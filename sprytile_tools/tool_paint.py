import bpy
from mathutils import Vector, Matrix, Quaternion

import sprytile_utils
import sprytile_uv


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

        if modal_evt.build_preview:
            self.build_preview(context, scene, ray_origin, ray_vector)

    def execute(self, context, scene, ray_origin, ray_vector):
        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(context.scene)
        hit_loc, normal, face_index, distance = self.modal.raycast_object(context.object, ray_origin, ray_vector,
                                                                          world_normal=True)
        if face_index is None:
            return

        normal.normalize()

        self.modal.add_virtual_cursor(hit_loc)
        # Change the uv of the given face
        grid_id = context.object.sprytile_gridid
        grid = sprytile_utils.get_grid(context, grid_id)
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])

        face_up, face_right = self.modal.get_face_up_vector(context, face_index)
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
        sprytile_uv.uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.modal.bmesh)

    def build_preview(self, context, scene, ray_origin, ray_vector):
        obj = context.object
        data = scene.sprytile_data

        grid_id = obj.sprytile_gridid
        target_grid = sprytile_utils.get_grid(context, grid_id)

        target_img = sprytile_utils.get_grid_texture(obj, target_grid)
        if target_img is None:
            return

        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene, False)

        # Raycast the object
        hit_loc, hit_normal, face_index, hit_dist = self.modal.raycast_object(obj, ray_origin, ray_vector)
        # Didn't hit a face, do nothing
        if face_index is None:
            self.modal.set_preview_data(None, None)
            return

        preview_verts = []

        face = self.modal.bmesh.faces[face_index]
        for loop in face.loops:
            vert = loop.vert
            preview_verts.append(context.object.matrix_world * vert.co)

        # Get the center of the preview verts
        vtx_center = Vector((0, 0, 0))
        for vtx in preview_verts:
            vtx_center += vtx
        vtx_center /= len(preview_verts)

        rotate_normal = plane_normal

        # Recalculate the rotation normal
        face_up, face_right = self.modal.get_face_up_vector(context, face_index)

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
        preview_uvs = sprytile_uv.get_uv_positions(data, target_img.size, target_grid,
                                                   up_vector, right_vector, tile_xy,
                                                   preview_verts, vtx_center)

        self.modal.set_preview_data(preview_verts, preview_uvs, is_quads=False)

    def handle_error(self, err):
        pass

    def handle_complete(self):
        pass


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()