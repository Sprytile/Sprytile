import bpy
import bgl
import blf
import bmesh
import math

import sys
from bpy_extras import view3d_utils
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty
from bmesh.types import BMVert, BMEdge, BMFace
from mathutils import Matrix, Vector, Quaternion
from mathutils.geometry import intersect_line_plane, distance_point_to_plane
from bpy.path import abspath
from datetime import datetime
from os import path
import sprytile_modal
import addon_updater_ops


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


def grid_is_single_pixel(grid):
    is_pixel = grid.grid[0] == 1 and grid.grid[1] == 1 and grid_no_spacing(grid)
    return is_pixel


def grid_no_spacing(grid):
    no_spacing = grid.padding[0] == 0 and grid.padding[0] == 0 and \
                 grid.margin[0] == 0 and grid.margin[1] == 0 and \
                 grid.margin[2] == 0 and grid.margin[3] == 0
    return no_spacing


def get_grid_ids(context, grid, select_coords):
    """Convert an array of selection X/Y coordinates to grid ids"""
    target_img = get_grid_texture(context.object, grid)
    if target_img is None:
        return None

    row_size = math.ceil(target_img.size[0] / grid.grid[0])
    grid_ids = []
    for x, y in select_coords:
        tile_id = (y * row_size) + x
        grid_ids.append(tile_id)
    return grid_ids


def get_grid_selection_coords(grid):
    tile_sel = grid.tile_selection
    selection_array = []
    for y in range(tile_sel[3]):
        for x in range(tile_sel[2]):
            coord = (tile_sel[0] + x, tile_sel[1] + y)
            selection_array.append(coord)
    return selection_array


def get_grid_selection_ids(context, grid):
    coords = get_grid_selection_coords(grid)
    sel_size = (grid.tile_selection[2], grid.tile_selection[3])
    grid_ids = get_grid_ids(context, grid, coords)
    return coords, sel_size, grid_ids


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


def get_grid_pos(position, grid_center, right_vector, up_vector, world_pixels, grid_x, grid_y, as_coord=False):
    """Snaps a world position to the given grid settings"""
    position_vector = position - grid_center
    pos_vector_normalized = position.normalized()

    if not as_coord:
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

    if as_coord:
        return Vector((x_snap, y_snap)), right_vector, up_vector

    grid_pos = grid_center + (right_vector * x_snap) + (up_vector * y_snap)

    return grid_pos, right_vector, up_vector


def get_grid_right_up(right_vector, up_vector, world_pixels, grid_x, grid_y):
    x_unit = grid_x / world_pixels
    y_unit = grid_y / world_pixels
    right_vector *= x_unit
    up_vector *= y_unit
    return right_vector, up_vector


def get_workplane_area(width, height):
    offset_ids, offset_grid, coord_min, coord_max = get_grid_area(width, height)
    return [coord_min[0] - 1, coord_min[1] - 1], coord_max


def get_grid_area(width, height, flip_x=False, flip_y=False):
    """
    Get the grid and tile ID offset, for a given dimension
    :param width:
    :param height:
    :param flip_x:
    :param flip_y:
    :return: offset_tile_ids, offset_grid
    """
    offset_x = int(width/2)
    offset_y = int(height/2)
    if width % 2 == 0:
        offset_x -= 1
    if height % 2 == 0:
        offset_y -= 1

    offset_x *= -1
    offset_y *= -1

    offset_tile_ids = []
    offset_grid = []
    coords_min = [sys.maxsize, sys.maxsize]
    coords_max = [-sys.maxsize, -sys.maxsize]
    for y in range(height):
        for x in range(width):
            # Calculate tile offset
            tile_offset = (width - 1 - x if flip_x else x,
                           height - 1 - y if flip_y else y)
            offset_tile_ids.append(tile_offset)

            # Calculate grid offset
            grid_offset = (x + offset_x, y + offset_y)

            coords_min[0] = min(grid_offset[0], coords_min[0])
            coords_min[1] = min(grid_offset[1], coords_min[1])
            coords_max[0] = max(grid_offset[0], coords_max[0])
            coords_max[1] = max(grid_offset[1], coords_max[1])

            offset_grid.append(grid_offset)
    return offset_tile_ids, offset_grid, coords_min, coords_max


def raycast_grid(scene, context, up_vector, right_vector, plane_normal, ray_origin, ray_vector, as_coord=False):
    """
    Raycast to a plane on the scene cursor, and return the grid snapped position
    :param scene:
    :param context:
    :param up_vector:
    :param right_vector:
    :param plane_normal:
    :param ray_origin:
    :param ray_vector:
    :param as_coord: If position should be returned as world position or grid coordinate
    :return: grid_position, x_vector, y_vector, plane_pos
    """

    plane_pos = intersect_line_plane(ray_origin, ray_origin + ray_vector, scene.cursor_location, plane_normal)
    # Didn't hit the plane exit
    if plane_pos is None:
        return None, None, None, None

    world_pixels = scene.sprytile_data.world_pixels
    target_grid = get_grid(context, context.object.sprytile_gridid)
    grid_x = target_grid.grid[0]
    grid_y = target_grid.grid[1]

    grid_position, x_vector, y_vector = get_grid_pos(
                                            plane_pos, scene.cursor_location,
                                            right_vector.copy(), up_vector.copy(),
                                            world_pixels, grid_x, grid_y, as_coord
                                        )
    if x_vector.normalized().dot(right_vector) < 0:
        x_vector *= -1
        grid_position -= x_vector
    if y_vector.normalized().dot(up_vector) < 0:
        y_vector *= -1
        grid_position -= y_vector
    return grid_position, x_vector, y_vector, plane_pos


def get_grid_matrix(sprytile_grid):
    """Returns the transform matrix of a sprytile grid"""
    offset_mtx = Matrix.Translation((sprytile_grid.offset[0], sprytile_grid.offset[1], 0))
    rotate_mtx = Matrix.Rotation(sprytile_grid.rotate, 4, 'Z')
    return offset_mtx * rotate_mtx


