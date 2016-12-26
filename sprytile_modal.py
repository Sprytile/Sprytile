import bpy
import bmesh
import math
from bpy_extras import view3d_utils
from collections import deque
from mathutils import Vector, Matrix, Quaternion
from mathutils.geometry import intersect_line_plane, distance_point_to_plane
from mathutils.bvhtree import BVHTree
from . import sprytile_utils


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


def get_grid_pos(position, grid_center, right_vector, up_vector, world_pixels, grid_x, grid_y):
    """Snaps a world position to the given grid settings"""
    position_vector = position - grid_center
    pos_vector_normalized = position.normalized()

    if right_vector.dot(pos_vector_normalized) < 0:
        right_vector *= -1
    if up_vector.dot(pos_vector_normalized) < 0:
        up_vector *= -1

    x_magnitude = position_vector.dot(right_vector)
    y_magnitude = position_vector.dot(up_vector)

    x_unit = grid_x / world_pixels
    y_unit = grid_y / world_pixels

    x_snap = math.floor(x_magnitude / x_unit)
    y_snap = math.floor(y_magnitude / y_unit)

    right_vector *= x_unit
    up_vector *= y_unit

    grid_pos = grid_center + (right_vector * x_snap) + (up_vector * y_snap)

    return grid_pos, right_vector, up_vector


def raycast_grid(scene, context, up_vector, right_vector, plane_normal, ray_origin, ray_vector):
    """Raycast to a normal plane on the scene cursor, and return the grid snapped position"""

    plane_pos = intersect_line_plane(ray_origin, ray_origin + ray_vector, scene.cursor_location, plane_normal)
    # Didn't hit the plane exit
    if plane_pos is None:
        return None, None, None, None

    world_pixels = scene.sprytile_data.world_pixels
    target_grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
    grid_x = target_grid.grid[0]
    grid_y = target_grid.grid[1]

    grid_position, x_vector, y_vector = get_grid_pos(plane_pos, scene.cursor_location,
                                                     right_vector.copy(), up_vector.copy(),
                                                     world_pixels, grid_x, grid_y)
    return grid_position, x_vector, y_vector, plane_pos


def get_current_grid_vectors(scene):
    """Returns the current grid X/Y/Z vectors from scene data
    :rtype: up_vector, right_vector, normal_vector
    """
    data_normal = scene.sprytile_data.paint_normal_vector
    data_up_vector = scene.sprytile_data.paint_up_vector

    normal_vector = Vector((data_normal[0], data_normal[1], data_normal[2]))
    up_vector = Vector((data_up_vector[0], data_up_vector[1], data_up_vector[2]))

    normal_vector.normalize()
    up_vector.normalize()
    right_vector = up_vector.cross(normal_vector)

    rotation = Quaternion(-normal_vector, scene.sprytile_data.mesh_rotate)
    up_vector = rotation * up_vector
    right_vector = rotation * right_vector

    return up_vector, right_vector, normal_vector


