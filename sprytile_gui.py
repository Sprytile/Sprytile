import bpy
import bgl
import blf
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix

class SprytileGui(bpy.types.Operator):
    bl_idname = "sprytile.gui_win"
    bl_label = "Sprytile GUI"

    def modal(self, context, event):
        if context.scene.sprytile_data.is_running is False:
            self.exit_modal(context)
            return {'CANCELLED'}
        self.gui_event = event
        context.area.tag_redraw()
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            if context.scene.sprytile_data.is_running is False:
                return {'CANCELLED'}

            gui_args = (self, context)
            self.gl_handle = bpy.types.SpaceView3D.draw_handler_add(draw_gui, gui_args, 'WINDOW', 'POST_PIXEL')
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            return {'CANCELLED'}

    def exit_modal(self, context):
        if self.gl_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.gl_handle, 'WINDOW')
        self.gl_handle = None

def draw_gui(self, context):
    """Draw the tile selection GUI for Sprytile"""
    # Draw the GL based UI here.
    # Return True if okay for mouse interface
    # Fales if UI is using mouse input
    event = self.gui_event

    region = context.region
    object = context.object
    target_grid = context.scene.sprytile_grids[object.sprytile_gridid]
    target_mat = bpy.data.materials[target_grid.mat_id]
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
        context.scene.sprytile_data.gui_use_mouse = mouse_within_x and mouse_within_y

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