def get_grid_texture(obj, sprytile_grid):
    """
    Returns the texture applied to an object, given the sprytile_grid
    :param obj: the Blender mesh object
    :param sprytile_grid: the sprytile grid applied to the object
    :return: Texture or None
    """
    mat_idx = obj.material_slots.find(sprytile_grid.mat_id)
    if mat_idx == -1:
        return None
    material = obj.material_slots[mat_idx].material
    if material is None:
        return None
    target_img = None
    for texture_slot in material.texture_slots:
        if texture_slot is None:
            continue
        if texture_slot.texture is None:
            continue
        if texture_slot.texture.type == 'NONE':
            continue
        if texture_slot.texture.image is None:
            continue
        if texture_slot.texture.type == 'IMAGE':
            # Cannot use the texture slot image reference directly
            # Have to get it through bpy.data.images to be able to use with BGL
            target_img = bpy.data.images.get(texture_slot.texture.image.name)
            break
    return target_img


def get_selected_grid(context):
    """
    Returns the sprytile_grid currently selected
    :param context: Blender tool context
    :return: sprytile_grid or None
    """
    obj = context.object
    scene = context.scene

    mat_list = scene.sprytile_mats
    # The selected mesh object has the current sprytile_grid id
    grid_id = obj.sprytile_gridid

    return get_grid(context, grid_id)


def get_grid(context, grid_id):
    """
    Returns the sprytile_grid with the given id
    :param context: Blender tool context
    :param grid_id: grid id
    :return: sprytile_grid or None
    """
    mat_list = context.scene.sprytile_mats
    for mat_data in mat_list:
        for grid in mat_data.grids:
            if grid.id == grid_id:
                return grid
    return None


def get_highest_grid_id(context):
    highest_id = -1
    mat_list = context.scene.sprytile_mats
    for mat_data in mat_list:
        for grid in mat_data.grids:
            highest_id = max(grid.id, highest_id)
    return highest_id


def get_mat_data(context, mat_id):
    mat_list = context.scene.sprytile_mats
    for mat_data in mat_list:
        if mat_data.mat_id == mat_id:
            return mat_data
    return None


def get_paint_settings(sprytile_data):
    '''
    Returns the paint settings bitmask from a sprytile_data instance
    :param sprytile_data: sprytile_data instance
    :return: A bitmask representing the paint settings in the sprytile_data
    '''
    # Rotation and UV flip are always included
    paint_settings = 0
    # Flip x/y are toggles
    paint_settings += (1 if sprytile_data.uv_flip_x else 0) << 9
    paint_settings += (1 if sprytile_data.uv_flip_y else 0) << 8
    # Rotation is encoded as 0-3 clockwise, bit shifted by 10
    degree_rotation = round(math.degrees(sprytile_data.mesh_rotate), 0)
    if degree_rotation < 0:
        degree_rotation += 360
    rot_val = 0
    if degree_rotation <= 1:
        rot_val = 0
    elif degree_rotation <= 90:
        rot_val = 3
    elif degree_rotation <= 180:
        rot_val = 2
    elif degree_rotation <= 270:
        rot_val = 1
    paint_settings += rot_val << 10

    if sprytile_data.paint_mode == 'MAKE_FACE':
        paint_settings += 5  # Default center align
        for x in range(4, 8):  # All toggles on
            paint_settings += 1 << x
    if sprytile_data.paint_mode == 'PAINT':
        paint_settings += sprytile_data["paint_align"]
        paint_settings += (1 if sprytile_data.paint_uv_snap else 0) << 7
        paint_settings += (1 if sprytile_data.paint_edge_snap else 0) << 6
        paint_settings += (1 if sprytile_data.paint_stretch_x else 0) << 5
        paint_settings += (1 if sprytile_data.paint_stretch_y else 0) << 4
    return paint_settings


def from_paint_settings(sprytile_data, paint_settings):
    """
    Sets the paint settings of a sprytile_data using the paint settings bitmask
    :param sprytile_data: sprytile_data instance to set
    :param paint_settings: Painting settings bitmask
    :return: None
    """
    if paint_settings == 0:
        return
    align_value = paint_settings & 15  # First four bits
    rot_value = (paint_settings & 3072) >> 10  # 11th and 12th bit, shifted back
    rot_radian = 0
    if rot_value == 1:
        rot_radian = math.radians(270)
    if rot_value == 2:
        rot_radian = math.radians(180)
    if rot_value == 3:
        rot_radian = math.radians(90)

    sprytile_data["paint_align"] = align_value
    sprytile_data.mesh_rotate = rot_radian
    sprytile_data.uv_flip_x = (paint_settings & 1 << 9) > 0
    sprytile_data.uv_flip_y = (paint_settings & 1 << 8) > 0
    sprytile_data.paint_uv_snap = (paint_settings & 1 << 7) > 0
    sprytile_data.paint_edge_snap = (paint_settings & 1 << 6) > 0
    sprytile_data.paint_stretch_x = (paint_settings & 1 << 5) > 0
    sprytile_data.paint_stretch_y = (paint_settings & 1 << 4) > 0


def get_work_layer_data(sprytile_data):
    """
    Returns the work layer bitmask from the given sprytile data
    """
    # Bits 0-4 are reserved for storing layer numbers
    # Bit 5 = Face is using decal mode
    # Bit 6 = Face is using UV mode

    # When face is using UV mode, there may be multiple
    # UV layers, to find which layers it is using,
    # Mask against bits 0-4

    # This is only for 1 layer decals, figure out multi layer later
    out_data = 0
    if sprytile_data.work_layer != 'BASE':
        out_data += (1 << 0)
        if sprytile_data.work_layer_mode == 'MESH_DECAL':
            out_data += (1 << 5)
        else:
            out_data += (1 << 6)
    return out_data


