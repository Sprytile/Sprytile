import bpy


class ToolPaint:
    modal = None

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
        # print("Pnt:", modal_evt.paint_mode)
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