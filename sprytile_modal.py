import math
from collections import deque

import bmesh
import bpy
import numpy
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_line_plane, distance_point_to_plane

from rx import Observable
from sprytile_tools.tool_build import ToolBuild
from sprytile_tools.tool_paint import ToolPaint
from . import sprytile_utils


class DataObjectDict(dict):
    def __getattr__(self, name):
        if name in self:
            return self[name]
        else:
            raise AttributeError("No such attribute: " + name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        if name in self:
            del self[name]
        else:
            raise AttributeError("No such attribute: " + name)


def snap_vector_to_axis(vector, mirrored=False):
    """Snaps a vector to the closest world axis"""
    norm_vector = vector.normalized()

    x = Vector((1.0, 0.0, 0.0))
    y = Vector((0.0, 1.0, 0.0))
    z = Vector((0.0, 0.0, 1.0))

    x_dot = 1 - abs(norm_vector.dot(x))
    y_dot = 1 - abs(norm_vector.dot(y))
    z_dot = 1 - abs(norm_vector.dot(z))
    dot_array = [x_dot, y_dot, z_dot]
    closest = min(dot_array)

    if closest is dot_array[0]:
        snapped_vector = x
    elif closest is dot_array[1]:
        snapped_vector = y
    else:
        snapped_vector = z

    vector_dot = norm_vector.dot(snapped_vector)
    if mirrored is False and vector_dot < 0:
        snapped_vector *= -1
    elif mirrored is True and vector_dot > 0:
        snapped_vector *= -1

    return snapped_vector


def get_current_grid_vectors(scene, with_rotation=True):
    """Returns the current grid X/Y/Z vectors from scene data
    :param scene: scene data
    :param with_rotation: bool, rotate the grid vectors by sprytile_data
    :return: up_vector, right_vector, normal_vector
    """
    data_normal = scene.sprytile_data.paint_normal_vector
    data_up_vector = scene.sprytile_data.paint_up_vector

    normal_vector = Vector((data_normal[0], data_normal[1], data_normal[2]))
    up_vector = Vector((data_up_vector[0], data_up_vector[1], data_up_vector[2]))

    normal_vector.normalize()
    up_vector.normalize()
    right_vector = up_vector.cross(normal_vector)

    if with_rotation:
        rotation = Quaternion(-normal_vector, scene.sprytile_data.mesh_rotate)
        up_vector = rotation * up_vector
        right_vector = rotation * right_vector

    return up_vector, right_vector, normal_vector


def get_uv_positions(data, image_size, target_grid, up_vector, right_vector, tile_xy, verts, vtx_center):
    """Given world vertices, find the UV position for each vert"""

    pixel_uv_x = 1.0 / image_size[0]
    pixel_uv_y = 1.0 / image_size[1]
    uv_unit_x = pixel_uv_x * target_grid.grid[0]
    uv_unit_y = pixel_uv_y * target_grid.grid[1]
    world_units = data.world_pixels
    world_convert = Vector((target_grid.grid[0] / world_units,
                            target_grid.grid[1] / world_units))

    # Build the translation matrix
    offset_matrix = Matrix.Translation((target_grid.offset[0] * pixel_uv_x, target_grid.offset[1] * pixel_uv_y, 0))
    rotate_matrix = Matrix.Rotation(target_grid.rotate, 4, 'Z')
    uv_matrix = Matrix.Translation((uv_unit_x * tile_xy[0], uv_unit_y * tile_xy[1], 0))
    uv_matrix = offset_matrix * rotate_matrix * uv_matrix

    flip_x = -1 if data.uv_flip_x else 1
    flip_y = -1 if data.uv_flip_y else 1
    flip_matrix = Matrix.Scale(flip_x, 4, right_vector) * Matrix.Scale(flip_y, 4, up_vector)

    uv_min = Vector((float('inf'), float('inf')))
    uv_max = Vector((float('-inf'), float('-inf')))

    uv_verts = []
    for vert in verts:
        # Around center
        vert_pos = vert - vtx_center
        # Apply flip scaling
        vert_pos = flip_matrix * vert_pos
        # Get x/y values by using the right/up vectors
        vert_xy = (right_vector.dot(vert_pos), up_vector.dot(vert_pos), 0)
        vert_xy = Vector(vert_xy)
        # Convert to -0.5 to 0.5 space
        vert_xy.x /= world_convert.x
        vert_xy.y /= world_convert.y
        # Offset by half, to move coordinates back into 0-1 range
        vert_xy += Vector((0.5, 0.5, 0))
        # Multiply by the uv unit sizes to get actual UV space
        vert_xy.x *= uv_unit_x
        vert_xy.y *= uv_unit_y
        # Then offset the actual UV space by the translation matrix
        vert_xy = uv_matrix * vert_xy
        # Record min/max for tile alignment step
        uv_min.x = min(uv_min.x, vert_xy.x)
        uv_min.y = min(uv_min.y, vert_xy.y)
        uv_max.x = max(uv_max.x, vert_xy.x)
        uv_max.y = max(uv_max.y, vert_xy.y)
        # Save to uv verts
        uv_verts.append(vert_xy)

    # In paint mode, do alignment and stretching steps
    if data.paint_mode == 'PAINT':
        # Convert vert origin to UV space, for use with paint modify
        uv_center = Vector((0.5, 0.5, 0.0))
        uv_center.x *= uv_unit_x
        uv_center.y *= uv_unit_y
        uv_center = uv_matrix * uv_center
        uv_verts = get_uv_paint_modify(data, uv_verts, uv_matrix,
                                       uv_unit_x, uv_unit_y, uv_min, uv_max,
                                       uv_center, Vector((pixel_uv_x, pixel_uv_y)))

    # One final loop to snap the UVs to the pixel grid
    # Always snap if not in paint mode, paint mode does
    # UV snapping in UV map paint modify function
    do_snap = data.paint_mode != 'PAINT'
    if do_snap and pixel_uv_x > 0 and pixel_uv_y > 0:
        for uv_vert in uv_verts:
            p_x = uv_vert.x / pixel_uv_x
            p_y = uv_vert.y / pixel_uv_y
            if math.isnan(p_x) or math.isnan(p_y):
                return None
            uv_pixel_x = int(round(p_x))
            uv_pixel_y = int(round(p_y))
            uv_vert.x = uv_pixel_x * pixel_uv_x
            uv_vert.y = uv_pixel_y * pixel_uv_y

    return uv_verts


def get_uv_paint_modify(data, uv_verts, uv_matrix, uv_unit_x, uv_unit_y, uv_min, uv_max, uv_center, pixel_uv):
    paint_align = data.paint_align
    # Stretching will change how the tile will be aligned
    if data.paint_stretch_x:
        if paint_align in {'TOP_LEFT', 'TOP_RIGHT'}:
            paint_align = "TOP"
        if paint_align in {'LEFT', 'RIGHT'}:
            paint_align = 'CENTER'
        if paint_align in {'BOTTOM_LEFT', 'BOTTOM_RIGHT'}:
            paint_align = 'BOTTOM'
    if data.paint_stretch_y:
        if paint_align in {'TOP_LEFT', 'BOTTOM_LEFT'}:
            paint_align = 'LEFT'
        if paint_align in {'TOP', 'BOTTOM'}:
            paint_align = 'CENTER'
        if paint_align in {'TOP_RIGHT', 'BOTTOM_RIGHT'}:
            paint_align = 'RIGHT'

    # Generate where tile min/max points are
    tile_min = uv_matrix * Vector((0, 0, 0))
    tile_max = uv_matrix * Vector((uv_unit_x, uv_unit_y, 0))

    # Calculate tile stretch
    scale_x = 1
    scale_y = 1
    tile_size = tile_max - tile_min
    face_size = uv_max - uv_min

    if data.paint_stretch_x and face_size.x > 0:
        scale_x = tile_size.x / face_size.x
    if data.paint_stretch_y and face_size.y > 0:
        scale_y = tile_size.y / face_size.y

    matrix_stretch = Matrix.Scale(scale_x, 2, Vector((1, 0))) * Matrix.Scale(scale_y, 2, Vector((0, 1)))

    threshold = tile_size * data.edge_threshold
    for uv_vert in uv_verts:
        # First, apply the stretch matrix
        uv = Vector((uv_vert.x, uv_vert.y))
        uv -= uv_center.xy
        uv = matrix_stretch * uv
        uv += uv_center.xy
        # Next, check if want to snap to edges
        if data.paint_edge_snap:
            if data.paint_stretch_x:
                if abs(uv.x - tile_min.x) < threshold.x:
                    uv.x = tile_min.x
                if abs(uv.x - tile_max.x) < threshold.x:
                    uv.x = tile_max.x
            if data.paint_stretch_y:
                if abs(uv.y - tile_min.y) < threshold.y:
                    uv.y = tile_min.y
                if abs(uv.y - tile_max.y) < threshold.y:
                    uv.y = tile_max.y
        # Pixel snap now, because alignment step depends on it
        if data.paint_uv_snap and pixel_uv.x > 0 and pixel_uv.y > 0 and uv.x > 0 and uv.y > 0:
            uv_pixel_x = int(round(uv.x / pixel_uv.x))
            uv_pixel_y = int(round(uv.y / pixel_uv.y))
            uv.x = uv_pixel_x * pixel_uv.x
            uv.y = uv_pixel_y * pixel_uv.y
        # Record min/max for tile alignment step
        uv_min.x = min(uv_min.x, uv.x)
        uv_min.y = min(uv_min.y, uv.y)
        uv_max.x = max(uv_max.x, uv.x)
        uv_max.y = max(uv_max.y, uv.y)
        # Save UV position
        uv_vert.x = uv.x
        uv_vert.y = uv.y

    # Only do align if not center
    if paint_align != 'CENTER':
        # Use the recorded min/max points to calculate offset
        uv_offset = Vector((0, 0))
        # Calculate x offsets
        if paint_align in {'TOP_LEFT', 'LEFT', 'BOTTOM_LEFT'}:
            uv_offset.x = tile_min.x - uv_min.x
        elif paint_align in {'TOP_RIGHT', 'RIGHT', 'BOTTOM_RIGHT'}:
            uv_offset.x = tile_max.x - uv_max.x
        # Calculate y offsets
        if paint_align in {'TOP_LEFT', 'TOP', 'TOP_RIGHT'}:
            uv_offset.y = tile_max.y - uv_max.y
        if paint_align in {'BOTTOM_LEFT', 'BOTTOM', 'BOTTOM_RIGHT'}:
            uv_offset.y = tile_min.y - uv_min.y
        for uv_vert in uv_verts:
            uv_vert.x += uv_offset.x
            uv_vert.y += uv_offset.y

    return uv_verts


def uv_map_face(context, up_vector, right_vector, tile_xy, face_index, mesh):
    """UV map the given face"""
    if mesh is None:
        return None, None

    scene = context.scene
    obj = context.object
    data = scene.sprytile_data

    grid_id = obj.sprytile_gridid
    target_grid = sprytile_utils.get_grid(context, grid_id)

    uv_layer = mesh.loops.layers.uv.verify()
    mesh.faces.layers.tex.verify()

    if face_index >= len(mesh.faces):
        return None, None

    target_img = sprytile_utils.get_grid_texture(obj, target_grid)
    if target_img is None:
        return None, None

    face = mesh.faces[face_index]
    if face.hide:
        return None, None

    vert_origin = context.object.matrix_world * face.calc_center_bounds()
    verts = []
    for loop in face.loops:
        vert = loop.vert
        verts.append(context.object.matrix_world * vert.co)

    uv_verts = get_uv_positions(data, target_img.size, target_grid,
                                up_vector, right_vector, tile_xy,
                                verts, vert_origin)

    if uv_verts is None:
        return None, None

    # Apply the UV positions on the face verts
    idx = 0
    for loop in face.loops:
        loop[uv_layer].uv = uv_verts[idx].xy
        idx += 1

    # Apply the correct material to the face
    mat_idx = context.object.material_slots.find(target_grid.mat_id)
    if mat_idx > -1:
        face.material_index = mat_idx

    # Save the grid and tile ID to the face
    grid_layer_id = mesh.faces.layers.int.get('grid_index')
    grid_layer_tileid = mesh.faces.layers.int.get('grid_tile_id')
    paint_settings_id = mesh.faces.layers.int.get('paint_settings')

    if grid_layer_id is None:
        grid_layer_id = mesh.faces.layers.int.new('grid_index')
    if grid_layer_tileid is None:
        grid_layer_tileid = mesh.faces.layers.int.new('grid_tile_id')
    if paint_settings_id is None:
        paint_settings_id = mesh.faces.layers.int.new('paint_settings')

    face = mesh.faces[face_index]
    row_size = math.ceil(target_img.size[0] / target_grid.grid[0])
    tile_id = (tile_xy[1] * row_size) + tile_xy[0]

    paint_settings = sprytile_utils.get_paint_settings(data)

    face[grid_layer_id] = grid_id
    face[grid_layer_tileid] = tile_id
    face[paint_settings_id] = paint_settings

    bmesh.update_edit_mesh(obj.data)
    mesh.faces.index_update()
    return face.index, target_grid


def get_build_vertices(position, x_vector, y_vector, up_vector, right_vector):
    """Get the world position vertices for a new face, at the given position"""
    x_dot = right_vector.dot(x_vector.normalized())
    y_dot = up_vector.dot(y_vector.normalized())
    x_positive = x_dot > 0
    y_positive = y_dot > 0

    # These are in world positions
    vtx1 = position
    vtx2 = position + y_vector
    vtx3 = position + x_vector + y_vector
    vtx4 = position + x_vector

    # Quadrant II, IV
    face_order = (vtx1, vtx2, vtx3, vtx4)
    # Quadrant I, III
    if x_positive == y_positive:
        face_order = (vtx1, vtx4, vtx3, vtx2)

    return face_order


class SprytileModalTool(bpy.types.Operator):
    """Tile based mesh creation/UV layout tool"""
    bl_idname = "sprytile.modal_tool"
    bl_label = "Sprytile Paint"
    bl_options = {'REGISTER'}

    preview_verts = None
    preview_uvs = None

    modal_map = bpy.props.EnumProperty(
        items=[
            ("SNAP", "Snap Cursor", "", 1),
            ("FOCUS", "Focus on Cursor", "", 2),
            ("ROTATE_LEFT", "Rotate Left", "", 3),
            ("ROTATE_RIGHT", "Rotate Right", "", 4),
        ],
        name="Sprytile Paint Modal Map"
    )

    keymaps = {}
    modal_values = []

    @staticmethod
    def find_view_axis(context):
        if context.area.type != 'VIEW_3D':
            return
        scene = context.scene
        if scene.sprytile_data.lock_normal is True:
            return

        region = context.region
        rv3d = context.region_data

        # Get the view ray from center of screen
        coord = Vector((int(region.width / 2), int(region.height / 2)))
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        # Get the up vector. The default scene view camera is pointed
        # downward, with up on Y axis. Apply view rotation to get current up
        view_up_vector = rv3d.view_rotation * Vector((0.0, 1.0, 0.0))

        plane_normal = snap_vector_to_axis(view_vector, mirrored=True)
        up_vector = snap_vector_to_axis(view_up_vector)

        # calculated vectors are not perpendicular, don't set data
        if plane_normal.dot(up_vector) != 0.0:
            return

        scene.sprytile_data.paint_normal_vector = plane_normal
        scene.sprytile_data.paint_up_vector = up_vector

        if abs(plane_normal.x) > 0:
            new_mode = 'X'
        elif abs(plane_normal.y) > 0:
            new_mode = 'Y'
        else:
            new_mode = 'Z'

        return new_mode

    def get_face_tiledata(self, face):
        grid_id_layer = self.bmesh.faces.layers.int.get('grid_index')
        tile_id_layer = self.bmesh.faces.layers.int.get('grid_tile_id')
        if grid_id_layer is None or tile_id_layer is None:
            return None, None

        grid_id = face[grid_id_layer]
        tile_packed_id = face[tile_id_layer]
        return grid_id, tile_packed_id

    def find_face_tile(self, context, event):
        if self.tree is None or context.scene.sprytile_ui.use_mouse is True:
            return

        # get the context arguments
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y

        # get the ray from the viewport and mouse
        ray_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

        location, normal, face_index, distance = self.raycast_object(context.object, ray_origin, ray_vector)
        if location is None:
            return

        face = self.bmesh.faces[face_index]

        grid_id, tile_packed_id = self.get_face_tiledata(face)
        if None in {grid_id, tile_packed_id}:
            return

        tilegrid = sprytile_utils.get_grid(context, grid_id)
        if tilegrid is None:
            return

        texture = sprytile_utils.get_grid_texture(context.object, tilegrid)
        if texture is None:
            return

        paint_setting_layer = self.bmesh.faces.layers.int.get('paint_settings')
        if paint_setting_layer is not None:
            paint_setting = face[paint_setting_layer]
            sprytile_utils.from_paint_settings(context.scene.sprytile_data, paint_setting)

        row_size = math.ceil(texture.size[0] / tilegrid.grid[0])
        tile_y = math.floor(tile_packed_id / row_size)
        tile_x = tile_packed_id % row_size

        context.object.sprytile_gridid = grid_id
        tilegrid.tile_selection[0] = tile_x
        tilegrid.tile_selection[1] = tile_y

        bpy.ops.sprytile.build_grid_list()

    def add_virtual_cursor(self, cursor_pos):
        cursor_len = len(self.virtual_cursor)
        if cursor_len == 0:
            self.virtual_cursor.append(cursor_pos)
            return

        last_pos = self.virtual_cursor[cursor_len - 1]
        last_vector = cursor_pos - last_pos
        if last_vector.magnitude < 0.1:
            return

        self.virtual_cursor.append(cursor_pos)

    def get_virtual_cursor_vector(self):
        cursor_direction = Vector((0.0, 0.0, 0.0))
        cursor_len = len(self.virtual_cursor)
        if cursor_len <= 1:
            return cursor_direction
        for idx in range(cursor_len - 1):
            segment = self.virtual_cursor[idx + 1] - self.virtual_cursor[idx]
            cursor_direction += segment
        cursor_direction /= cursor_len
        return cursor_direction

    def flow_cursor(self, context, face_index, virtual_cursor):
        """Move the cursor along the given face, using virtual_cursor direction"""
        cursor_len = len(self.virtual_cursor)
        if cursor_len <= 1:
            return

        cursor_direction = self.get_virtual_cursor_vector()
        cursor_direction.normalize()

        face = self.bmesh.faces[face_index]
        max_dot = 1.0
        closest_idx = -1
        closest_pos = Vector((0.0, 0.0, 0.0))
        for idx, vert in enumerate(face.verts):
            vert_world_pos = context.object.matrix_world * vert.co
            vert_vector = vert_world_pos - virtual_cursor
            vert_vector.normalize()
            vert_dot = abs(1.0 - vert_vector.dot(cursor_direction))
            if vert_dot < max_dot:
                closest_idx = idx
                closest_pos = vert_world_pos

        if closest_idx != -1:
            context.scene.cursor_location = closest_pos

    def raycast_grid_coord(self, context, obj, x, y, up_vector, right_vector, normal):
        ray_origin = Vector(context.scene.cursor_location)
        ray_origin += (x + 0.5) * right_vector
        ray_origin += (y + 0.5) * up_vector
        ray_origin += normal * 0.01
        ray_direction = -normal

        return self.raycast_object(obj, ray_origin, ray_direction, 0.02)

    def raycast_object(self, obj, ray_origin, ray_direction, ray_dist=1000000, world_normal=False):
        matrix = obj.matrix_world.copy()
        # get the ray relative to the object
        matrix_inv = matrix.inverted()
        ray_origin_obj = matrix_inv * ray_origin
        ray_target_obj = matrix_inv * (ray_origin + ray_direction)
        ray_direction_obj = ray_target_obj - ray_origin_obj

        location, normal, face_index, distance = self.tree.ray_cast(ray_origin_obj, ray_direction_obj, ray_dist)
        if face_index is None:
            return None, None, None, None

        face = self.bmesh.faces[face_index]
        shift_vec = ray_direction.normalized() * 0.001
        # Shoot through backface
        if face.normal.dot(ray_direction) > 0:
            return self.raycast_object(obj, location + shift_vec, ray_direction)
        # Shoot through hidden face
        if face.hide:
            return self.raycast_object(obj, location + shift_vec, ray_direction)

        # Translate location back to world space
        location = matrix * location
        if world_normal:
            normal = matrix * normal
        return location, normal, face_index, distance

    def execute_tool(self, context, event, is_preview=False):
        """Run the paint tool"""
        # Don't do anything if nothing to raycast on
        # or the GL GUI is using the mouse
        if self.tree is None or context.scene.sprytile_ui.use_mouse is True:
            return

        # get the context arguments
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y

        if rv3d is None:
            return

        # get the ray from the viewport and mouse
        ray_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

        build_preview = is_preview and not self.refresh_mesh

        self.build_preview(build_preview, context, ray_origin, ray_vector)
        if build_preview:
            return

        # if paint mode, ray cast against object
        paint_mode = scene.sprytile_data.paint_mode
        if paint_mode == 'PAINT':
            self.execute_paint(context, ray_origin, ray_vector)
        # if build mode, ray cast on plane and build face
        elif paint_mode == 'MAKE_FACE':
            self.execute_build(context, scene, ray_origin, ray_vector)
        # set normal mode...
        elif paint_mode == 'SET_NORMAL':
            self.execute_set_normal(context, rv3d, ray_origin, ray_vector)
        elif paint_mode == 'FILL':
            self.execute_fill(context, scene, ray_origin, ray_vector)

    def execute_paint(self, context, ray_origin, ray_vector):
        up_vector, right_vector, plane_normal = get_current_grid_vectors(context.scene)
        hit_loc, normal, face_index, distance = self.raycast_object(context.object, ray_origin, ray_vector, world_normal=True)
        if face_index is None:
            print("No hit")
            return

        normal.normalize()

        self.add_virtual_cursor(hit_loc)
        # Change the uv of the given face
        grid_id = context.object.sprytile_gridid
        grid = sprytile_utils.get_grid(context, grid_id)
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])

        face_up, face_right = self.get_face_up_vector(context, face_index)
        data = context.scene.sprytile_data

        rotate_normal = plane_normal
        if face_up is not None and face_right is not None:
            rotate_normal = face_up.cross(face_right)
        
        rotate_matrix = Quaternion(-rotate_normal, data.mesh_rotate)
        if face_up is not None:
            up_vector = rotate_matrix * face_up
        if face_right is not None:
            right_vector = rotate_matrix * face_right

        up_vector.normalize()
        right_vector.normalize()
        # print("Up vector:", up_vector, "Right vector:", right_vector)
        # print("Up mag:", up_vector.magnitude, "Right mag:", right_vector.magnitude)
        uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.bmesh)

    def execute_fill(self, context, scene, ray_origin, ray_vector):
        up_vector, right_vector, plane_normal =  get_current_grid_vectors(scene, with_rotation=False)

        # Intersect on the virtual plane
        plane_hit = intersect_line_plane(ray_origin, ray_origin + ray_vector, scene.cursor_location, plane_normal)
        # Didn't hit the plane exit
        if plane_hit is None:
            return

        grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
        sprytile_data = scene.sprytile_data

        world_pixels = sprytile_data.world_pixels
        grid_x = grid.grid[0]
        grid_y = grid.grid[1]

        # Find the position of the plane hit, in terms of grid coordinates
        hit_coord, grid_right, grid_up = sprytile_utils.get_grid_pos(
                                                plane_hit, scene.cursor_location,
                                                right_vector.copy(), up_vector.copy(),
                                                world_pixels, grid_x, grid_y, as_coord=True
                                            )
        
        # Check hit_coord is inside the work plane grid
        plane_size = sprytile_data.axis_plane_size
        if hit_coord.x < -plane_size[0] or hit_coord.x >= plane_size[0]:
            return
        if hit_coord.y < -plane_size[1] or hit_coord.y >= plane_size[1]:
            return

        # Use raycast_grid_coord to build a 2d array of work plane
        fill_array = numpy.zeros((plane_size[1] * 2, plane_size[0] * 2))
        face_idx_array = numpy.zeros((plane_size[1] * 2, plane_size[0] * 2))
        face_idx_array.fill(-1)
        for y in range(plane_size[1] * 2):
            y_coord = plane_size[1] - 1 - y
            for x in range(plane_size[0] * 2):
                x_coord = -plane_size[0] + x
                hit_loc, hit_normal, face_index, hit_dist = self.raycast_grid_coord(
                                            context, context.object, x_coord, y_coord,
                                            grid_up, grid_right, plane_normal)
                if hit_loc is not None:
                    grid_id, tile_packed_id = self.get_face_tiledata(self.bmesh.faces[face_index])
                    map_value = 1
                    if tile_packed_id is not None:
                        map_value = tile_packed_id
                    fill_array[y][x] = map_value
                    face_idx_array[y][x] = face_index
                x_coord += 1
            y_coord += 1
        # Convert from grid coordinate to map coordinate
        hit_array_coord = [int(hit_coord.x) + plane_size[0],
                           int((plane_size[1] * 2) - 1 - (hit_coord.y + plane_size[1]))]

        # Calculate the tile index of currently selected tile
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])
        # For getting paint settings later
        paint_setting_layer = self.bmesh.faces.layers.int.get('paint_settings')

        # Pre calculate for auto merge
        shift_vec = plane_normal.normalized() * 0.01
        threshold = (1 / context.scene.sprytile_data.world_pixels) * 2

        # Get vectors again, to apply tile rotations in UV stage
        up_vector, right_vector, plane_normal = get_current_grid_vectors(scene)

        # Flood fill targets map cell coordinates
        hit_coord_content = int(fill_array[hit_array_coord[1]][hit_array_coord[0]])
        fill_coords = self.flood_fill(fill_array, hit_array_coord, -1, hit_coord_content)
        # Build the faces and UV map them
        for cell_coord in fill_coords:
            grid_coord = [-plane_size[0] + cell_coord[0],
                          plane_size[1] - 1 - cell_coord[1]]

            # Check face index array, if -1, create face
            face_index = face_idx_array[cell_coord[1]][cell_coord[0]]
            did_build = False
            # If no existing face, build it
            if face_index < 0:
                did_build = True
                face_position = scene.cursor_location + grid_coord[0] * grid_right + grid_coord[1] * grid_up
                face_index = self.build_face(context, face_position,
                                             grid_right, grid_up,
                                             up_vector, right_vector)
            # Face existing...
            else:
                # Raycast to get the face index of the face, could have changed
                hit_loc, hit_normal, face_index, hit_dist = self.raycast_grid_coord(
                                            context, context.object,
                                            grid_coord[0], grid_coord[1],
                                            grid_up, grid_right, plane_normal)

                # use the face paint settings for the UV map step
                face = self.bmesh.faces[face_index]
                if sprytile_data.fill_lock_transform and paint_setting_layer is not None:
                    paint_setting = face[paint_setting_layer]
                    sprytile_utils.from_paint_settings(context.scene.sprytile_data, paint_setting)

            face_up, face_right = self.get_face_up_vector(context, face_index)
            if face_up is not None and face_up.dot(up_vector) < 0.95:
                data = context.scene.sprytile_data
                rotate_matrix = Matrix.Rotation(data.mesh_rotate, 4, plane_normal)
                up_vector = rotate_matrix * face_up
                right_vector = rotate_matrix * face_right

            uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.bmesh)

            if did_build and sprytile_data.auto_merge:
                face = self.bmesh.faces[face_index]
                face.select = True
                # Find the face center, to raycast from later
                face_center = context.object.matrix_world * face.calc_center_bounds()
                # Move face center back a little for ray casting
                face_center += shift_vec

                bpy.ops.mesh.remove_doubles(threshold=threshold, use_unselected=True)

                for el in [self.bmesh.faces, self.bmesh.verts, self.bmesh.edges]:
                    el.index_update()
                    el.ensure_lookup_table()

                # Modified the mesh, refresh and raycast to find the new face index
                self.bmesh = bmesh.from_edit_mesh(context.object.data)
                self.tree = BVHTree.FromBMesh(self.bmesh)
                loc, norm, new_face_idx, hit_dist = self.raycast_object(context.object, face_center, ray_vector, 0.1)
                if new_face_idx is not None:
                    self.bmesh.faces[new_face_idx].select = False

        # Refresh BVHTree collision
        self.bmesh = bmesh.from_edit_mesh(context.object.data)
        self.tree = BVHTree.FromBMesh(self.bmesh)

    def flood_fill(self, fill_map, start_coord, new_tile_idx, old_tile_idx):
        flood_stack = []
        if new_tile_idx == old_tile_idx:
            return flood_stack
        fill_stack = [start_coord]

        def scan_line(test_x, test_y, current):
            if not current and fill_map[test_y][test_x] == old_tile_idx:
                line_coord = [test_x, test_y]
                fill_stack.append(line_coord)
                return True
            elif current and fill_map[test_y][test_x] != old_tile_idx:
                return False
            return current

        height = len(fill_map)
        # Run scanline fill, adding target grid coords to build stack
        while len(fill_stack) > 0:
            coord = fill_stack.pop()
            x = coord[0]
            y = coord[1]
            line = fill_map[y]
            # Move the x index back in this line until hit a filled tile
            while x >= 0 and line[x] == old_tile_idx:
                x -= 1
            x += 1
            span_above = False
            span_below = False
            width = len(line)
            # y axis, 0 is top
            while x < width and line[x] == old_tile_idx:
                cell_coord = [x, y]
                # Add the grid coordinate to this list to build face later
                flood_stack.append(cell_coord)
                # Set fill map value
                fill_map[y][x] = new_tile_idx
                # Scan line above
                if y > 0:
                    span_above = scan_line(x, y - 1, span_above)
                # Scan line below
                if y < height - 1:
                    span_below = scan_line(x, y + 1, span_below)
                x += 1
        return flood_stack

    def build_preview(self, do_build, context, ray_origin, ray_vector):
        SprytileModalTool.preview_verts = None
        SprytileModalTool.preview_uvs = None

        # Something probably changed upstream, don't build now
        if self.refresh_mesh or do_build is False:
            return

        scene = context.scene
        obj = context.object
        data = scene.sprytile_data

        grid_id = obj.sprytile_gridid
        target_grid = sprytile_utils.get_grid(context, grid_id)

        target_img = sprytile_utils.get_grid_texture(obj, target_grid)
        if target_img is None:
            return

        up_vector, right_vector, plane_normal = get_current_grid_vectors(scene, False)

        # Raycast to the virtual grid
        face_position, x_vector, y_vector, plane_cursor = sprytile_utils.raycast_grid(
                                                                scene, context,
                                                                up_vector, right_vector, plane_normal,
                                                                ray_origin, ray_vector
                                                            )

        preview_verts = []

        # Raycast the object
        hit_loc, hit_normal, face_index, hit_dist = self.raycast_object(obj, ray_origin, ray_vector)
        # Did hit mesh...
        if face_index is not None:
            # In paint mode, just gather world positions of hit face
            if data.paint_mode == 'PAINT':
                face = self.bmesh.faces[face_index]
                for loop in face.loops:
                    vert = loop.vert
                    preview_verts.append(context.object.matrix_world * vert.co)
            elif face_position is not None:
                grid_hit_dist = (face_position - ray_origin).magnitude
                # Mesh hit closer than grid hit, check coplanarity and dot value before rejecting
                if hit_dist < grid_hit_dist:
                    check_dot = abs(plane_normal.dot(hit_normal))
                    check_dot -= 1
                    check_coplanar = distance_point_to_plane(hit_loc, scene.cursor_location, plane_normal)

                    check_coplanar = abs(check_coplanar) < 0.05
                    check_dot = abs(check_dot) < 0.05
                    # Hitting the mesh, get the preview verts from the hit face
                    if not check_dot or not check_coplanar:
                        return

        if data.paint_mode == 'MAKE_FACE' and face_position is None:
            return
        # Didn't hit mesh in paint mode, do nothing
        if data.paint_mode == 'PAINT' and len(preview_verts) == 0:
            return

        # Preview verts still empty, verts will be taken from the grid
        if len(preview_verts) < 1:
            preview_verts = get_build_vertices(face_position, x_vector, y_vector,
                                               up_vector, right_vector)

        # Get the center of the preview verts
        vtx_center = Vector((0, 0, 0))
        for vtx in preview_verts:
            vtx_center += vtx
        vtx_center /= len(preview_verts)

        rotate_normal = plane_normal

        # In paint mode, recalculate the rotation normal
        if data.paint_mode == 'PAINT' and face_index is not None:
            face_up, face_right = self.get_face_up_vector(context, face_index)

            if face_up is not None and face_right is not None:
                rotate_normal = face_right.cross(face_up)

            if face_up is not None:
                up_vector = face_up
            if face_right is not None:
                right_vector = face_right

        rotation = Quaternion(rotate_normal, data.mesh_rotate)
        up_vector = rotation * up_vector
        right_vector = rotation * right_vector

        up_vector.normalize()
        right_vector.normalize()

        tile_xy = (target_grid.tile_selection[0], target_grid.tile_selection[1])
        preview_uvs = get_uv_positions(data, target_img.size, target_grid,
                                       up_vector, right_vector, tile_xy,
                                       preview_verts, vtx_center)

        SprytileModalTool.preview_verts = preview_verts
        SprytileModalTool.preview_uvs = preview_uvs

    def execute_build(self, context, scene, ray_origin, ray_vector):
        grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])

        up_vector, right_vector, plane_normal = get_current_grid_vectors(scene)
        hit_loc, hit_normal, face_index, hit_dist = self.raycast_object(context.object, ray_origin, ray_vector)

        # Used to move raycast slightly along ray vector
        shift_vec = ray_vector.normalized() * 0.001

        # If raycast hit the mesh...
        if face_index is not None:
            # The face is valid for painting if hit face
            # is facing same way as plane normal and is coplanar to target plane
            check_dot = abs(plane_normal.dot(hit_normal))
            check_dot -= 1
            check_coplanar = distance_point_to_plane(hit_loc, scene.cursor_location, plane_normal)

            check_coplanar = abs(check_coplanar) < 0.05
            check_dot = abs(check_dot) < 0.05
            # Hit a face that is valid for painting
            if check_dot and check_coplanar:
                self.add_virtual_cursor(hit_loc)
                # Change UV of this face instead
                face_up, face_right = self.get_face_up_vector(context, face_index)
                if face_up is not None and face_up.dot(up_vector) < 0.95:
                    data = context.scene.sprytile_data
                    rotate_matrix = Matrix.Rotation(data.mesh_rotate, 4, hit_normal)
                    up_vector = rotate_matrix * face_up
                    right_vector = rotate_matrix * face_right
                uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.bmesh)
                if scene.sprytile_data.cursor_flow:
                    self.flow_cursor(context, face_index, hit_loc)
                return

        # Raycast did not hit the mesh, raycast to the virtual grid
        face_position, x_vector, y_vector, plane_cursor = sprytile_utils.raycast_grid(
                                                            scene, context,
                                                            up_vector, right_vector, plane_normal,
                                                            ray_origin, ray_vector
                                                        )
        # Failed to hit the grid
        if face_position is None:
            return

        # If raycast hit mesh, compare distance of grid hit and mesh hit
        if hit_loc is not None:
            grid_hit_dist = (face_position - ray_origin).magnitude
            # Mesh hit closer than grid hit, don't do anything
            if hit_dist < grid_hit_dist:
                return

        # store plane_cursor, for deciding where to move actual cursor if auto cursor mode is on
        self.add_virtual_cursor(plane_cursor)
        # Build face and UV map it
        face_index = self.build_face(context, face_position, x_vector, y_vector, up_vector, right_vector)

        face_up, face_right = self.get_face_up_vector(context, face_index)
        if face_up is not None and face_up.dot(up_vector) < 0.95:
            data = context.scene.sprytile_data
            rotate_matrix = Matrix.Rotation(data.mesh_rotate, 4, plane_normal)
            up_vector = rotate_matrix * face_up
            right_vector = rotate_matrix * face_right

        uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.bmesh)

        if scene.sprytile_data.auto_merge:
            face = self.bmesh.faces[face_index]
            face.select = True
            # Find the face center, to raycast from later
            face_center = context.object.matrix_world * face.calc_center_bounds()
            # Move face center back a little for ray casting
            face_center -= shift_vec

            threshold = (1 / context.scene.sprytile_data.world_pixels) * 2
            bpy.ops.mesh.remove_doubles(threshold=threshold, use_unselected=True)

            for el in [self.bmesh.faces, self.bmesh.verts, self.bmesh.edges]:
                el.index_update()
                el.ensure_lookup_table()

            # Modified the mesh, refresh and raycast to find the new face index
            self.bmesh = bmesh.from_edit_mesh(context.object.data)
            self.tree = BVHTree.FromBMesh(self.bmesh)
            loc, norm, new_face_idx, hit_dist = self.raycast_object(context.object, face_center, ray_vector)
            if new_face_idx is not None:
                self.bmesh.faces[new_face_idx].select = False
                face_index = new_face_idx
            else:
                face_index = -1

        # Auto merge refreshes the mesh automatically
        self.refresh_mesh = not scene.sprytile_data.auto_merge

        if scene.sprytile_data.cursor_flow and face_index is not None and face_index > -1:
            self.flow_cursor(context, face_index, plane_cursor)

    def build_face(self, context, position, x_vector, y_vector, up_vector, right_vector, selected=False):
        """Build a face at the given position"""
        if self.bmesh is None:
            self.refresh_mesh = True
            return None

        face_positions = get_build_vertices(position, x_vector, y_vector, up_vector, right_vector)
        face_vertices = []
        # Convert world space position to object space
        world_inv = context.object.matrix_world.copy().inverted()
        for face_vtx in face_positions:
            vtx = self.bmesh.verts.new(face_vtx)
            vtx.co = world_inv * vtx.co
            face_vertices.append(vtx)

        face = self.bmesh.faces.new(face_vertices)
        face.normal_update()
        if selected:
            face.select = True

        for el in [self.bmesh.faces, self.bmesh.verts, self.bmesh.edges]:
            el.index_update()
            el.ensure_lookup_table()

        bmesh.update_edit_mesh(context.object.data, True, True)

        # Update the collision BVHTree with new data
        self.refresh_mesh = True
        return face.index

    def get_face_up_vector(self, context, face_index):
        """Find the edge of the given face that most closely matches view up vector"""
        # Get the view up vector. The default scene view camera is pointed
        # downward, with up on Y axis. Apply view rotation to get current up

        rv3d = context.region_data
        view_up_vector = rv3d.view_rotation * Vector((0.0, 1.0, 0.0))
        view_right_vector = rv3d.view_rotation * Vector((1.0, 0.0, 0.0))
        data = context.scene.sprytile_data

        if self.bmesh is None or self.bmesh.faces is None:
            self.refresh_mesh = True
            return None, None

        world_matrix = context.object.matrix_world
        face = self.bmesh.faces[face_index]

        # Convert the face normal to world space
        normal_inv = context.object.matrix_world.copy().inverted().transposed()
        face_normal = normal_inv * face.normal.copy()

        do_hint = data.paint_mode in {'PAINT', 'SET_NORMAL'} and data.paint_hinting
        if do_hint:
            selection = self.bmesh.select_history.active
            if isinstance(selection, bmesh.types.BMEdge):
                # Figure out which side of the face this edge is on
                # selected edge is considered the bottom of the face
                vtx1 = world_matrix * selection.verts[0].co.copy()
                vtx2 = world_matrix * selection.verts[1].co.copy()
                edge_center = (vtx1 + vtx2) / 2
                face_center = world_matrix * face.calc_center_bounds()
                # Get the rough heading of the up vector
                estimated_up = face_center - edge_center
                estimated_up.normalize()

                sel_vector = vtx2 - vtx1
                sel_vector.normalize()

                # Cross the face normal and hint vector to get the up vector
                view_up_vector = face_normal.cross(sel_vector)
                view_up_vector.normalize()

                # If the calculated up faces away from rough up, reverse it
                if view_up_vector.dot(estimated_up) < 0:
                    view_up_vector *= -1
                    sel_vector *= -1
                return view_up_vector, sel_vector

        # Find the edge of the hit face that most closely matches
        # the view up / view right vectors
        closest_up = None
        closest_up_dot = 2.0
        closest_right = None
        closest_right_dot = 2.0
        idx = -1
        for edge in face.edges:
            idx += 1
            # Move vertices to world space
            vtx1 = world_matrix * edge.verts[0].co
            vtx2 = world_matrix * edge.verts[1].co
            edge_vec = vtx2 - vtx1
            edge_vec.normalize()
            edge_up_dot = 1 - abs(edge_vec.dot(view_up_vector))
            edge_right_dot = 1 - abs(edge_vec.dot(view_right_vector))
            # print(idx, edge_vec, "up dot", edge_up_dot, "right dot", edge_right_dot)
            if edge_up_dot < 0.1 and edge_up_dot < closest_up_dot:
                closest_up_dot = edge_up_dot
                closest_up = edge_vec
                # print("Setting", idx, "as closest up")
            if edge_right_dot < 0.1 and edge_right_dot < closest_right_dot:
                closest_right_dot = edge_right_dot
                closest_right = edge_vec
                # print("Setting", idx, "as closest right")

        # print("Closest indices: up", closest_up, "right", closest_right)
        chosen_up = None

        if closest_up is not None:
            if closest_up.dot(view_up_vector) < 0:
                closest_up *= -1
            chosen_up = closest_up
        elif closest_right is not None:
            if closest_right.dot(view_right_vector) < 0:
                closest_right *= -1
            chosen_up = face_normal.cross(closest_right)

        if do_hint and closest_right is not None:
            if closest_right.dot(view_right_vector) < 0:
                closest_right *= -1
            chosen_up = face_normal.cross(closest_right)

        # print("Chosen up", chosen_up)
        return chosen_up, closest_right

    def execute_set_normal(self, context, rv3d, ray_origin, ray_vector):
        hit_loc, hit_normal, face_index, distance = self.raycast_object(context.object, ray_origin, ray_vector)
        if hit_loc is None:
            return
        hit_normal = context.object.matrix_world.to_quaternion() * hit_normal

        face_up_vector, face_right_vector = self.get_face_up_vector(context, face_index)
        if face_up_vector is None:
            return

        sprytile_data = context.scene.sprytile_data
        sprytile_data.paint_normal_vector = hit_normal
        sprytile_data.paint_up_vector = face_up_vector
        sprytile_data.lock_normal = True
        sprytile_data.paint_mode = 'MAKE_FACE'

    def cursor_move_layer(self, context, direction):
        scene = context.scene
        target_grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
        grid_x = target_grid.grid[0]
        grid_y = target_grid.grid[1]
        layer_move = min(grid_x, grid_y)
        layer_move *= (1 / context.scene.sprytile_data.world_pixels)
        plane_normal = scene.sprytile_data.paint_normal_vector.copy()
        plane_normal *= layer_move * direction
        grid_position = scene.cursor_location + plane_normal
        scene.cursor_location = grid_position

    def cursor_snap(self, context, event):
        if self.tree is None or context.scene.sprytile_ui.use_mouse is True:
            return

        # get the context arguments
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y

        # get the ray from the viewport and mouse
        ray_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

        up_vector, right_vector, plane_normal = get_current_grid_vectors(scene)

        if event.type in self.is_keyboard_list and event.shift and event.value == 'PRESS':
            if scene.sprytile_data.cursor_snap == 'GRID':
                scene.sprytile_data.cursor_snap = 'VERTEX'
            else:
                scene.sprytile_data.cursor_snap = 'GRID'

        # Snap cursor, depending on setting
        if scene.sprytile_data.cursor_snap == 'GRID':
            location = intersect_line_plane(ray_origin, ray_origin + ray_vector, scene.cursor_location, plane_normal)
            if location is None:
                return
            world_pixels = scene.sprytile_data.world_pixels
            target_grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
            grid_x = target_grid.grid[0]
            grid_y = target_grid.grid[1]

            grid_position, x_vector, y_vector = sprytile_utils.get_grid_pos(
                                                    location, scene.cursor_location,
                                                    right_vector.copy(), up_vector.copy(),
                                                    world_pixels, grid_x, grid_y
                                                )
            scene.cursor_location = grid_position

        elif scene.sprytile_data.cursor_snap == 'VERTEX':
            location, normal, face_index, distance = self.raycast_object(context.object, ray_origin, ray_vector)
            if location is None:
                return
            # Location in world space, convert to object space
            matrix = context.object.matrix_world.copy()
            matrix_inv = matrix.inverted()
            location, normal, face_index, dist = self.tree.find_nearest(matrix_inv * location)
            if location is None:
                return

            # Found the nearest face, go to BMesh to find the nearest vertex
            if self.bmesh is None:
                self.refresh_mesh = True
                return
            if face_index >= len(self.bmesh.faces) or face_index < 0:
                return
            face = self.bmesh.faces[face_index]
            closest_vtx = -1
            closest_dist = float('inf')
            # positions are in object space
            for vtx_idx, vertex in enumerate(face.verts):
                test_dist = (location - vertex.co).magnitude
                if test_dist < closest_dist:
                    closest_vtx = vtx_idx
                    closest_dist = test_dist
            # convert back to world space
            if closest_vtx != -1:
                scene.cursor_location = matrix * face.verts[closest_vtx].co

    def modal(self, context, event):
        do_exit = False
        sprytile_data = context.scene.sprytile_data
        if sprytile_data.is_running is False:
            do_exit = True
        if context.object.mode != 'EDIT':
            do_exit = True
        if do_exit:
            self.exit_modal(context)
            return {'CANCELLED'}

        if self.rx_observer is not None:
            self.rx_observer.on_next(
                DataObjectDict(
                    paint_mode=sprytile_data.paint_mode,
                    event=event
                )
            )

        if self.no_undo and sprytile_data.is_grid_translate is False:
            print("no undo on, grid translate off")
            self.no_undo = False

        if event.type == 'TIMER':
            view_axis = self.find_view_axis(context)
            if view_axis is not None:
                if view_axis != sprytile_data.normal_mode:
                    self.virtual_cursor.clear()
                    sprytile_data.normal_mode = view_axis
                    sprytile_data.lock_normal = False
            return {'PASS_THROUGH'}

        # Mouse move triggers preview drawing
        draw_preview = sprytile_data.paint_mode in {'MAKE_FACE', 'FILL', 'PAINT'}
        if draw_preview:
            if (event.alt or context.scene.sprytile_ui.use_mouse) or sprytile_data.is_snapping:
                draw_preview = False

        # Refreshing the mesh, preview needs constantly refreshed
        # mesh or bad things seem to happen. This can potentially get expensive
        if self.refresh_mesh or self.bmesh.is_valid is False or draw_preview:
            self.bmesh = bmesh.from_edit_mesh(context.object.data)
            for el in [self.bmesh.faces, self.bmesh.verts, self.bmesh.edges]:
                el.index_update()
                el.ensure_lookup_table()
            self.bmesh = bmesh.from_edit_mesh(context.object.data)
            self.tree = BVHTree.FromBMesh(self.bmesh)
            self.refresh_mesh = False

        # Potentially expensive, test if there is a selected mesh element
        if event.type == 'MOUSEMOVE':
            sprytile_data.has_selection = False
            for v in self.bmesh.verts:
                if v.select:
                    sprytile_data.has_selection = True
                    break

        # Clear preview data if not drawing preview
        if not draw_preview and SprytileModalTool.preview_verts is not None:
            SprytileModalTool.preview_verts = None
            SprytileModalTool.preview_uvs = None

        context.area.tag_redraw()

        region = context.region
        coord = Vector((event.mouse_region_x, event.mouse_region_y))
        # Pass through if outside the region
        if coord.x < 0 or coord.y < 0 or coord.x > region.width or coord.y > region.height:
            # Unless exit events, then exit
            if event.type in {'RIGHTMOUSE', 'ESC'}:
                self.exit_modal(context)
                return {'CANCELLED'}
            return {'PASS_THROUGH'}

        key_return = self.handle_keys(context, event)
        if key_return is not None:
            return key_return

        mouse_return = self.handle_mouse(context, event, draw_preview)
        if mouse_return is not None:
            return mouse_return

        return {'PASS_THROUGH'}

    def handle_mouse(self, context, event, draw_preview):
        """"""
        if 'MOUSE' not in event.type:
            return None

        gui_use_mouse = context.scene.sprytile_ui.use_mouse
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation, if gui is not using the mouse
            if not gui_use_mouse:
                if event.type != 'MIDDLEMOUSE' and context.scene.sprytile_data.is_snapping:
                    direction = -1 if event.type == 'WHEELUPMOUSE' else 1
                    self.cursor_move_layer(context, direction)
                    self.execute_tool(context, event, True)
                    return {'RUNNING_MODAL'}
                return {'PASS_THROUGH'}
            else:
                return {'RUNNING_MODAL'}
        # no_undo flag is up, process no other mouse events until it is cleared
        if self.no_undo:
            print("No undo flag is on", event.type, event.value)
            clear_types = {'LEFTMOUSE', 'RIGHTMOUSE'}
            if event.type in clear_types and event.value == 'RELEASE':
                print("Clearing no undo")
                self.refresh_mesh = True
                self.no_undo = False
            return {'PASS_THROUGH'} if self.no_undo else {'RUNNING_MODAL'}
        elif event.type == 'LEFTMOUSE':
            self.left_down = event.value == 'PRESS' and event.alt is False
            if self.left_down:
                self.tree = BVHTree.FromBMesh(bmesh.from_edit_mesh(context.object.data))
                self.execute_tool(context, event)
            elif event.alt is True and event.value == 'PRESS':
                self.find_face_tile(context, event)
            else:  # Mouse up, send undo
                bpy.ops.ed.undo_push()
            return {'RUNNING_MODAL'}
        elif event.type == 'MOUSEMOVE':
            if self.left_down:
                self.execute_tool(context, event)
                return {'RUNNING_MODAL'}
            elif draw_preview and not self.no_undo and event.type not in self.is_keyboard_list:
                self.execute_tool(context, event, True)
            if context.scene.sprytile_data.is_snapping:
                self.cursor_snap(context, event)
        elif event.type == 'RIGHTMOUSE':
            region = context.region
            in_region = 0 <= event.mouse_region_x <= region.width and 0 <= event.mouse_region_y <= region.height
            if in_region and not gui_use_mouse:
                return {'PASS_THROUGH'}
        return None

    def handle_keys(self, context, event):
        """Process keyboard presses"""
        if event.type not in self.is_keyboard_list:
            return None

        def keymap_is_evt(kmi, evt):
            is_mapped_key = kmi.type == event.type and \
                            kmi.value in {event.value, 'ANY'} and \
                            kmi.ctrl is event.ctrl and \
                            kmi.alt is event.alt and \
                            kmi.shift is event.shift
            return is_mapped_key

        # Process intercepts for special keymaps
        for key_intercept in self.intercept_keys:
            key = key_intercept[0]
            arg = key_intercept[1]
            if not keymap_is_evt(key, event):
                continue
            # print("Special key is", arg)
            if arg == 'move_sel':
                bpy.ops.sprytile.translate_grid('INVOKE_REGION_WIN')
                SprytileModalTool.preview_uvs = None
                SprytileModalTool.preview_verts = None
                print("No undo on")
                self.no_undo = True
                return {'RUNNING_MODAL'}
            if arg == 'sel_mesh':
                return {'PASS_THROUGH'}

        sprytile_data = context.scene.sprytile_data
        # Hack to use modal keymap
        used_key = False
        build_preview = False
        for keymap, kmi_list in self.keymaps.items():
            if not keymap.is_modal:
                continue
            for kmi_idx, keymap_item in enumerate(kmi_list):
                if keymap_is_evt(keymap_item, event):
                    modal_evt = self.modal_values[kmi_idx]
                    # print(event.type, modal_evt)
                    if modal_evt == 'Cancel':
                        context.scene.sprytile_data.is_running = False
                    elif modal_evt == 'Cursor Snap':
                        last_snap = context.scene.sprytile_data.is_snapping
                        new_snap = event.value == 'PRESS'
                        sprytile_data.is_snapping = new_snap
                        # Ask UI to redraw snapping changed
                        context.scene.sprytile_ui.is_dirty = last_snap != new_snap
                    elif modal_evt == 'Cursor Focus':
                        bpy.ops.view3d.view_center_cursor('INVOKE_DEFAULT')
                    elif modal_evt == 'Rotate Left':
                        bpy.ops.sprytile.rotate_left()
                        build_preview = True
                    elif modal_evt == 'Rotate Right':
                        bpy.ops.sprytile.rotate_right()
                        build_preview = True
                    elif modal_evt == 'Flip X':
                        sprytile_data.uv_flip_x = not sprytile_data.uv_flip_x
                        build_preview = True
                    elif modal_evt == 'Flip Y':
                        sprytile_data.uv_flip_y = not sprytile_data.uv_flip_y
                        build_preview = True
                    used_key = True
        # Key event used by fake modal map, return none
        if used_key:
            if build_preview:
                self.execute_tool(context, event, True)
            return {'RUNNING_MODAL'}
        if event.shift and context.scene.sprytile_data.is_snapping:
            self.cursor_snap(context, event)
            return {'RUNNING_MODAL'}
        # Pass through every key event we don't handle ourselves
        return {'PASS_THROUGH'}

    def execute(self, context):
        return self.invoke(context, None)

    def setup_observer(self, observer):
        self.rx_observer = observer

    def invoke(self, context, event):
        if context.scene.sprytile_data.is_running:
            return {'CANCELLED'}
        if context.space_data.type == 'VIEW_3D':
            obj = context.object
            if obj.hide or obj.type != 'MESH':
                self.report({'WARNING'}, "Active object must be a visible mesh")
                return {'CANCELLED'}
            if len(context.scene.sprytile_mats) < 1:
                bpy.ops.sprytile.validate_grids()
            if len(context.scene.sprytile_mats) < 1:
                self.report({'WARNING'}, "No valid materials")
                return {'CANCELLED'}

            use_default_grid_id = obj.sprytile_gridid == -1
            if sprytile_utils.get_grid(context, obj.sprytile_gridid) is None:
                use_default_grid_id = True

            if use_default_grid_id:
                obj.sprytile_gridid = context.scene.sprytile_mats[0].grids[0].id

            if context.space_data.viewport_shade != 'MATERIAL':
                context.space_data.viewport_shade = 'MATERIAL'

            self.virtual_cursor = deque([], 3)
            self.no_undo = False
            self.left_down = False
            self.bmesh = bmesh.from_edit_mesh(context.object.data)
            self.tree = BVHTree.FromBMesh(self.bmesh)
            self.refresh_mesh = False

            self.rx_observer = None

            observable_source = Observable.create(self.setup_observer)
            self.rx_source = observable_source.publish().auto_connect(1)

            self.tools = {
                "build": ToolBuild(self, self.rx_source),
                "paint": ToolPaint(self, self.rx_source)
            }

            # Set up timer callback
            win_mgr = context.window_manager
            self.view_axis_timer = win_mgr.event_timer_add(0.1, context.window)

            self.setup_user_keys(context)
            win_mgr.modal_handler_add(self)

            sprytile_data = context.scene.sprytile_data
            sprytile_data.is_running = True
            sprytile_data.is_snapping = False

            context.scene.sprytile_ui.is_dirty = True
            bpy.ops.sprytile.gui_win('INVOKE_REGION_WIN')
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def setup_user_keys(self, context):
        """Find the keymaps to pass through to Blender"""
        self.is_keyboard_list = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q',
                                 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
                                 'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE',
                                 'LEFT_CTRL', 'LEFT_ALT', 'LEFT_SHIFT', 'RIGHT_ALT',
                                 'RIGHT_CTRL', 'RIGHT_SHIFT', 'OSKEY', 'GRLESS', 'ESC', 'TAB', 'RET', 'SPACE',
                                 'LINE_FEED', 'BACK_SPACE', 'DEL', 'SEMI_COLON', 'PERIOD', 'COMMA', 'QUOTE',
                                 'ACCENT_GRAVE', 'MINUS', 'SLASH', 'BACK_SLASH', 'EQUAL', 'LEFT_BRACKET',
                                 'RIGHT_BRACKET', 'LEFT_ARROW', 'DOWN_ARROW', 'RIGHT_ARROW', 'UP_ARROW',
                                 'NUMPAD_2', 'NUMPAD_4', 'NUMPAD_6', 'NUMPAD_8', 'NUMPAD_1', 'NUMPAD_3', 'NUMPAD_5',
                                 'NUMPAD_7', 'NUMPAD_9', 'NUMPAD_PERIOD', 'NUMPAD_SLASH', 'NUMPAD_ASTERIX', 'NUMPAD_0',
                                 'NUMPAD_MINUS', 'NUMPAD_ENTER', 'NUMPAD_PLUS',
                                 'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'F13',
                                 'F14', 'F15', 'F16', 'F17', 'F18', 'F19', 'PAUSE', 'INSERT', 'HOME', 'PAGE_UP',
                                 'PAGE_DOWN', 'END', 'MEDIA_PLAY', 'MEDIA_STOP', 'MEDIA_FIRST', 'MEDIA_LAST']

        self.intercept_keys = []

        user_keymaps = context.window_manager.keyconfigs.user.keymaps

        def get_keymap_entry(keymap_name, command):
            keymap = user_keymaps[keymap_name]
            if keymap is None:
                return False, None
            key_list = keymap.keymap_items
            cmd_idx = key_list.find(command)
            if cmd_idx < 0:
                return True, None
            return True, key_list[cmd_idx]

        # These keymaps intercept existing shortcuts and repurpose them
        keymap_intercept = {
            '3D View': [
                ('view3d.select_circle', 'sel_mesh'),
                ('transform.translate', 'move_sel')
            ]
        }
        for keymap_id in keymap_intercept:
            cmd_list = keymap_intercept[keymap_id]
            for cmd_data in cmd_list:
                cmd = cmd_data[0]
                arg = cmd_data[1]
                has_map, cmd_entry = get_keymap_entry(keymap_id, cmd)
                if not has_map:
                    break
                if cmd_entry is None:
                    continue
                self.intercept_keys.append((cmd_entry, arg))

    def exit_modal(self, context):
        context.scene.sprytile_data.is_running = False
        if self.rx_observer is not None:
            self.rx_observer.on_completed()
        self.tree = None
        if hasattr(self, "view_axis_timer"):
            context.window_manager.event_timer_remove(self.view_axis_timer)
        if context.object.mode == 'EDIT':
            bmesh.update_edit_mesh(context.object.data, True, True)


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()