def from_work_layer_data(sprytile_data, layer_data):
    pass


def label_wrap(col, text, area="VIEW_3D", region_type="TOOL_PROPS", tab_str="    ", scale_y=0.55):
    a_id = -1
    r_id = -1
    new_line = "\n"
    tab = "\t"
    tabbing = False
    n_line = False
    col.scale_y = scale_y
    areas = bpy.context.screen.areas
    for i, a in enumerate(areas):
        if a.type == area:
            a_id = i
        reg = a.regions
        for ir, r in enumerate(reg):
            if r.type == region_type:
                r_id = ir
    if a_id < 0 or r_id < 0:
        return

    p_width = areas[a_id].regions[r_id].width
    char_width = 7  # approximate width of each character
    line_length = int(p_width / char_width)
    last_space = line_length  # current position of last space character in text
    while last_space > 0:
        split_point = line_length  # where to split the text
        if split_point > len(text):
            split_point = len(text) - 1

        cr = text.find(new_line, 0, len(text))

        if (cr > 0) and (cr <= split_point):
            n_line = True
            last_space = cr  # Position of new line symbol, if found
        else:
            tabp = text.find("\t", 0, split_point)
            if tabp >= 0:
                text = text.replace(tab, "", 1)
                tabbing = True
                n_line = False
            last_space = text.rfind(" ", 0, split_point)  # Position of last space character in text

        if (last_space == -1) or len(text) <= line_length:  # No more spaces found, or its the last line of text
            last_space = len(text)
        line = text[0:last_space]
        if tabbing:
            line = tab_str + line
        col.label(line)
        if n_line:
            tabbing = False
        text = text[last_space + 1:len(text)]


class SprytileAxisUpdate(bpy.types.Operator):
    bl_idname = "sprytile.axis_update"
    bl_label = "Update Sprytile Axis"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        # Given the normal mode, find the direction of paint_normal_vector, paint_up_vector
        data = context.scene.sprytile_data
        region = context.region
        rv3d = context.region_data

        # Get the view ray from center of screen
        coord = Vector((int(region.width / 2), int(region.height / 2)))
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        # Get the up vector. The default scene view camera is pointed
        # downward, with up on Y axis. Apply view rotation to get current up
        view_up_vector = rv3d.view_rotation * Vector((0.0, 1.0, 0.0))

        view_vector = snap_vector_to_axis(view_vector, mirrored=True)
        view_up_vector = snap_vector_to_axis(view_up_vector)

        # implicit X
        paint_normal = Vector((1.0, 0.0, 0.0))
        if data.normal_mode == 'Y':
            paint_normal = Vector((0.0, 1.0, 0.0))
        elif data.normal_mode == 'Z':
            paint_normal = Vector((0.0, 0.0, 1.0))

        view_dot = paint_normal.dot(view_up_vector)
        view_dot = abs(view_dot)
        paint_up = view_up_vector
        if view_dot > 0.9:
            paint_up = view_vector

        # print("View", view_vector, "View Up", view_up_vector)
        # print("Axis update, view dot:", view_dot)
        # print("mode", data.normal_mode, "paint normal", paint_normal, "paint up", paint_up)
        data.paint_normal_vector = paint_normal
        data.paint_up_vector = paint_up

        return {'FINISHED'}


class SprytileGridAdd(bpy.types.Operator):
    bl_idname = "sprytile.grid_add"
    bl_label = "Add New Grid"
    bl_description = "Add new tile grid"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.add_new_grid(context)
        return {'FINISHED'}

    @staticmethod
    def add_new_grid(context):
        mat_list = context.scene.sprytile_mats
        target_mat = None

        if len(mat_list) > 0:
            target_mat = mat_list[0]

        grid_id = context.object.sprytile_gridid

        target_grid = get_grid(context, grid_id)
        if target_grid is not None:
            for mat in mat_list:
                if mat.mat_id == target_grid.mat_id:
                    target_mat = mat
                    break

        if target_mat is None:
            return

        grid_idx = -1
        for idx, grid in enumerate(mat.grids):
            if grid.id == grid_id:
                grid_idx = idx
                break

        new_idx = len(target_mat.grids)

        new_grid = target_mat.grids.add()
        new_grid.mat_id = target_mat.mat_id
        new_grid.id = get_highest_grid_id(context) + 1

        if grid_idx > -1:
            new_grid.grid = target_mat.grids[grid_idx].grid
            target_mat.grids.move(new_idx, grid_idx + 1)

        bpy.ops.sprytile.build_grid_list()


class SprytileGridRemove(bpy.types.Operator):
    bl_idname = "sprytile.grid_remove"
    bl_label = "Remove Grid"
    bl_description = "Remove selected tile grid"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.delete_grid(context)
        return {'FINISHED'}

    @staticmethod
    def delete_grid(context):
        mat_list = context.scene.sprytile_mats
        target_mat = None

        if len(mat_list) > 0:
            target_mat = mat_list[0]

        grid_id = context.object.sprytile_gridid

        target_grid = get_grid(context, grid_id)
        if target_grid is not None:
            for mat in mat_list:
                if mat.mat_id == target_grid.mat_id:
                    target_mat = mat
                    break

        if target_mat is None or len(target_mat.grids) <= 1:
            return

        grid_idx = -1
        for idx, grid in enumerate(target_mat.grids):
            if grid.id == grid_id:
                grid_idx = idx
                break

        target_mat.grids.remove(grid_idx)
        bpy.ops.sprytile.build_grid_list()