def uv_map_face(context, up_vector, right_vector, tile_xy, face_index, mesh):
    """UV map the given face"""
    scene = context.scene
    obj = context.object
    data = scene.sprytile_data

    grid_id = obj.sprytile_gridid
    target_grid = sprytile_utils.get_grid(context, grid_id)
    world_units = data.world_pixels
    world_convert = Vector((target_grid.grid[0] / world_units,
                            target_grid.grid[1] / world_units))
    uv_layer = mesh.loops.layers.uv.verify()
    mesh.faces.layers.tex.verify()

    if face_index >= len(mesh.faces):
        return None, None

    target_img = sprytile_utils.get_grid_texture(obj, target_grid)
    if target_img is None:
        return None, None

    pixel_uv_x = 1.0 / target_img.size[0]
    pixel_uv_y = 1.0 / target_img.size[1]
    uv_unit_x = pixel_uv_x * target_grid.grid[0]
    uv_unit_y = pixel_uv_y * target_grid.grid[1]

    # Build the translation matrix
    offset_matrix = Matrix.Translation((target_grid.offset[0] * pixel_uv_x, target_grid.offset[1] * pixel_uv_y, 0))
    rotate_matrix = Matrix.Rotation(target_grid.rotate, 4, 'Z')
    grid_matrix = offset_matrix * rotate_matrix
    uv_matrix = Matrix.Translation((uv_unit_x * tile_xy[0], uv_unit_y * tile_xy[1], 0))
    uv_matrix = grid_matrix * uv_matrix

    flip_x = -1 if data.uv_flip_x else 1
    flip_y = -1 if data.uv_flip_y else 1
    flip_matrix = Matrix.Scale(flip_x, 4, right_vector) * Matrix.Scale(flip_y, 4, up_vector)

    uv_min = Vector((float('inf'), float('inf')))
    uv_max = Vector((float('-inf'), float('-inf')))

    face = mesh.faces[face_index]
    vert_origin = face .calc_center_bounds()
    for loop in face.loops:
        vert = loop.vert
        # Center around 0, 0
        vert_pos = vert.co - vert_origin
        # Apply flip scaling
        vert_pos = flip_matrix * vert_pos
        # Get x/y values by using the right/up vectors
        vert_xy = (right_vector.dot(vert_pos), up_vector.dot(vert_pos), 0)
        vert_xy = Vector(vert_xy)
        # Convert to -0.5 to 0.5 space
        vert_xy.x /= world_convert.x
        vert_xy.y /= world_convert.y
        # Offset by half, to move it coordinates back into 0-1 range
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
        # Apply the UV
        loop[uv_layer].uv = vert_xy.xy

    # In paint mode, do alignment and stretching steps
    if data.paint_mode == 'PAINT':
        uv_map_paint_modify(data, face, uv_layer, uv_matrix,
                            uv_unit_x, uv_unit_y, uv_min, uv_max)

    # One final loop to snap the UVs to the pixel grid
    for loop in face.loops:
        uv = loop[uv_layer].uv
        uv_pixel_x = int(round(uv.x / pixel_uv_x))
        uv_pixel_y = int(round(uv.y / pixel_uv_y))
        uv.x = uv_pixel_x * pixel_uv_x
        uv.y = uv_pixel_y * pixel_uv_y
        loop[uv_layer].uv = uv

    # Apply the correct material to the face
    mat_idx = context.object.material_slots.find(target_grid.mat_id)
    if mat_idx > -1:
        face.material_index = mat_idx

    # Save the grid and tile ID to the face
    grid_layer_id = mesh.faces.layers.int.get('grid_index')
    grid_layer_tileid = mesh.faces.layers.int.get('grid_tile_id')

    if grid_layer_id is None:
        grid_layer_id = mesh.faces.layers.int.new('grid_index')
    if grid_layer_tileid is None:
        grid_layer_tileid = mesh.faces.layers.int.new('grid_tile_id')

    face = mesh.faces[face_index]
    row_size = math.ceil(target_img.size[0] / target_grid.grid[0])
    tile_id = (tile_xy[1] * row_size) + tile_xy[0]

    face[grid_layer_id] = grid_id
    face[grid_layer_tileid] = tile_id

    bmesh.update_edit_mesh(obj.data)
    mesh.faces.index_update()
    return face.index, target_grid


def uv_map_paint_modify(data, face, uv_layer, uv_matrix, uv_unit_x, uv_unit_y, uv_min, uv_max):
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
        # Loop through and face loops and apply offset to UV
        for loop in face.loops:
            loop[uv_layer].uv += uv_offset

    # Execute tile stretch
    threshold_ratio = 0.45
    if data.paint_stretch_x:
        # Scale the tile to fit x
        tile_width = tile_max.x - tile_min.x
        face_width = uv_max.x - uv_min.x
        threshold = tile_width * threshold_ratio
        for loop in face.loops:
            uv = loop[uv_layer].uv
            uv.x -= tile_min.x
            uv = Matrix.Scale(tile_width / face_width, 2, Vector((1, 0))) * uv
            uv.x += tile_min.x
            if abs(uv.x - tile_min.x) < threshold:
                uv.x = tile_min.x
            if abs(uv.x - tile_max.x) < threshold:
                uv.x = tile_max.x
            loop[uv_layer].uv = uv.xy
    if data.paint_stretch_y:
        tile_height = tile_max.y - tile_min.y
        face_height = uv_max.y - uv_min.y
        print(tile_height, face_height)
        threshold = tile_height * threshold_ratio
        for loop in face.loops:
            uv = loop[uv_layer].uv
            uv.y -= tile_min.y
            uv = Matrix.Scale(tile_height / face_height, 2, Vector((0, 1))) * uv
            uv.y += tile_min.y
            if abs(uv.y - tile_min.y) < threshold:
                uv.y = tile_min.y
            if abs(uv.y - tile_max.y) < threshold:
                uv.y = tile_max.y
            loop[uv_layer].uv = uv


