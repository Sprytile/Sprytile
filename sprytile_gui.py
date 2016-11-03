import bpy
import bgl
import blf
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix

def draw_gui(self, context):
    """Draw the tile selection GUI for Sprytile"""
    # Draw the GL based UI here.
    # Return True if okay for mouse interface
    # Fales if UI is using mouse input
    self.gui_use_mouse = False
    event = self.gui_event

    region = context.region
    object = context.object

    # bgl.glBegin(bgl.GL_LINES)
    bgl.glRecti(5, 5, int(region.width / 2), int(region.height / 2))
    bgl.glEnd()

    # restore opengl defaults
    bgl.glLineWidth(1)
    bgl.glDisable(bgl.GL_BLEND)
    bgl.glColor4f(0.0, 0.0, 0.0, 1.0)

def register():
    bpy.utils.register_module(__name__)

def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
