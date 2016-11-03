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
    event = self.gui_event

    region = context.region
    object = context.object
    target_mat = bpy.data.materials[object.sprytile_matid]
    # look through the texture slots of the material
    # to find the first with a texture/image
    target_img = None
    for texture_slot in target_mat.texture_slots:
        if texture_slot is None:
            continue
        if texture_slot.texture is None:
            continue
        if texture_slot.texture.image is None:
            continue
        # Cannot use the texture slot image reference directly
        # Have to get it through bpy.data.images to be able to use with BGL
        target_img = bpy.data.images.get(texture_slot.texture.image.name)
        break

    if target_img is None:
        return

    # Draw a quad
    min = Vector((region.width - 200, 5))
    max = Vector((region.width - 5, 200))

    if event is not None and event.type in {'MOUSEMOVE'}:
        mouse_within_x = event.mouse_region_x >= min.x and event.mouse_region_x <= max.x
        mouse_within_y = event.mouse_region_y >= min.y and event.mouse_region_y <= max.y
        self.gui_use_mouse = mouse_within_x and mouse_within_y

    target_img.gl_load(0, bgl.GL_NEAREST, bgl.GL_NEAREST)
    bgl.glBindTexture(bgl.GL_TEXTURE_2D, target_img.bindcode[0])
    bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, bgl.GL_NEAREST)
    bgl.glEnable(bgl.GL_TEXTURE_2D)
    bgl.glEnable(bgl.GL_BLEND)

    bgl.glColor4f(1.0, 1.0, 1.0, 1.0)
    bgl.glBegin(bgl.GL_QUADS)

    bgl.glTexCoord2f(0,0)
    bgl.glVertex2f(min.x, min.y)

    bgl.glTexCoord2f(0,1)
    bgl.glVertex2f(min.x, max.y)

    bgl.glTexCoord2f(1,1)
    bgl.glVertex2f(max.x, max.y)

    bgl.glTexCoord2f(1,0)
    bgl.glVertex2f(max.x, min.y)

    bgl.glEnd()

    # restore opengl defaults
    bgl.glLineWidth(1)
    bgl.glDisable(bgl.GL_BLEND)
    bgl.glDisable(bgl.GL_TEXTURE_2D)
    bgl.glColor4f(0.0, 0.0, 0.0, 1.0)

def register():
    bpy.utils.register_module(__name__)

def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
