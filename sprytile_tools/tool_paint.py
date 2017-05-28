import bpy

class ToolPaint:
    def __init__(self, rx_source):
        rx_source.filter(
            lambda x: x.data.paint_mode == 'PAINT'
        ).subscribe(
            on_next=lambda x: self.process_tool(x),
            on_error=lambda err: self.handle_error(err),
            on_completed=lambda: self.handle_complete()
        )

    def process_tool(self, modal):
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