class SprytileModalTool(bpy.types.Operator):
    """Tile based mesh creation/UV layout tool"""
    bl_idname = "sprytile.modal_tool"
    bl_label = "Sprytile Paint"
    bl_options = {'REGISTER'}

    keymaps = {}

    def find_view_axis(self, context):
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
        # print("view up", view_up_vector)
        # print("Original forward", rv3d.view_rotation.inverted() * view_vector)

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

        if new_mode != scene.sprytile_data.normal_mode:
            self.virtual_cursor.clear()
        scene.sprytile_data.normal_mode = new_mode

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

        grid_id_layer = self.bmesh.faces.layers.int.get('grid_index')
        tile_id_layer = self.bmesh.faces.layers.int.get('grid_tile_id')

        if grid_id_layer is None or tile_id_layer is None:
            return

        face = self.bmesh.faces[face_index]
        grid_id = face[grid_id_layer]
        tile_packed_id = face[tile_id_layer]

        tilegrid = sprytile_utils.get_grid(context, grid_id)
        if tilegrid is None:
            return

        texture = sprytile_utils.get_grid_texture(context.object, tilegrid)
        if texture is None:
            return

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

        last_pos = self.virtual_cursor[cursor_len-1]
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

    def raycast_object(self, obj, ray_origin, ray_direction):
        matrix = obj.matrix_world.copy()
        # get the ray relative to the object
        matrix_inv = matrix.inverted()
        ray_origin_obj = matrix_inv * ray_origin
        ray_target_obj = matrix_inv * (ray_origin + ray_direction)
        ray_direction_obj = ray_target_obj - ray_origin_obj

        location, normal, face_index, distance = self.tree.ray_cast(ray_origin_obj, ray_direction_obj)
        if face_index is None:
            return None, None, None, None
        # Translate location back to world space
        location = matrix * location
        return location, normal, face_index, distance

    def execute_tool(self, context, event):
        """Run the paint tool"""
        # Don't do anything if nothing to raycast on
        # or the GL GUI is using the mouse
        if self.tree is None or context.scene.sprytile_ui.use_mouse is True:
            return

        # print("Execute tool")
        # get the context arguments
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y

        # get the ray from the viewport and mouse
        ray_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

        # if paint mode, ray cast against object
        paint_mode = scene.sprytile_data.paint_mode
        if paint_mode == 'PAINT':
            self.execute_paint(context, ray_origin, ray_vector)
        # if build mode, ray cast on plane and build face
        elif paint_mode == 'MAKE_FACE':
            self.execute_build(context, scene, ray_origin, ray_vector)
        # set normal mode...
        else:
            self.execute_set_normal(context, rv3d, ray_origin, ray_vector)

    def execute_paint(self, context, ray_origin, ray_vector):
        up_vector, right_vector, plane_normal = get_current_grid_vectors(context.scene)
        hit_loc, normal, face_index, distance = self.raycast_object(context.object, ray_origin, ray_vector)
        if face_index is None:
            return

        self.add_virtual_cursor(hit_loc)
        # Change the uv of the given face
        grid_id = context.object.sprytile_gridid
        grid = sprytile_utils.get_grid(context, grid_id)
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])

        face_up = self.get_face_up_vector(context, face_index)
        if face_up is not None and face_up.dot(up_vector) < 0.95:
            data = context.scene.sprytile_data
            face_up = Matrix.Rotation(data.mesh_rotate, 4, normal) * face_up
            up_vector = face_up
            right_vector = face_up.cross(normal)

        face_index, grid = uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.bmesh)

    def execute_build(self, context, scene, ray_origin, ray_vector):
        grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])

        up_vector, right_vector, plane_normal = get_current_grid_vectors(scene)
        hit_loc, hit_normal, face_index, hit_dist = self.raycast_object(context.object, ray_origin, ray_vector)

        # If raycast on the mesh, check that the hit face isn't facing
        # the same way as the plane_normal and not coplanar to target plane
        if face_index is not None:
            check_dot = plane_normal.dot(hit_normal)
            check_dot -= 1
            check_coplanar = distance_point_to_plane(hit_loc, scene.cursor_location, plane_normal)

            # print("Hit face")
            # print("Dot:", check_dot, " Coplanar", check_coplanar)

            check_coplanar = abs(check_coplanar) < 0.05
            check_dot = abs(check_dot) < 0.05
            if check_dot and check_coplanar:
                self.add_virtual_cursor(hit_loc)
                # Change UV of this face instead
                uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.bmesh)
                if scene.sprytile_data.cursor_flow:
                    self.flow_cursor(context, face_index, hit_loc)
                return

        face_position, x_vector, y_vector, plane_cursor = raycast_grid(
            scene, context,
            up_vector, right_vector, plane_normal,
            ray_origin, ray_vector)
        if face_position is None:
            return

        # store plane_cursor, for deciding where to move actual cursor if auto cursor mode is on
        self.add_virtual_cursor(plane_cursor)
        # Build face and UV map it
        face_index = self.build_face(context, face_position, x_vector, y_vector, up_vector, right_vector)
        uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.bmesh)
        if scene.sprytile_data.cursor_flow:
            self.flow_cursor(context, face_index, plane_cursor)

    def build_face(self, context, position, x_vector, y_vector, up_vector, right_vector):
        """Build a face at the given position"""
        x_dot = right_vector.dot(x_vector.normalized())
        y_dot = up_vector.dot(y_vector.normalized())
        x_positive = x_dot > 0
        y_positive = y_dot > 0

        # These are in world positions
        vtx1 = self.bmesh.verts.new(position)
        vtx2 = self.bmesh.verts.new(position + y_vector)
        vtx3 = self.bmesh.verts.new(position + x_vector + y_vector)
        vtx4 = self.bmesh.verts.new(position + x_vector)

        # Quadrant II, IV
        face_order = (vtx1, vtx2, vtx3, vtx4)
        # Quadrant I, III
        if x_positive == y_positive:
            face_order = (vtx1, vtx4, vtx3, vtx2)

        # Convert world space position to object space
        world_inv = context.object.matrix_world.copy().inverted()
        for vtx in face_order:
            vtx.co = world_inv * vtx.co

        face = self.bmesh.faces.new(face_order)
        face.normal_update()

        self.bmesh.faces.index_update()
        self.bmesh.faces.ensure_lookup_table()

        bmesh.update_edit_mesh(context.object.data, True, True)

        # Update the collision BVHTree with new data
        self.tree = BVHTree.FromBMesh(self.bmesh)
        return face.index

    def get_face_up_vector(self, context, face_index):
        """Find the edge of the given face that most closely matches view up vector"""
        # Get the view up vector. The default scene view camera is pointed
        # downward, with up on Y axis. Apply view rotation to get current up
        rv3d = context.region_data
        view_up_vector = rv3d.view_rotation * Vector((0.0, 1.0, 0.0))

        # Find the edge of the hit face that most closely matches the view up vector
        face = self.bmesh.faces[face_index]
        closest_idx = -1
        closest_dot = 2.0
        edge_vectors = []
        idx = -1
        for edge in face.edges:
            idx += 1
            # if edge.is_boundary is False:
            #     continue
            # Move vertices to world space
            vtx1 = context.object.matrix_world * edge.verts[0].co
            vtx2 = context.object.matrix_world * edge.verts[1].co
            edge_vec = vtx1 - vtx2
            edge_vec.normalize()
            edge_vectors.append(edge_vec)
            edge_dot = 1 - abs(edge_vec.dot(view_up_vector))
            if edge_dot < closest_dot:
                closest_dot = edge_dot
                closest_idx = idx

        if closest_idx == -1:
            return None

        chosen_up = edge_vectors[closest_idx]
        if chosen_up.dot(view_up_vector) < 0:
            chosen_up *= -1

        return chosen_up

    def execute_set_normal(self, context, rv3d, ray_origin, ray_vector):
        hit_loc, hit_normal, face_index, distance = self.raycast_object(context.object, ray_origin, ray_vector)
        if hit_loc is None:
            return

        face_up_vector = self.get_face_up_vector(context, face_index)
        if face_up_vector is None:
            return

        sprytile_data = context.scene.sprytile_data
        sprytile_data.paint_normal_vector = hit_normal
        sprytile_data.paint_up_vector = face_up_vector
        sprytile_data.lock_normal = True
        sprytile_data.paint_mode = 'MAKE_FACE'

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

        # Snap cursor, depending on setting
        if scene.sprytile_data.cursor_snap == 'GRID':
            location = intersect_line_plane(ray_origin, ray_origin + ray_vector, scene.cursor_location, plane_normal)
            if location is None:
                return
            world_pixels = scene.sprytile_data.world_pixels
            target_grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
            grid_x = target_grid.grid[0]
            grid_y = target_grid.grid[1]

            grid_position, x_vector, y_vector = get_grid_pos(location, scene.cursor_location,
                                                             right_vector.copy(), up_vector.copy(),
                                                             world_pixels, grid_x, grid_y)
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
        if event.type == 'TIMER':
            self.find_view_axis(context)
            return {'PASS_THROUGH'}

        if context.object.mode != 'EDIT':
            self.exit_modal(context)
            return {'CANCELLED'}

        if self.refresh_mesh:
            self.bmesh = bmesh.from_edit_mesh(context.object.data)
            self.tree = BVHTree.FromBMesh(self.bmesh)
            self.refresh_mesh = False

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

        mouse_return = self.handle_mouse(context, event)
        if mouse_return is not None:
            return mouse_return

        return {'RUNNING_MODAL'}

    def handle_mouse(self, context, event):
        """"""
        if 'MOUSE' not in event.type:
            return None

        gui_use_mouse = context.scene.sprytile_ui.use_mouse
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and not gui_use_mouse:
            # allow navigation, if gui is not using the mouse
            return {'PASS_THROUGH'}
        # no_undo flag is up, process no other mouse events until it is cleared
        if self.no_undo:
            if event.type in {'LEFTMOUSE', 'RIGHTMOUSE'} and event.value == 'RELEASE':
                self.no_undo = False
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
            if context.scene.sprytile_data.is_snapping:
                self.cursor_snap(context, event)
        elif event.type == 'RIGHTMOUSE':
            region = context.region
            in_region = 0 <= event.mouse_region_x <= region.width and 0 <= event.mouse_region_y <= region.height
            if in_region and not gui_use_mouse:
                return {'PASS_THROUGH'}
            print("Right mouse did not pass")
        return None

    def handle_keys(self, context, event):
        """Process keyboard presses"""
        # Check if the event matches any of the keymap
        # entries we're interested in. If it is, pass the event through
        for keymap_item in self.user_keys:
            is_mapped_key = keymap_item.type == event.type and\
                            keymap_item.value == event.value and\
                            keymap_item.ctrl is event.ctrl and\
                            keymap_item.alt is event.alt and\
                            keymap_item.shift is event.shift
            if is_mapped_key:
                # If intercepted undo/redo, will want to refresh mesh
                self.refresh_mesh = True
                return {'PASS_THROUGH'}

        # Now process intercepts for special keymaps
        for key_intercept in self.intercept_keys:
            key = key_intercept[0]
            arg = key_intercept[1]
            is_mapped_key = key.type == event.type and\
                key.value == event.value and\
                key.ctrl is event.ctrl and\
                key.alt is event.alt and\
                key.shift is event.shift

            if not is_mapped_key:
                continue
            # print("Special key is", arg)
            if arg == 'move_sel':
                bpy.ops.sprytile.translate_grid('INVOKE_REGION_WIN')
                self.no_undo = True
                return None
            if arg == 'sel_mesh':
                return {'PASS_THROUGH'}

        sprytile_data = context.scene.sprytile_data
        if event.type == 'ESC':
            self.exit_modal(context)
            return {'CANCELLED'}
        if event.type == 'X' and event.value == 'PRESS':
            bpy.ops.mesh.delete()
            self.refresh_mesh = True
        if event.type == 'S':
            last_snap = context.scene.sprytile_data.is_snapping
            new_snap = event.value == 'PRESS'
            sprytile_data.is_snapping = new_snap
            # Ask UI to redraw snapping changed
            context.scene.sprytile_ui.is_dirty = last_snap != new_snap
        if event.type == 'Q' and event.value == 'PRESS':
            bpy.ops.sprytile.rotate_left()
        if event.type == 'D' and event.value == 'PRESS':
            bpy.ops.sprytile.rotate_right()
        elif event.type == 'W' and event.value == 'PRESS':
            bpy.ops.view3d.view_center_cursor('INVOKE_DEFAULT')

        return None

    def execute(self, context):
        return self.invoke(context, None)

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

            if obj.sprytile_gridid == -1:
                obj.sprytile_gridid = context.scene.sprytile_mats[0].grids[0].id

            if context.space_data.viewport_shade != 'MATERIAL':
                context.space_data.viewport_shade = 'MATERIAL'

            self.virtual_cursor = deque([], 3)
            self.no_undo = False
            self.left_down = False
            self.bmesh = bmesh.from_edit_mesh(context.object.data)
            self.tree = BVHTree.FromBMesh(self.bmesh)
            self.refresh_mesh = False

            # Set up timer callback
            win_mgr = context.window_manager
            self.view_axis_timer = win_mgr.event_timer_add(0.1, context.window)

            self.setup_user_keys(context)
            win_mgr.modal_handler_add(self)

            sprytile_data = context.scene.sprytile_data
            sprytile_data.is_running = True
            sprytile_data.is_snapping = False

            context.scene.sprytile_ui.is_dirty = True

            bpy.ops.sprytile.gui_win('INVOKE_DEFAULT')
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def setup_user_keys(self, context):
        """Find the keymaps to pass through to Blender"""
        self.user_keys = []
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

        # These keymaps are passed through blender
        keymap_pass_through = {
            'Screen': {
                "ids": ['ed.undo', 'ed.redo']
            },
            'Mesh': {
                "ids": ['mesh.select_all', 'mesh.hide', 'mesh.reveal'],
                "prop": ['VIEW3D_MT_edit_mesh_select_mode']
            },
            '3D View': {
                "ids": ['view3d.select_circle', 'transform.rotate'],
                "prop": ['VIEW3D_MT_snap']
            },
            'Object Non-modal': {
                "ids": ['object.mode_set']
            }
        }
        for keymap_id in keymap_pass_through:
            keymap = user_keymaps[keymap_id]
            if keymap is None:
                continue
            cmd_list = keymap_pass_through[keymap_id]
            for kmi in keymap.keymap_items.values():
                if "ids" in cmd_list:
                    if kmi.idname in cmd_list["ids"]:
                        self.user_keys.append(kmi)
                        continue
                if "prop" not in cmd_list:
                    continue
                if kmi.properties is None:
                    continue
                if 'name' not in kmi.properties:
                    continue
                if kmi.properties.name in cmd_list["prop"]:
                    self.user_keys.append(kmi)

        # These keymaps intercept existing shortcuts
        # and repurpose them
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
        self.tree = None
        context.window_manager.event_timer_remove(self.view_axis_timer)
        if context.object.mode == 'EDIT':
            bmesh.update_edit_mesh(context.object.data, True, True)


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()
