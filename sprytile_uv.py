import math

import bmesh
from mathutils import Vector, Matrix

import sprytile_utils


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