class SprytileGridCycle(bpy.types.Operator):
    bl_idname = "sprytile.grid_cycle"
    bl_label = "Cycle grid settings"

    direction = bpy.props.IntProperty(default=1)

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.cycle_grid(context)
        return {'FINISHED'}

    def cycle_grid(self, context):
        obj = context.object
        curr_grid = get_grid(context, obj.sprytile_gridid)
        if curr_grid is None:
            return

        curr_mat = get_mat_data(context, curr_grid.mat_id)
        if curr_mat is None:
            return

        idx = -1
        for grid in curr_mat.grids:
            idx += 1
            if grid.id == curr_grid.id:
                break

        idx += self.direction
        if idx < 0:
            idx = len(curr_mat.grids)-1
        if idx >= len(curr_mat.grids):
            idx = 0

        obj.sprytile_gridid = curr_mat.grids[idx].id
        bpy.ops.sprytile.build_grid_list()


class SprytileStartTool(bpy.types.Operator):
    bl_idname = "sprytile.start_tool"
    bl_label = "Start Sprytile Paint"

    mode = bpy.props.IntProperty(default=3)

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        if self.mode is 0:
            context.scene.sprytile_data.paint_mode = 'SET_NORMAL'
        if self.mode is 1:
            context.scene.sprytile_data.paint_mode = 'PAINT'
        if self.mode is 2:
            context.scene.sprytile_data.paint_mode = 'MAKE_FACE'
        bpy.ops.sprytile.modal_tool('INVOKE_REGION_WIN')
        return {'FINISHED'}


class SprytileGridMove(bpy.types.Operator):
    bl_idname = "sprytile.grid_move"
    bl_label = "Move Grid"
    bl_description = "Move selected tile grid up or down"

    direction = bpy.props.IntProperty(default=1)

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.move_grid(context)
        return {'FINISHED'}

    def move_grid(self, context):
        obj = context.object
        curr_grid = get_grid(context, obj.sprytile_gridid)
        if curr_grid is None:
            return

        curr_mat = get_mat_data(context, curr_grid.mat_id)
        if curr_mat is None:
            return

        idx = -1
        for grid in curr_mat.grids:
            idx += 1
            if grid.id == curr_grid.id:
                break

        old_idx = idx
        idx = old_idx + self.direction
        if idx < 0:
            idx = len(curr_mat.grids)-1
        if idx >= len(curr_mat.grids):
            idx = 0

        curr_mat.grids.move(old_idx, idx)
        obj.sprytile_gridid = curr_mat.grids[idx].id
        bpy.ops.sprytile.build_grid_list()


class SprytileNewMaterial(bpy.types.Operator):
    bl_idname = "sprytile.add_new_material"
    bl_label = "New Shadeless Material"
    bl_description = "Create a new shadeless material"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def invoke(self, context, event):
        obj = context.object
        if obj.type != 'MESH':
            return {'FINISHED'}

        mat = bpy.data.materials.new(name="Material")

        set_idx = len(obj.material_slots)
        bpy.ops.object.material_slot_add()

        obj.active_material_index = set_idx
        obj.material_slots[set_idx].material = mat

        bpy.ops.sprytile.material_setup('INVOKE_DEFAULT')
        bpy.ops.sprytile.validate_grids('INVOKE_DEFAULT')
        bpy.data.materials.update()
        return {'FINISHED'}


class SprytileSetupMaterial(bpy.types.Operator):
    bl_idname = "sprytile.material_setup"
    bl_label = "Set Material to Shadeless"
    bl_description = "Make current selected material shadeless, for pixel art texture purposes"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        obj = context.object
        if obj.type != 'MESH':
            return {'FINISHED'}

        mat = obj.material_slots[obj.active_material_index].material
        mat.use_shadeless = True
        mat.use_transparency = True
        mat.transparency_method = 'Z_TRANSPARENCY'
        mat.alpha = 0.0
        return {'FINISHED'}


class SprytileLoadTileset(bpy.types.Operator, ImportHelper):

    bl_idname = "sprytile.tileset_load"
    bl_label = "Load Tileset"
    bl_description = "Load a tileset into the current material"

    # For some reason this full list doesn't really work,
    # reordered the list to prioritize common file types
    # filter_ext = "*" + ";*".join(bpy.path.extensions_image.sort())

    filter_glob = StringProperty(
        default="*.bmp;*.psd;*.hdr;*.rgba;*.jpg;*.png;*.tiff;*.tga;*.jpeg;*.jp2;*.rgb;*.dds;*.exr;*.psb;*.j2c;*.dpx;*.tif;*.tx;*.cin;*.pdd;*.sgi",
        options={'HIDDEN'},
    )

    def execute(self, context):
        if context.object.type != 'MESH':
            return {'FINISHED'}
        # Check object material count, if 0 create a new material before loading
        if len(context.object.material_slots.items()) < 1:
            bpy.ops.sprytile.add_new_material('INVOKE_DEFAULT')
        SprytileLoadTileset.load_tileset_file(context, self.filepath)
        return {'FINISHED'}

    @staticmethod
    def load_tileset_file(context, filepath):
        obj = context.object

        texture_name = filepath[filepath.rindex(path.sep) + 1:]
        material_name = filepath[filepath.rindex(path.sep) + 1: filepath.rindex('.')]

        bpy.ops.sprytile.material_setup()

        target_mat = obj.material_slots[obj.active_material_index].material
        target_mat.name = material_name

        target_mat.texture_slots.clear(0)
        target_slot = target_mat.texture_slots.create(0)

        loaded_img = bpy.data.images.load(filepath)

        target_texture = bpy.data.textures.new(texture_name, type='IMAGE')
        target_texture.image = loaded_img

        target_slot.texture = target_texture

        bpy.ops.sprytile.texture_setup('INVOKE_DEFAULT')
        bpy.ops.sprytile.validate_grids('INVOKE_DEFAULT')
        bpy.data.textures.update()


