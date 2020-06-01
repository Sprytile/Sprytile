import bpy
import numpy
from mathutils import Matrix
from mathutils.geometry import intersect_line_plane

import sprytile_utils
import sprytile_uv
from sprytile_uv import UvDataLayers

class ToolFill:
    modal = None
    left_down = False

    def __init__(self, modal, rx_source):
        self.modal = modal
        rx_source.filter(
            lambda modal_evt: modal_evt.paint_mode == 'FILL'
        ).subscribe(
            on_next=lambda modal_evt: self.process_tool(modal_evt),
            on_error=lambda err: self.handle_error(err),
            on_completed=lambda: self.handle_complete()
        )

    def process_tool(self, modal_evt):
        if self.modal.rx_data is None:
            return

        # get the context arguments
        context = self.modal.rx_data.context
        scene = context.scene
        ray_origin = self.modal.rx_data.ray_origin
        ray_vector = self.modal.rx_data.ray_vector

        if modal_evt.left_down:
            if self.left_down is False:
                self.left_down = True
                self.execute_fill(context, scene, ray_origin, ray_vector)
        elif self.left_down:
            self.left_down = False
            bpy.ops.ed.undo_push()

    def handle_error(self, err):
        pass

    def handle_complete(self):
        pass

    def execute_fill(self, context, scene, ray_origin, ray_vector):
        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene, with_rotation=False)

        # Intersect on the virtual plane
        plane_hit = intersect_line_plane(ray_origin, ray_origin + ray_vector, scene.cursor.location, plane_normal)
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
            plane_hit, scene.cursor.location,
            right_vector.copy(), up_vector.copy(),
            world_pixels, grid_x, grid_y, as_coord=True
        )

        # Check hit_coord is inside the work plane grid
        plane_size = sprytile_data.fill_plane_size

        grid_min, grid_max = sprytile_utils.get_workplane_area(plane_size[0], plane_size[1])

        x_offset = 1
        if plane_size[0] % 2 == 1:
            grid_min[0] += x_offset
            grid_max[0] += x_offset

        if hit_coord.x < grid_min[0] or hit_coord.x >= grid_max[0]:
            return
        if hit_coord.y < grid_min[1] or hit_coord.y >= grid_max[1]:
            return

        # Build the fill map
        sel_coords, sel_size, sel_ids = sprytile_utils.get_grid_selection_ids(context, grid)
        fill_map, face_idx_array = self.build_fill_map(context, grid_up, grid_right, plane_normal,
                                                       plane_size, grid_min, grid_max, sel_ids)

        # Convert from grid coordinate to map coordinate
        hit_array_coord = [int(hit_coord.x) - grid_min[0],
                           int(hit_coord.y) - grid_min[1]]

        # For getting paint settings later
        paint_setting_layer = self.modal.bmesh.faces.layers.int.get(UvDataLayers.PAINT_SETTINGS)

        # Get vectors again, to apply tile rotations in UV stage
        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene)

        # Get the content in hit coordinate
        hit_coord_content = int(fill_map[hit_array_coord[1]][hit_array_coord[0]])
        # Get the coordinates that would be flood filled
        fill_coords = self.flood_fill(fill_map, hit_array_coord, -2, hit_coord_content)

        # If lock transform on, cache the paint settings before doing any operations
        paint_setting_cache = None
        if sprytile_data.fill_lock_transform and paint_setting_layer is not None:
            paint_setting_cache = [None]*len(fill_coords)
            for idx, cell_coord in enumerate(fill_coords):
                face_index = face_idx_array[cell_coord[1]][cell_coord[0]]
                if face_index > -1:
                    face = self.modal.bmesh.faces[face_index]
                    paint_setting_cache[idx] = face[paint_setting_layer]

        # Get the work layer filter, based on layer settings
        work_layer_mask = sprytile_utils.get_work_layer_data(sprytile_data)
        require_base_layer = sprytile_data.work_layer != 'BASE'

        origin_xy = (grid.tile_selection[0], grid.tile_selection[1])
        data = scene.sprytile_data
        # Loop through list of coords to be filled
        for idx, cell_coord in enumerate(fill_coords):
            # Fetch the paint settings from cache
            if paint_setting_cache is not None:
                paint_setting = paint_setting_cache[idx]
                if paint_setting is not None:
                    sprytile_utils.from_paint_settings(data, paint_setting)

            # Convert map coord to grid coord
            grid_coord = [grid_min[0] + cell_coord[0],
                          grid_min[1] + cell_coord[1]]

            sub_x = (grid_coord[0] - int(hit_coord.x)) % sel_size[0]
            sub_y = (grid_coord[1] - int(hit_coord.y)) % sel_size[1]
            sub_xy = sel_coords[(sub_y * sel_size[0]) + sub_x]
            self.modal.construct_face(context, grid_coord, [1,1],
                                      sub_xy, origin_xy,
                                      grid_up, grid_right,
                                      up_vector, right_vector,
                                      plane_normal,
                                      require_base_layer=require_base_layer,
                                      work_layer_mask=work_layer_mask)

    def build_fill_map(self, context, grid_up, grid_right,
                       plane_normal, plane_size, grid_min, grid_max,
                       selected_ids):
        # Use raycast_grid_coord to build a 2d array of work plane

        fill_array = numpy.full((plane_size[1], plane_size[0]), -1)
        face_idx_array = numpy.full((plane_size[1], plane_size[0]), -1)
        idx_y = 0
        idx_x = 0
        for y in range(grid_min[1], grid_max[1]):
            for x in range(grid_min[0], grid_max[0]):
                hit_loc, hit_normal, face_index, hit_dist = self.modal.raycast_grid_coord(
                                                                context, x, y,
                                                                grid_up, grid_right, plane_normal)

                if hit_loc is not None:
                    grid_id, tile_packed_id, width, height, origin = self.modal.get_tiledata_from_index(face_index)
                    map_value = 1
                    if tile_packed_id is not None:
                        map_value = tile_packed_id
                        if selected_ids is not None and tile_packed_id in selected_ids:
                            map_value = selected_ids[0]
                    fill_array[idx_y][idx_x] = map_value
                    face_idx_array[idx_y][idx_x] = face_index

                idx_x += 1
            idx_x = 0
            idx_y += 1

        return fill_array, face_idx_array

    @staticmethod
    def scan_line(fill_map, test_x, test_y, current, old_tile_idx, fill_stack):
        content = fill_map[test_y][test_x]
        if not current and content == old_tile_idx:
            line_coord = [test_x, test_y]
            fill_stack.append(line_coord)
            return True
        elif current and content != old_tile_idx:
            return False
        return current

    def flood_fill(self, fill_map, start_coord, new_tile_idx, old_tile_idx):
        flood_stack = []
        if new_tile_idx == old_tile_idx:
            return flood_stack
        fill_stack = [start_coord]
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
                    span_above = self.scan_line(fill_map, x, y - 1, span_above, old_tile_idx, fill_stack)
                # Scan line below
                if y < height - 1:
                    span_below = self.scan_line(fill_map, x, y + 1, span_below, old_tile_idx, fill_stack)
                x += 1
        return flood_stack


def register():
    pass


def unregister():
    pass


if __name__ == '__main__':
    register()