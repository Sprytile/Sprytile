import bpy
import bmesh
from mathutils import Vector, Matrix, Quaternion

import sprytile_utils
import sprytile_uv
import sprytile_preview
import sprytile_modal


class ToolPaint:
    modal = None
    left_down = False

    def __init__(self, modal, rx_source):
        self.modal = modal
        rx_source.filter(
            lambda modal_evt: modal_evt.paint_mode == 'PAINT'
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

        #if modal_evt.build_preview:
        #    self.build_preview(context, scene, ray_origin, ray_vector)

    @staticmethod
    def process_preview(context, scene, face_index):
        obj = context.object
        data = scene.sprytile_data

        grid_id = obj.sprytile_gridid
        target_grid = sprytile_utils.get_grid(context, grid_id)

        if target_grid is None:
            return None, None, None, None, None, None, None

        target_img = sprytile_utils.get_grid_texture(obj, target_grid)
        if target_img is None:
            return None, None, None, None, None, None, None

        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene, False)

        face_verts = []
        mesh = bmesh.from_edit_mesh(context.object.data)

        face = mesh.faces[face_index]
        for loop in face.loops:
            vert = loop.vert
            face_verts.append(context.object.matrix_world @ vert.co)

        # Get the center of the preview verts
        vtx_min = Vector((float('inf'), float('inf'), float('inf')))
        vtx_max = Vector((float('-inf'), float('-inf'), float('-inf')))
        for vtx in face_verts:
            vtx_min.x = min(vtx.x, vtx_min.x)
            vtx_min.y = min(vtx.y, vtx_min.y)
            vtx_min.z = min(vtx.z, vtx_min.z)
            vtx_max.x = max(vtx.x, vtx_max.x)
            vtx_max.y = max(vtx.y, vtx_max.y)
            vtx_max.z = max(vtx.z, vtx_max.z)
        vtx_center = (vtx_min + vtx_max) / 2

        rotate_normal = plane_normal

        # Recalculate the rotation normal
        face_up, face_right = sprytile_modal.VIEW3D_OP_SprytileModalTool.get_face_up_vector(context.object, context, face_index)

        if face_up is not None and face_right is not None:
            rotate_normal = face_right.cross(face_up)

        if face_up is not None:
            up_vector = face_up
        if face_right is not None:
            right_vector = face_right

        rotation = Quaternion(rotate_normal, data.mesh_rotate)
        up_vector = rotation @ up_vector
        right_vector = rotation @ right_vector

        up_vector.normalize()
        right_vector.normalize()

        tile_xy = (target_grid.tile_selection[0], target_grid.tile_selection[1])

        offset_tile_id, offset_grid, coord_min, coord_max = sprytile_utils.get_grid_area(
            target_grid.tile_selection[2],
            target_grid.tile_selection[3],
            data.uv_flip_x,
            data.uv_flip_y)

        size_x = (coord_max[0] - coord_min[0]) + 1
        size_y = (coord_max[1] - coord_min[1]) + 1
        size_x *= target_grid.grid[0]
        size_y *= target_grid.grid[1]

        uvs = sprytile_uv.get_uv_pos_size(data, target_img.size, target_grid,
                                          tile_xy, size_x, size_y,
                                          up_vector, right_vector,
                                          face_verts, vtx_center)
        return face, face_verts, uvs, target_grid, data, target_img, tile_xy

    def execute(self, context, scene, ray_origin, ray_vector):
        # Raycast the object
        obj = context.object
        # Get the work layer filter, based on layer settings
        work_layer_mask = sprytile_utils.get_work_layer_data(scene.sprytile_data)
        hit_loc, hit_normal, face_index, hit_dist = self.modal.raycast_object(obj, ray_origin, ray_vector,
                                                                              work_layer_mask=work_layer_mask)
        if hit_loc is None:
            return

        face, verts, uvs, target_grid, data, target_img, tile_xy = ToolPaint.process_preview(
                                                                        context,
                                                                        scene,
                                                                        face_index)
        if face is None:
            return

        self.modal.add_virtual_cursor(hit_loc)
        sprytile_uv.apply_uvs(context, face, uvs, target_grid,
                              self.modal.bmesh, data, target_img,
                              tile_xy, origin_xy=tile_xy)

    @staticmethod
    def build_preview(context, scene, ray_origin, ray_vector):
        # Raycast the object
        obj = context.object
        # Get the work layer filter, based on layer settings
        work_layer_mask = sprytile_utils.get_work_layer_data(scene.sprytile_data)
        hit_loc, hit_normal, face_index, hit_dist = sprytile_modal.VIEW3D_OP_SprytileModalTool.raycast_object(obj, ray_origin, ray_vector,
                                                                              work_layer_mask=work_layer_mask)
        if hit_loc is None:
            sprytile_preview.clear_preview_data()
            return

        face, verts, uvs, target_grid, data, target_img, tile_xy = ToolPaint.process_preview(
                                                                        context,
                                                                        scene,
                                                                        face_index)
        if face is None:
            sprytile_preview.clear_preview_data()
            return

        sprytile_preview.set_preview_data(verts, uvs, is_quads=False)

    def handle_error(self, err):
        pass

    def handle_complete(self):
        pass


def register():
    pass


def unregister():
    pass


if __name__ == '__main__':
    register()