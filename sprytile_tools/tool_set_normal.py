import bpy


class ToolSetNormal:
    modal = None

    def __init__(self, modal, rx_source):
        self.modal = modal
        rx_source.filter(
            lambda modal_evt: modal_evt.paint_mode == 'SET_NORMAL'
        ).subscribe(
            on_next=lambda modal_evt: self.process_tool(modal_evt),
            on_error=lambda err: self.handle_error(err),
            on_completed=lambda: self.handle_complete()
        )

    def process_tool(self, modal_evt):
        if self.modal.rx_data is None:
            return

        self.modal.clear_preview_data()
        if modal_evt.left_down is False:
            return

        # get the context arguments
        context = self.modal.rx_data.context
        ray_origin = self.modal.rx_data.ray_origin
        ray_vector = self.modal.rx_data.ray_vector

        hit_loc, hit_normal, face_index, distance = self.modal.raycast_object(context.object, ray_origin, ray_vector)
        if hit_loc is None:
            return
        hit_normal = context.object.matrix_world.to_quaternion() * hit_normal

        face_up_vector, face_right_vector = self.modal.get_face_up_vector(context, face_index)
        if face_up_vector is None:
            return

        sprytile_data = context.scene.sprytile_data
        sprytile_data.paint_normal_vector = hit_normal
        sprytile_data.paint_up_vector = face_up_vector
        sprytile_data.lock_normal = True
        sprytile_data.paint_mode = 'MAKE_FACE'
        pass

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