class SprytileNewTileset(bpy.types.Operator, ImportHelper):

    bl_idname = "sprytile.tileset_new"
    bl_label = "Add Tileset"
    bl_description = "Create a new material and load another tileset"

    # For some reason this full list doesn't really work,
    # reordered the list to prioritize common file types
    # filter_ext = "*" + ";*".join(bpy.path.extensions_image.sort())

    filter_glob = StringProperty(
        default="*.bmp;*.psd;*.hdr;*.rgba;*.jpg;*.png;*.tiff;*.tga;*.jpeg;*.jp2;*.rgb;*.dds;*.exr;*.psb;*.j2c;*.dpx;*.tif;*.tx;*.cin;*.pdd;*.sgi",
        options={'HIDDEN'},
    )

    def execute(self, context):
        if context.object.type != 'MESH':
            return {'FINISHED'}
        bpy.ops.sprytile.add_new_material('INVOKE_DEFAULT')
        SprytileLoadTileset.load_tileset_file(context, self.filepath)
        return {'FINISHED'}


class SprytileSetupTexture(bpy.types.Operator):
    bl_idname = "sprytile.texture_setup"
    bl_label = "Setup Pixel Texture"
    bl_description = "Change texture settings for crunchy pixelart style"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.setup_tex(context)
        return {'FINISHED'}

    @staticmethod
    def setup_tex(context):
        """"""
        obj = context.object
        if obj.type != 'MESH':
            return
        material = obj.material_slots[obj.active_material_index].material
        target_texture = None
        target_img = None
        target_slot = None
        for texture_slot in material.texture_slots:
            if texture_slot is None:
                continue
            if texture_slot.texture is None:
                continue
            if texture_slot.texture.type == 'NONE':
                continue
            if texture_slot.texture.type == 'IMAGE':
                # Cannot use the texture slot image reference directly
                # Have to get it through bpy.data.images to be able to use with BGL
                target_texture = bpy.data.textures.get(texture_slot.texture.name)
                target_img = bpy.data.images.get(texture_slot.texture.image.name)
                target_slot = texture_slot
                break
        if target_texture is None or target_img is None:
            return

        target_texture.use_preview_alpha = True
        target_texture.use_alpha = True
        target_texture.use_interpolation = False
        target_texture.use_mipmap = False
        target_texture.filter_type = 'BOX'
        target_texture.filter_size = 0.10
        target_img.use_alpha = True

        target_slot.use_map_color_diffuse = True
        target_slot.use_map_alpha = True
        target_slot.alpha_factor = 1.0
        target_slot.diffuse_color_factor = 1.0
        target_slot.texture_coords = 'UV'


class SprytileValidateGridList(bpy.types.Operator):
    bl_idname = "sprytile.validate_grids"
    bl_label = "Validate Tile Grids"
    bl_description = "Press if tile grids are not displaying properly"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.validate_grids(context)
        return {'FINISHED'}

    @staticmethod
    def validate_grids(context):
        mat_list = bpy.data.materials
        mat_data_list = context.scene.sprytile_mats

        # Validate the material IDs in scene.sprytile_mats
        for check_mat_data in mat_data_list:
            mat_idx = mat_list.find(check_mat_data.mat_id)
            if mat_idx > -1:
                continue

            # This mat data id not found in materials
            # Loop through materials looking for one
            # that doesn't appear in sprytile_mats list
            for check_mat in mat_list:
                mat_unused = True
                for mat_data in mat_data_list:
                    if mat_data.mat_id == check_mat.name:
                        mat_unused = False
                        break

                if mat_unused:
                    target_mat_id = check_mat_data.mat_id
                    check_mat_data.mat_id = check_mat.name
                    for grid in check_mat_data.grids:
                        grid.mat_id = check_mat.name
                    for list_display in context.scene.sprytile_list.display:
                        if list_display.mat_id == target_mat_id:
                            list_display.mat_id = check_mat.name
                    break

        remove_idx = []

        # Filter out mat data with invalid IDs or users
        for idx, mat in enumerate(mat_data_list.values()):
            mat_idx = mat_list.find(mat.mat_id)
            if mat_idx < 0:
                remove_idx.append(idx)
                continue
            if mat_list[mat_idx].users == 0:
                remove_idx.append(idx)
            for grid in mat.grids:
                grid.mat_id = mat.mat_id
        remove_idx.reverse()
        for idx in remove_idx:
            mat_data_list.remove(idx)

        # Loop through available materials, checking if mat_data_list has
        # at least one entry for each material
        for mat in mat_list:
            if mat.users == 0:
                continue
            is_mat_valid = False
            for mat_data in mat_data_list:
                if mat_data.mat_id == mat.name:
                    is_mat_valid = True
                    break
            if is_mat_valid is False:
                mat_data_entry = mat_data_list.add()
                mat_data_entry.mat_id = mat.name
                mat_grid = mat_data_entry.grids.add()
                mat_grid.mat_id = mat.name
                mat_grid.id = get_highest_grid_id(context) + 1

        context.object.sprytile_gridid = get_highest_grid_id(context)
        bpy.ops.sprytile.build_grid_list()


class SprytileBuildGridList(bpy.types.Operator):
    bl_idname = "sprytile.build_grid_list"
    bl_label = "Sprytile Build Grid List"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.build_list(context)
        return {'FINISHED'}

    @staticmethod
    def build_list(context):
        """Build the scene.sprytile_list.display from scene.sprytile_mats"""
        display_list = context.scene.sprytile_list.display
        mat_list = context.scene.sprytile_mats

        display_list.clear()
        for mat_data in mat_list:
            mat_display = display_list.add()
            mat_display.mat_id = mat_data.mat_id
            if mat_data.is_expanded is False:
                continue
            for mat_grid in mat_data.grids:
                idx = len(display_list)
                grid_display = display_list.add()
                grid_display.grid_id = mat_grid.id
                if context.object.sprytile_gridid == grid_display.grid_id:
                    context.scene.sprytile_list.idx = idx


