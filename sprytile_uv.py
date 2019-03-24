import math

import bmesh
from mathutils import Vector, Matrix

import sprytile_utils


class UvDataLayers:
    GRID_INDEX = "grid_index"
    GRID_TILE_ID = "grid_tile_id"
    GRID_SEL_WIDTH = "grid_sel_width"
    GRID_SEL_HEIGHT = "grid_sel_height"
    GRID_SEL_ORIGIN = "grid_sel_origin"
    PAINT_SETTINGS = "paint_settings"
    WORK_LAYER = "work_layer"

    LAYER_NAMES = [GRID_INDEX, GRID_TILE_ID,
                   GRID_SEL_WIDTH, GRID_SEL_HEIGHT,
                   GRID_SEL_ORIGIN, PAINT_SETTINGS,
                   WORK_LAYER]


def get_uv_pos_size(data, image_size, target_grid, origin_xy, size_x, size_y,
                    up_vector, right_vector, verts, vtx_center):
    pixel_uv_x = 1.0 / image_size[0]
    pixel_uv_y = 1.0 / image_size[1]

    uv_unit_x = pixel_uv_x * size_x
    uv_unit_y = pixel_uv_y * size_y

    world_units = data.world_pixels
    world_convert = Vector((size_x / world_units,
                            size_y / world_units))

    # Build the translation matrix
    offset_matrix = Matrix.Translation((target_grid.offset[0] * pixel_uv_x, target_grid.offset[1] * pixel_uv_y, 0))
    rotate_matrix = Matrix.Rotation(target_grid.rotate, 4, 'Z')

    origin_x = target_grid.grid[0] + (target_grid.padding[0] * 2) + target_grid.margin[1] + target_grid.margin[3]
    origin_x *= origin_xy[0]
    origin_x += target_grid.padding[0]
    origin_x = pixel_uv_x * origin_x

    origin_y = target_grid.grid[1] + (target_grid.padding[1] * 2) + target_grid.margin[0] + target_grid.margin[2]
    origin_y *= origin_xy[1]
    origin_y += target_grid.padding[1]
    origin_y = pixel_uv_y * origin_y
    origin_matrix = Matrix.Translation((origin_x, origin_y, 0))

    uv_matrix = offset_matrix @ rotate_matrix @ origin_matrix

    flip_x = -1 if data.uv_flip_x else 1
    flip_y = -1 if data.uv_flip_y else 1
    flip_matrix = Matrix.Scale(flip_x, 4, right_vector) @ Matrix.Scale(flip_y, 4, up_vector)

    pad_offset = target_grid.auto_pad_offset
    if target_grid.auto_pad is False:
        pad_offset = 0
    pad_scale = Vector(((size_x - pad_offset) / size_x, (size_y - pad_offset) / size_y))
    pad_matrix = Matrix.Scale(pad_scale.x, 4, right_vector) @ Matrix.Scale(pad_scale.y, 4, up_vector)

    uv_min = Vector((float('inf'), float('inf')))
    uv_max = Vector((float('-inf'), float('-inf')))

    uv_verts = []
    for vert in verts:
        # Around center
        vert_pos = vert - vtx_center
        # Apply flip scaling
        vert_pos = flip_matrix @ vert_pos
        # Apply padding
        vert_pos = pad_matrix @ vert_pos
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
        vert_xy = uv_matrix @ vert_xy
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
        uv_center = uv_matrix @ uv_center
        uv_verts = get_uv_paint_modify(data, uv_verts, uv_matrix, pad_scale,
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
            uv_vert.x = min(uv_max.x, max(uv_pixel_x * pixel_uv_x, uv_min.x))
            uv_vert.y = min(uv_max.y, max(uv_pixel_y * pixel_uv_y, uv_min.y))

    return uv_verts


def get_uv_positions(data, image_size, target_grid, up_vector, right_vector, tile_xy, verts, vtx_center):
    """Given world vertices, find the UV position for each vert"""

    return get_uv_pos_size(data, image_size, target_grid, tile_xy,
                           target_grid.grid[0], target_grid.grid[1],
                           up_vector, right_vector,
                           verts, vtx_center)


def get_uv_paint_modify(data, uv_verts, uv_matrix, pad_scale, uv_unit_x, uv_unit_y, uv_min, uv_max, uv_center, pixel_uv):
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

    # Generate tile bounds with auto padding
    half_uv = Vector((uv_unit_x / 2, uv_unit_y / 2, 0))
    pad_matrix = Matrix.Scale(pad_scale.x, 4, Vector((1, 0, 0))) @ Matrix.Scale(pad_scale.y, 4, Vector((0, 1, 0)))
    tile_min = pad_matrix @ Vector((-half_uv.x, -half_uv.y, 0)) + half_uv
    tile_max = pad_matrix @ Vector((half_uv.x, half_uv.y, 0)) + half_uv
    tile_min = uv_matrix @ tile_min
    tile_max = uv_matrix @ tile_max
    # Actual bounds without auto padding
    tile_bound_min = uv_matrix @ Vector((0, 0, 0))
    tile_bound_max = uv_matrix @ Vector((uv_unit_x, uv_unit_y, 0))

    # Calculate tile stretch
    scale_x = 1
    scale_y = 1
    tile_size = tile_max - tile_min
    face_size = uv_max - uv_min

    if data.paint_stretch_x and face_size.x > 0:
        scale_x = tile_size.x / face_size.x
    if data.paint_stretch_y and face_size.y > 0:
        scale_y = tile_size.y / face_size.y

    matrix_stretch = Matrix.Scale(scale_x, 2, Vector((1, 0))) @ Matrix.Scale(scale_y, 2, Vector((0, 1)))

    threshold = tile_size * data.edge_threshold
    for uv_vert in uv_verts:
        # First, apply the stretch matrix
        uv = Vector((uv_vert.x, uv_vert.y))
        uv -= uv_center.xy
        uv = matrix_stretch @ uv
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
            snap_x = uv_pixel_x * pixel_uv.x
            snap_y = uv_pixel_y * pixel_uv.y
            uv.x = snap_x
            uv.y = snap_y
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
    # One final loop to keep in auto pad
    for uv_vert in uv_verts:
        if tile_bound_min.x <= uv_vert.x <= tile_bound_max.x:
            uv_vert.x = min(tile_max.x, max(tile_min.x, uv_vert.x))
        if tile_bound_min.y <= uv_vert.y <= tile_bound_max.y:
            uv_vert.y = min(tile_max.y, max(tile_min.y, uv_vert.y))

    return uv_verts


def uv_map_face(context, up_vector, right_vector, tile_xy, origin_xy, face_index, mesh, tile_size=(1, 1)):
    """
    UV map the given face
    :param context:
    :param up_vector: World up vector
    :param right_vector: World right vector
    :param tile_xy: Tile placement XY coordinates
    :param origin_xy: Origin XY of tile placement
    :param face_index: Face index to UV map
    :param mesh:
    :param tile_size: Tile units being UV mapped
    :return:
    """
    if mesh is None:
        return None, None

    scene = context.scene
    obj = context.object
    data = scene.sprytile_data

    grid_id = obj.sprytile_gridid
    target_grid = sprytile_utils.get_grid(context, grid_id)

    uv_layer = mesh.loops.layers.uv.verify()

    if face_index >= len(mesh.faces):
        return None, None

    target_img = sprytile_utils.get_grid_texture(obj, target_grid)
    if target_img is None:
        return None, None

    face = mesh.faces[face_index]
    if face.hide:
        return None, None

    vert_origin = context.object.matrix_world @ face.calc_center_bounds()
    verts = []
    for loop in face.loops:
        vert = loop.vert
        verts.append(context.object.matrix_world @ vert.co)

    tile_start = [tile_xy[0], tile_xy[1]]
    if tile_size[0] > 1 or tile_size[1] > 1:
        tile_start[0] -= tile_size[0]
        tile_start[1] -= tile_size[1]

    size_x = tile_size[0] * target_grid.grid[0]
    size_y = tile_size[1] * target_grid.grid[1]

    uv_verts = get_uv_pos_size(data, target_img.size,
                               target_grid, tile_start,
                               size_x, size_y,
                               up_vector, right_vector,
                               verts, vert_origin)

    if uv_verts is None:
        return None, None

    apply_uvs(context, face, uv_verts,
              target_grid, mesh, data,
              target_img, tile_xy,
              origin_xy=origin_xy,
              uv_layer=uv_layer)

    return face.index, target_grid


def apply_uvs(context, face, uv_verts, target_grid,
              mesh, data, target_img, tile_xy,
              uv_layer=None, origin_xy=None):

    if uv_layer is None:
        uv_layer = mesh.loops.layers.uv.verify()

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
    # If adding more layers, make sure setup in sprytile_modal.update_bmesh_tree
    grid_layer_id = mesh.faces.layers.int.get(UvDataLayers.GRID_INDEX)
    grid_layer_tileid = mesh.faces.layers.int.get(UvDataLayers.GRID_TILE_ID)
    grid_sel_width = mesh.faces.layers.int.get(UvDataLayers.GRID_SEL_WIDTH)
    grid_sel_height = mesh.faces.layers.int.get(UvDataLayers.GRID_SEL_HEIGHT)
    grid_sel_origin = mesh.faces.layers.int.get(UvDataLayers.GRID_SEL_ORIGIN)
    paint_settings_id = mesh.faces.layers.int.get(UvDataLayers.PAINT_SETTINGS)
    work_layer_id = mesh.faces.layers.int.get(UvDataLayers.WORK_LAYER)

    face = mesh.faces[face.index]
    row_size = math.ceil(target_img.size[0] / target_grid.grid[0])
    tile_id = (tile_xy[1] * row_size) + tile_xy[0]
    origin_id = tile_id
    if origin_xy is not None:
        origin_id = (origin_xy[1] * row_size) + origin_xy[0]

    paint_settings = sprytile_utils.get_paint_settings(data)
    work_layer_data = sprytile_utils.get_work_layer_data(data)

    sel_width = target_grid.tile_selection[2]
    sel_height = target_grid.tile_selection[3]

    face[grid_layer_id] = context.object.sprytile_gridid
    face[grid_layer_tileid] = tile_id
    face[grid_sel_width] = sel_width
    face[grid_sel_height] = sel_height
    face[grid_sel_origin] = origin_id
    face[paint_settings_id] = paint_settings
    face[work_layer_id] = work_layer_data

    bmesh.update_edit_mesh(context.object.data)
    mesh.faces.index_update()

    return face.index, target_grid


def register():
    pass


def unregister():
    pass


if __name__ == '__main__':
    register()
