import bpy
import numpy
from mathutils import Matrix
from mathutils.geometry import intersect_line_plane

import sprytile_utils
import sprytile_uv

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

        # Build the fill map
        fill_map, face_idx_array = self.build_fill_map(context, grid_up, grid_right, plane_normal, plane_size)

        # Convert from grid coordinate to map coordinate
        hit_array_coord = [int(hit_coord.x) + plane_size[0],
                           int((plane_size[1] * 2) - 1 - (hit_coord.y + plane_size[1]))]

        # Calculate the tile index of currently selected tile
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])
        # For getting paint settings later
        paint_setting_layer = self.modal.bmesh.faces.layers.int.get('paint_settings')

        # Pre calculate for auto merge
        shift_vec = plane_normal.normalized() * 0.01
        threshold = (1 / context.scene.sprytile_data.world_pixels) * 2

        # Get vectors again, to apply tile rotations in UV stage
        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene)

        # Flood fill targets map cell coordinates
        hit_coord_content = int(fill_map[hit_array_coord[1]][hit_array_coord[0]])
        fill_coords = self.flood_fill(fill_map, hit_array_coord, -1, hit_coord_content)
        for cell_coord in fill_coords:
            self.construct_fill(context, scene, sprytile_data, cell_coord, plane_size,
                                face_idx_array, paint_setting_layer, tile_xy,
                                ray_vector, shift_vec, threshold,
                                up_vector, right_vector, plane_normal,
                                grid_up, grid_right)

    def construct_fill(self, context, scene, sprytile_data, cell_coord, plane_size,
                       face_idx_array, paint_setting_layer, tile_xy,
                       ray_vector, shift_vec, threshold,
                       up_vector, right_vector, plane_normal,
                       grid_up, grid_right):

        grid_coord = [-plane_size[0] + cell_coord[0],
                      plane_size[1] - 1 - cell_coord[1]]

        # Check face index array, if -1, create face
        face_index = face_idx_array[cell_coord[1]][cell_coord[0]]
        did_build = False
        # If no existing face, build it
        if face_index < 0:
            did_build = True
            face_position = scene.cursor_location + grid_coord[0] * grid_right + grid_coord[1] * grid_up
            face_verts = self.modal.get_build_vertices(face_position,
                                                       grid_right, grid_up,
                                                       up_vector, right_vector)
            face_index = self.modal.create_face(context, face_verts)
        # Face existing...
        else:
            # Raycast to get the face index of the face, could have changed
            hit_loc, hit_normal, face_index, hit_dist = self.modal.raycast_grid_coord(
                context, context.object,
                grid_coord[0], grid_coord[1],
                grid_up, grid_right, plane_normal)

            # use the face paint settings for the UV map step
            face = self.modal.bmesh.faces[face_index]
            if sprytile_data.fill_lock_transform and paint_setting_layer is not None:
                paint_setting = face[paint_setting_layer]
                sprytile_utils.from_paint_settings(context.scene.sprytile_data, paint_setting)

        face_up, face_right = self.modal.get_face_up_vector(context, face_index)
        if face_up is not None and face_up.dot(up_vector) < 0.95:
            data = context.scene.sprytile_data
            rotate_matrix = Matrix.Rotation(data.mesh_rotate, 4, plane_normal)
            up_vector = rotate_matrix * face_up
            right_vector = rotate_matrix * face_right

        sprytile_uv.uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.modal.bmesh)

        if did_build and sprytile_data.auto_merge:
            face = self.modal.bmesh.faces[face_index]
            face.select = True
            # Find the face center, to raycast from later
            face_center = context.object.matrix_world * face.calc_center_bounds()
            # Move face center back a little for ray casting
            face_center += shift_vec

            bpy.ops.mesh.remove_doubles(threshold=threshold, use_unselected=True)

            for el in [self.modal.bmesh.faces, self.modal.bmesh.verts, self.modal.bmesh.edges]:
                el.index_update()
                el.ensure_lookup_table()

            # Modified the mesh, refresh and raycast to find the new face index
            self.modal.update_bmesh_tree(context)
            loc, norm, new_face_idx, hit_dist = self.modal.raycast_object(context.object, face_center, ray_vector, 0.1)
            if new_face_idx is not None:
                self.modal.bmesh.faces[new_face_idx].select = False

    def build_fill_map(self, context, grid_up, grid_right, plane_normal, plane_size):
        # Use raycast_grid_coord to build a 2d array of work plane
        fill_array = numpy.zeros((plane_size[1] * 2, plane_size[0] * 2))
        face_idx_array = numpy.zeros((plane_size[1] * 2, plane_size[0] * 2))
        face_idx_array.fill(-1)
        for y in range(plane_size[1] * 2):
            y_coord = plane_size[1] - 1 - y
            for x in range(plane_size[0] * 2):
                x_coord = -plane_size[0] + x
                hit_loc, hit_normal, face_index, hit_dist = self.modal.raycast_grid_coord(
                                                                context, context.object, x_coord, y_coord,
                                                                grid_up, grid_right, plane_normal)

                if hit_loc is not None:
                    grid_id, tile_packed_id = self.modal.get_tiledata_from_index(face_index)
                    map_value = 1
                    if tile_packed_id is not None:
                        map_value = tile_packed_id
                    fill_array[y][x] = map_value
                    face_idx_array[y][x] = face_index

                x_coord += 1
            y_coord += 1
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
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()