class SprytileRotateLeft(bpy.types.Operator):
    bl_idname = "sprytile.rotate_left"
    bl_label = "Rotate Sprytile Left"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        curr_rotation = context.scene.sprytile_data.mesh_rotate
        curr_rotation += 1.5708
        if curr_rotation > 6.28319:
            curr_rotation = 0
        context.scene.sprytile_data.mesh_rotate = curr_rotation
        return {'FINISHED'}


class SprytileRotateRight(bpy.types.Operator):
    bl_idname = "sprytile.rotate_right"
    bl_label = "Rotate Sprytile Right"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        curr_rotation = context.scene.sprytile_data.mesh_rotate
        curr_rotation -= 1.5708
        if curr_rotation < -6.28319:
            curr_rotation = 0
        context.scene.sprytile_data.mesh_rotate = curr_rotation
        return {'FINISHED'}


class SprytileReloadImages(bpy.types.Operator):
    bl_idname = "sprytile.reload_imgs"
    bl_label = "Reload All Images"
    bl_description = "Automatically reload images referenced by the scene"

    def invoke(self, context, event):
        for img in bpy.data.images:
            if img is None:
                continue
            img.reload()
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
        return {'FINISHED'}


class SprytileReloadImagesAuto(bpy.types.Operator):
    bl_idname = "sprytile.reload_auto"
    bl_label = "Reload All Images (Auto)"

    _timer = None
    last_check_time = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            if context.scene.sprytile_data.auto_reload is False:
                self.cancel(context)
                return {'CANCELLED'}

            if self.check_files():
                for window in context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                            area.tag_redraw()

        return {'PASS_THROUGH'}

    def check_files(self):
        did_reload = False
        for img in bpy.data.images:
            if img is None:
                continue
            filepath = abspath(img.filepath)
            if path.exists(filepath) is False:
                continue
            file_mod = path.getmtime(filepath)
            filetime = datetime.fromtimestamp(file_mod)
            if self.last_check_time is None or filetime > self.last_check_time:
                print("Reloading", img.filepath)
                img.reload()
                did_reload = True
        self.last_check_time = datetime.now()
        return did_reload

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.last_check_time = None
        self.check_files()
        wm = context.window_manager
        self._timer = wm.event_timer_add(2, context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)


class SprytileUpdateCheck(bpy.types.Operator):
    bl_idname = "sprytile.update_check"
    bl_label = "Check for Update"

    def invoke(self, context, event):
        print("Check itch.io API")
        import sys
        print(sys.modules['sprytile'].bl_info.get('version', (-1, -1, -1)))
        import urllib.request
        import json
        url = "https://itch.io/api/1/x/wharf/latest?game_id=98966&channel_name=addon"
        response = urllib.request.urlopen(url)
        data = response.read()
        encoding = response.info().get_content_charset('utf-8')
        json_data = json.loads(data.decode(encoding))
        print(json_data)
        return {'FINISHED'}


class SprytileMakeDoubleSided(bpy.types.Operator):
    bl_idname = "sprytile.make_double_sided"
    bl_label = "Make Double Sided (Sprytile)"
    bl_description = "Duplicate selected faces and flip normals"

    def execute(self, context):
        self.invoke(context, None)

    def invoke(self, context, event):
        print("Invoked make double sided")
        if context.object is None or (context.object.type != 'MESH' or context.object.mode != 'EDIT'):
            print("Nope")
            return {'FINISHED'}
        mesh = bmesh.from_edit_mesh(context.object.data)
        double_face = []
        for face in mesh.faces:
            if not face.select:
                continue
            double_face.append(face)
        for face in double_face:
            face.copy(True, True)
            face.normal_flip()
            face.normal_update()

        mesh.faces.index_update()
        mesh.faces.ensure_lookup_table()
        bmesh.update_edit_mesh(context.object.data, True, True)
        return {'FINISHED'}


class SprytileSetupGrid(bpy.types.Operator):
    bl_idname = "sprytile.setup_grid"
    bl_label = "Floor Grid To Pixels"
    bl_description = "Make floor grid display follow world pixel settings"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        pixel_unit = (1 / context.scene.sprytile_data.world_pixels)
        space_data = context.space_data
        space_data.grid_scale = pixel_unit
        space_data.grid_subdivisions = 1
        context.scene.tool_settings.use_snap = True
        context.scene.tool_settings.snap_element = 'INCREMENT'
        return {'FINISHED'}


