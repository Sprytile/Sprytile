import bpy
from mathutils import Vector, Matrix, Quaternion
from mathutils.geometry import distance_point_to_plane

import sprytile_utils
import sprytile_uv


class ToolBuild:
    modal = None
    left_down = False

    def __init__(self, modal, rx_source):
        self.modal = modal
        rx_source.filter(
            lambda modal_evt: modal_evt.paint_mode == 'MAKE_FACE'
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
            self.left_down = True
            self.execute(context, scene, ray_origin, ray_vector)
        elif self.left_down:
            self.left_down = False
            bpy.ops.ed.undo_push()

        if modal_evt.build_preview:
            self.build_preview(context, scene, ray_origin, ray_vector)

    def execute(self, context, scene, ray_origin, ray_vector):
        data = scene.sprytile_data
        grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])

        # Get vectors for grid
        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(
            scene,
            with_rotation=False
        )
        rotation = Quaternion(plane_normal, data.mesh_rotate)
        up_vector = rotation * up_vector
        right_vector = rotation * right_vector

        # Used to move raycast slightly along ray vector
        shift_vec = ray_vector.normalized() * 0.001

        # raycast grid to get the grid position under the mouse
        grid_coord, grid_right, grid_up, plane_pos = sprytile_utils.raycast_grid(
            scene, context,
            up_vector, right_vector, plane_normal,
            ray_origin, ray_vector,
            as_coord=True
        )

        # Get the area to build
        offset_tile_id, offset_grid = sprytile_utils.get_grid_area(
            grid.tile_selection[2],
            grid.tile_selection[3],
            data.uv_flip_x, data.uv_flip_y
        )

        # Loop through grid coordinates to build
        face_index = None
        for i in range(len(offset_grid)):
            grid_offset = offset_grid[i]
            tile_offset = offset_tile_id[i]

            grid_pos = [grid_coord[0] + grid_offset[0], grid_coord[1] + grid_offset[1]]
            tile_pos = [tile_xy[0] + tile_offset[0], tile_xy[1] + tile_offset[1]]

            face_index = self.modal.construct_face(context, grid_pos, tile_pos,
                                                   grid_up, grid_right,
                                                   up_vector, right_vector, plane_normal,
                                                   shift_vec=shift_vec)

        if data.cursor_flow and face_index is not None and face_index > -1:
            self.modal.flow_cursor(context, face_index, plane_pos)

    def build_preview(self, context, scene, ray_origin, ray_vector):
        obj = context.object
        data = scene.sprytile_data

        grid_id = obj.sprytile_gridid
        target_grid = sprytile_utils.get_grid(context, grid_id)

        target_img = sprytile_utils.get_grid_texture(obj, target_grid)
        if target_img is None:
            return

        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene, False)

        rotation = Quaternion(plane_normal, data.mesh_rotate)

        up_vector = rotation * up_vector
        right_vector = rotation * right_vector

        # Raycast to the virtual grid
        face_position, x_vector, y_vector, plane_cursor = sprytile_utils.raycast_grid(
            scene, context,
            up_vector, right_vector, plane_normal,
            ray_origin, ray_vector
        )

        if face_position is None:
            return

        offset_tile_id, offset_grid = sprytile_utils.get_grid_area(target_grid.tile_selection[2],
                                                                   target_grid.tile_selection[3],
                                                                   data.uv_flip_x,
                                                                   data.uv_flip_y)

        preview_verts = []
        preview_uvs = []
        for i in range(len(offset_tile_id)):
            grid_offset = offset_grid[i]
            tile_offset = offset_tile_id[i]

            x_offset = x_vector * grid_offset[0]
            y_offset = y_vector * grid_offset[1]

            coord_position = face_position + x_offset + y_offset
            coord_verts = self.modal.get_build_vertices(coord_position, x_vector, y_vector,
                                                        up_vector, right_vector)
            # Get the center of the preview verts
            vtx_center = Vector((0, 0, 0))
            for vtx in coord_verts:
                vtx_center += vtx
            vtx_center /= len(coord_verts)

            # Calculate the tile with offset
            tile_xy = (target_grid.tile_selection[0] + tile_offset[0],
                       target_grid.tile_selection[1] + tile_offset[1])

            coord_uvs = sprytile_uv.get_uv_positions(data, target_img.size, target_grid,
                                                     up_vector, right_vector, tile_xy,
                                                     coord_verts, vtx_center)

            preview_verts.extend(coord_verts)
            preview_uvs.extend(coord_uvs)

        self.modal.set_preview_data(preview_verts, preview_uvs)

    def handle_error(self, err):
        print("Error in build mode: {0}".format(err))
        pass

    def handle_complete(self):
        pass


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()