class SprytileGridTranslate(bpy.types.Operator):
    bl_idname = "sprytile.translate_grid"
    bl_label = "Pixel Translate (Sprytile)"

    @staticmethod
    def draw_callback(self, context):
        if self.exec_counter != -1 or self.ref_pos is None:
            return None

        check_pos = self.get_ref_pos(context)
        measure_vec = check_pos - self.ref_pos
        pixel_unit = 1 / context.scene.sprytile_data.world_pixels
        for i in range(3):
            measure_vec[i] = int(round(measure_vec[i] / pixel_unit))

        screen_y = context.region.height - 45
        screen_x = 20
        padding = 5

        font_id = 0
        font_size = 16
        blf.size(font_id, font_size, 72)

        bgl.glColor4f(1, 1, 1, 1)

        readout_axis = ['X', 'Y', 'Z']
        for i in range(3):
            blf.position(font_id, screen_x, screen_y, 0)
            blf.draw(font_id, "%s : %d" % (readout_axis[i], measure_vec[i]))
            screen_y -= font_size + padding

    def modal(self, context, event):
        # User cancelled transform
        if event.type == 'ESC':
            return self.exit_modal(context)
        if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            return self.exit_modal(context)
        # On the timer events, count down the frames and execute the
        # translate operator when reach 0
        if event.type == 'TIMER':
            if self.exec_counter > 0:
                self.exec_counter -= 1

            if self.exec_counter == 0:
                self.exec_counter -= 1
                up_vec, right_vec, norm_vec = get_current_grid_vectors(context.scene)
                norm_vec = snap_vector_to_axis(norm_vec)
                axis_constraint = [
                    abs(norm_vec.x) == 0,
                    abs(norm_vec.y) == 0,
                    abs(norm_vec.z) == 0
                ]
                tool_value = bpy.ops.transform.translate(
                    'INVOKE_DEFAULT',
                    constraint_axis=axis_constraint,
                    snap=self.restore_settings is not None
                )
                # Translate tool moved nothing, exit
                if 'CANCELLED' in tool_value:
                    return self.exit_modal(context)

        # When the active operator changes, we know that translate has been completed
        if context.active_operator != self.watch_operator:
            return self.exit_modal(context)

        return {'PASS_THROUGH'}

    def get_ref_pos(self, context):
        if context.object.mode != 'EDIT':
            return None
        if self.bmesh is None:
            self.bmesh = bmesh.from_edit_mesh(context.object.data)
        if len(self.bmesh.select_history) <= 0:
            for vert in self.bmesh.verts:
                if vert.select:
                    return vert.co.copy()
            return None

        target = self.bmesh.select_history[0]
        if isinstance(target, BMFace):
            return target.verts[0].co.copy()
        if isinstance(target, BMEdge):
            return target.verts[0].co.copy()
        if isinstance(target, BMVert):
            return target.co.copy()
        return None

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        # When this tool is invoked, change the grid settings so that snapping
        # is on pixel unit steps. Save settings to restore later
        self.restore_settings = None
        space_data = context.space_data
        if space_data.type == 'VIEW_3D':
            self.restore_settings = {
                "grid_scale": space_data.grid_scale,
                "grid_sub": space_data.grid_subdivisions,
                "show_floor": space_data.show_floor,
                "pivot": context.space_data.pivot_point,
                "orient": context.space_data.transform_orientation,
                "use_snap": context.scene.tool_settings.use_snap,
                "snap_element": context.scene.tool_settings.snap_element
            }
            pixel_unit = 1 / context.scene.sprytile_data.world_pixels
            space_data.grid_scale = pixel_unit
            space_data.grid_subdivisions = 1
            space_data.show_floor = False
            space_data.pivot_point = 'CURSOR'
            space_data.transform_orientation = 'GLOBAL'
            context.scene.tool_settings.use_snap = True
            context.scene.tool_settings.snap_element = 'INCREMENT'
        # Remember what the current active operator is, when it changes
        # we know that the translate operator is complete
        self.watch_operator = context.active_operator

        # Countdown the frames passed through the timer. For some reason
        # the translate tool will not use the new grid scale if we switch
        # over immediately to translate.
        self.exec_counter = 5

        if context.object.mode == 'OBJECT':
            view_axis = sprytile_modal.SprytileModalTool.find_view_axis(context)
            if view_axis is not None:
                context.scene.sprytile_data.normal_mode = view_axis

        # Save the bmesh, and reference position
        self.bmesh = None
        self.ref_pos = self.get_ref_pos(context)

        args = self, context
        self.draw_handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, args, 'WINDOW', 'POST_PIXEL')

        win_mgr = context.window_manager
        self.timer = win_mgr.event_timer_add(0.1, context.window)
        win_mgr.modal_handler_add(self)
        context.scene.sprytile_data.is_grid_translate = True
        # Now go up to modal function to read the rest
        return {'RUNNING_MODAL'}

    def exit_modal(self, context):
        context.scene.sprytile_data.is_grid_translate = False
        pixel_unit = 1 / context.scene.sprytile_data.world_pixels
        # Restore grid settings if changed
        if self.restore_settings is not None:
            context.space_data.grid_scale = self.restore_settings['grid_scale']
            context.space_data.grid_subdivisions = self.restore_settings['grid_sub']
            context.space_data.show_floor = self.restore_settings['show_floor']
            context.space_data.pivot_point = self.restore_settings['pivot']
            context.space_data.transform_orientation = self.restore_settings['orient']
            context.scene.tool_settings.use_snap = self.restore_settings['use_snap']
            context.scene.tool_settings.snap_element = self.restore_settings['snap_element']
        # Didn't snap to grid, force to grid by calculating what the snapped translate would be
        else:
            op = context.active_operator
            if op is not None and op.bl_idname == 'TRANSFORM_OT_translate':
                # Take the translated value and snap it to pixel units
                translation = op.properties.value.copy()
                for i in range(3):
                    translation[i] = int(round(translation[i] / pixel_unit))
                    translation[i] *= pixel_unit
                # Move selection to where snapped position would be
                offset = translation - op.properties.value
                bpy.ops.transform.translate(value=offset)

        # Loop through the selected of the bmesh
        # if context.object.mode == 'EDIT' and context.scene.sprytile_data.snap_translate:
        #     for sel in self.bmesh.select_history:
        #         vert_list = []
        #         if isinstance(sel, BMFace) or isinstance(sel, BMEdge):
        #             for vert in sel.verts:
        #                 vert_list.append(vert)
        #         if isinstance(sel, BMVert):
        #             vert_list.append(sel)
        #         cursor_pos = context.scene.cursor_location
        #         for vert in vert_list:
        #             vert_offset = vert.co - cursor_pos
        #             vert_int = Vector((
        #                         int(round(vert_offset.x / pixel_unit)),
        #                         int(round(vert_offset.y / pixel_unit)),
        #                         int(round(vert_offset.z / pixel_unit))
        #                         ))
        #             new_vert_pos = cursor_pos + (vert_int * pixel_unit)
        #             vert.co = new_vert_pos

        self.bmesh = None
        bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle, 'WINDOW')
        context.window_manager.event_timer_remove(self.timer)
        return {'FINISHED'}


class SprytileResetData(bpy.types.Operator):
    bl_idname = "sprytile.reset_sprytile"
    bl_label = "Reset Sprytile"
    bl_description = "In case sprytile breaks…"

    def invoke(self, context, event):
        context.scene.sprytile_data.auto_reload = False
        context.scene.sprytile_data.is_running = False
        return {'FINISHED'}


class SprytileObjectDropDown(bpy.types.Menu):
    bl_idname = "SPRYTILE_object_drop"
    bl_label = "Sprytile Utilites"
    bl_description = "Sprytile helper functions"

    def draw(self, context):
        layout = self.layout
        layout.operator("sprytile.reset_sprytile")
        layout.separator()
        layout.operator("sprytile.material_setup")
        layout.operator("sprytile.texture_setup")
        layout.operator("sprytile.add_new_material")
        layout.separator()
        layout.operator("sprytile.props_teardown")


class SprytileObjectPanel(bpy.types.Panel):
    bl_label = "Sprytile Tools"
    bl_idname = "sprytile.panel_object"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Sprytile"

    @classmethod
    def poll(cls, context):
        if context.object and context.object.type == 'MESH':
            return context.object.mode == 'OBJECT'
        return True

    def draw(self, context):
        # if bpy.app.version > (2, 77, 0):
        #     addon_updater_ops.check_for_update_background()
        # else:
        #     addon_updater_ops.check_for_update_background(context)

        layout = self.layout

        if hasattr(context.scene, "sprytile_data") is False:
            box = layout.box()
            box.label("Sprytile Data Empty")
            box.operator("sprytile.props_setup")
            return

        layout.menu("SPRYTILE_object_drop")

        selection_enabled = True
        if context.object is None:
            selection_enabled = False
        elif context.object.type != 'MESH':
            selection_enabled = False

        box = layout.box()
        box.label("Material Setup")
        if selection_enabled:
            box.operator("sprytile.tileset_load")
            box.operator("sprytile.tileset_new")
        else:
            box.label("Select a mesh object to use Sprytile")

        layout.separator()
        help_text = "Enter edit mode to use Paint Tools"
        label_wrap(layout.column(), help_text)

        # layout.separator()
        # box = layout.box()
        # box.label("Pixel Translate Options")
        # box.prop(context.scene.sprytile_data, "snap_translate", toggle=True)

        layout.separator()
        box = layout.box()
        box.label("Image Utilities")
        split = box.split(percentage=0.3, align=True)
        split.prop(context.scene.sprytile_data, "auto_reload", toggle=True)
        split.operator("sprytile.reload_imgs")

        # addon_updater_ops.update_notice_box_ui(self, context)


class SprytileWorkDropDown(bpy.types.Menu):
    bl_idname = "SPRYTILE_work_drop"
    bl_label = "Sprytile Utilites"
    bl_description = "Sprytile helper functions"

    def draw(self, context):
        layout = self.layout
        layout.operator("sprytile.reset_sprytile")
        layout.separator()
        layout.operator("sprytile.setup_grid")
        layout.separator()
        layout.operator("sprytile.material_setup")
        layout.operator("sprytile.texture_setup")
        layout.separator()
        layout.operator("sprytile.make_double_sided")
        layout.separator()
        layout.operator("sprytile.props_teardown")


class SprytileLayerPanel(bpy.types.Panel):
    bl_label = "Layers"
    bl_idname = "sprytile.panel_layers"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Sprytile"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if context.object and context.object.type == 'MESH':
            return context.object.mode == 'EDIT'

    def draw(self, context):
        if hasattr(context.scene, "sprytile_data") is False:
            return
        data = context.scene.sprytile_data
        layout = self.layout
        box = layout.box()
        col = box.column_flow(align=True)
        col.prop(data, "set_work_layer", index=1, text="Decal Layer", toggle=True, expand=True)
        col.prop(data, "set_work_layer", index=0, text="Base Layer", toggle=True, expand=True)
        layout.prop(data, "mesh_decal_offset")

        # layout.prop(data, "work_layer_mode")
        # if data.work_layer_mode == 'MESH_DECAL':


class SprytileWorkflowPanel(bpy.types.Panel):
    bl_label = "Workflow"
    bl_idname = "sprytile.panel_workflow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Sprytile"

    @classmethod
    def poll(cls, context):
        if context.object and context.object.type == 'MESH':
            return context.object.mode == 'EDIT'

    def draw(self, context):
        addon_updater_ops.check_for_update_background()

        layout = self.layout

        if hasattr(context.scene, "sprytile_data") is False:
            box = layout.box()
            box.label("Sprytile Data Empty")
            box.operator("sprytile.props_setup")
            return

        data = context.scene.sprytile_data

        icon_id = "VIEW3D_VEC"
        # For some reason VIEW3D_VEC does not exist in 2.79?
        if bpy.app.version > (2, 78, 0):
            icon_id = "GRID"

        row = layout.row(align=False)
        row.label("", icon=icon_id)

        dropdown_icon = "TRIA_DOWN" if data.axis_plane_settings else "TRIA_RIGHT"

        sub_row = row.row(align=True)
        sub_row.prop(data, "axis_plane_settings", icon=dropdown_icon, emboss=False, text="")
        sub_row.prop(data, "axis_plane_display", expand=True)

        if data.axis_plane_settings:
            addon_prefs = context.user_preferences.addons[__package__].preferences
            layout.prop(addon_prefs, "preview_transparency")
            layout.prop(data, "axis_plane_color")
            layout.prop(data, "axis_plane_size")

        row = layout.row(align=False)
        row.label("", icon="SNAP_ON")
        row.prop(data, "cursor_snap", expand=True)

        row = layout.row(align=False)
        row.label("", icon="CURSOR")
        row.prop(data, "cursor_flow", toggle=True)

        # layout.prop(data, "snap_translate", toggle=True)

        layout.prop(data, "world_pixels")
        layout.menu("SPRYTILE_work_drop")

        split = layout.split(percentage=0.3, align=True)
        split.prop(data, "auto_reload", toggle=True)
        split.operator("sprytile.reload_imgs")



def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()
