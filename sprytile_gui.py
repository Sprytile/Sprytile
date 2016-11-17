import bpy
import bgl
import blf
from math import floor
from bgl import *
from bpy.props import *
from mathutils import Vector, Matrix
from . import sprytile_utils


class SprytileGuiData(bpy.types.PropertyGroup):
    zoom = FloatProperty(
        name="Sprytile UI zoom",
        default=1.0
    )
    use_mouse = BoolProperty(name="GUI use mouse")
    is_dirty = BoolProperty(name="Srpytile GUI redraw flag")


class SprytileGui(bpy.types.Operator):
    bl_idname = "sprytile.gui_win"
    bl_label = "Sprytile GUI"

    mouse_pt = None
    zoom_levels = [0.0625, 0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]

    # ================
    # Modal functions
    # ================
    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def modal(self, context, event):
        if context.scene.sprytile_data.is_running is False:
            SprytileGui.handler_remove(self, context)
            context.area.tag_redraw()
            return {'CANCELLED'}

        # Check if current_grid is different from current sprytile grid
        if context.object.sprytile_gridid != SprytileGui.current_grid:
            # Setup the offscreen texture for the new grid
            setup_off_return = SprytileGui.setup_offscreen(self, context)
            if setup_off_return is not None:
                return setup_off_return
            # Skip redrawing on this frame
            return {'PASS_THROUGH'}

        self.handle_ui(context, event)
        context.scene.sprytile_ui.is_dirty = False
        context.area.tag_redraw()
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            if context.scene.sprytile_data.is_running is False:
                return {'CANCELLED'}
            if len(context.scene.sprytile_grids) < 1:
                return {'CANCELLED'}

            # Try to setup offscreen
            setup_off_return = SprytileGui.setup_offscreen(self, context)
            if setup_off_return is not None:
                return setup_off_return

            context.scene.sprytile_ui.zoom = 1.0
            self.handle_ui(context, event)

            SprytileGui.handler_add(self, context)
            if context.area:
                context.area.tag_redraw()
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            return {'CANCELLED'}

    def handle_ui(self, context, event):
        if event.type in {'LEFTMOUSE', 'MOUSEMOVE'}:
            self.mouse_pt = Vector((event.mouse_region_x, event.mouse_region_y))

        mouse_pt = self.mouse_pt

        region = context.region
        obj = context.object

        grids = context.scene.sprytile_grids
        tilegrid = grids[obj.sprytile_gridid]
        tex_size = SprytileGui.tex_size

        display_scale = context.scene.sprytile_ui.zoom
        display_size = SprytileGui.display_size
        display_size = round(display_size[0] * display_scale), round(display_size[1] * display_scale)
        display_pad = 5

        gui_min = Vector((region.width - (int(display_size[0]) + display_pad), display_pad))
        gui_max = Vector((region.width - display_pad, (int(display_size[1]) + display_pad)))

        self.gui_min = gui_min
        self.gui_max = gui_max

        reject_region = context.space_data.type != 'VIEW_3D' or region.type != 'WINDOW'
        if event is None or reject_region:
            return

        change_cursor = False

        if mouse_pt is not None and event.type in {'MOUSEMOVE'}:
            mouse_in_region = 0 <= mouse_pt.x <= region.width and 0 <= mouse_pt.y <= region.height
            mouse_in_gui = gui_min.x <= mouse_pt.x <= gui_max.x and gui_min.y <= mouse_pt.y <= gui_max.y

            context.scene.sprytile_ui.use_mouse = mouse_in_gui

            if mouse_in_gui:
                context.window.cursor_modal_set('DEFAULT')
            elif mouse_in_region:
                change_cursor = True
            else:
                context.window.cursor_modal_restore()

        if change_cursor or context.scene.sprytile_ui.is_dirty:
            is_snapping = context.scene.sprytile_data.is_snapping
            cursor_data = 'PAINT_BRUSH' if not is_snapping else 'CROSSHAIR'
            if event.alt:
                cursor_data = 'EYEDROPPER'
            context.window.cursor_modal_set(cursor_data)

        if context.scene.sprytile_ui.use_mouse is False:
            return

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            new_scale = display_scale
            new_scale += 0.2 if event.type == 'WHEELUPMOUSE' else -0.2
            calc_size = [
                (display_size[0] * new_scale),
                (display_size[1] * new_scale)
            ]
            if calc_size[0] < 64 or calc_size[1] < 64:
                new_scale = max(64.0 / display_size[0], 64.0 / display_size[1])
            context.scene.sprytile_ui.zoom = new_scale

        if mouse_pt is not None and event.type in {'LEFTMOUSE', 'MOUSEMOVE'}:
            click_pos = Vector((mouse_pt.x - gui_min.x, mouse_pt.y - gui_min.y))
            ratio_pos = Vector((click_pos.x / display_size[0], click_pos.y / display_size[1]))
            tex_pos = Vector((ratio_pos.x * tex_size[0], ratio_pos.y * tex_size[1]))
            # Inverse matrix tex_pos
            grid_pos = Vector((tex_pos.x / tilegrid.grid[0], tex_pos.y / tilegrid.grid[1]))
            grid_pos.x = floor(grid_pos.x)
            grid_pos.y = floor(grid_pos.y)
            SprytileGui.cursor_grid_pos = grid_pos

            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                tilegrid.tile_selection[0] = grid_pos.x
                tilegrid.tile_selection[1] = grid_pos.y

        # Cycle through grids on same material when right click
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            bpy.ops.sprytile.grid_cycle()

    # ==================
    # Actual GUI drawing
    # ==================
    @staticmethod
    def setup_offscreen(self, context):
        SprytileGui.offscreen = SprytileGui.setup_gpu_offscreen(self, context)
        if SprytileGui.offscreen:
            SprytileGui.texture = SprytileGui.offscreen.color_texture
        else:
            self.report({'ERROR'}, "Error initializing offscreen buffer. More details in the console")
            return {'CANCELLED'}
        return None

    @staticmethod
    def setup_gpu_offscreen(self, context):
        import gpu
        scene = context.scene
        obj = context.object

        grid_id = obj.sprytile_gridid

        # Get the current tile grid, to fetch the texture size to render to
        tilegrid = scene.sprytile_grids[grid_id]
        tex_size = 128, 128
        target_img = sprytile_utils.get_grid_texture(obj, tilegrid)
        # Couldn't get the texture outta here
        if target_img is not None:
            tex_size = target_img.size[0], target_img.size[1]

        import gpu
        try:
            offscreen = gpu.offscreen.new(tex_size[0], tex_size[1])
        except Exception as e:
            print(e)
            SprytileGui.clear_offscreen(self)
            offscreen = None

        SprytileGui.texture_grid = target_img
        SprytileGui.tex_size = tex_size
        SprytileGui.display_size = tex_size
        SprytileGui.current_grid = grid_id
        SprytileGui.loaded_grid = tilegrid
        return offscreen

    @staticmethod
    def clear_offscreen(self):
        SprytileGui.texture = None

    @staticmethod
    def handler_add(self, context):
        SprytileGui.draw_callback = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_handler, (self, context),
                                                                           'WINDOW', 'POST_PIXEL')

    @staticmethod
    def handler_remove(self, context):
        context.window.cursor_modal_restore()
        if SprytileGui.draw_callback is not None:
            bpy.types.SpaceView3D.draw_handler_remove(SprytileGui.draw_callback, 'WINDOW')
        SprytileGui.draw_callback = None

    @staticmethod
    def draw_callback_handler(self, context):
        """Callback handler"""
        SprytileGui.draw_offscreen(self, context)
        SprytileGui.draw_to_viewport(self.gui_min, self.gui_max)

    @staticmethod
    def draw_offscreen(self, context):
        """Draw the GUI into the offscreen texture"""
        offscreen = SprytileGui.offscreen
        target_img = SprytileGui.texture_grid
        tex_size = SprytileGui.tex_size

        offscreen.bind()
        glClear(GL_COLOR_BUFFER_BIT)
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluOrtho2D(0, tex_size[0], 0, tex_size[1])

        def draw_full_quad():
            texco = [(0, 0), (0, 1), (1, 1), (1, 0)]
            verco = [(0, 0), (0, tex_size[1]), (tex_size[0], tex_size[1]), (tex_size[0], 0)]
            glBegin(bgl.GL_QUADS)
            # first draw the texture
            for i in range(4):
                glTexCoord2f(texco[i][0], texco[i][1])
                glVertex2f(verco[i][0], verco[i][1])
            glEnd()

        glColor4f(0.0, 0.0, 0.0, 0.5)
        draw_full_quad()

        if target_img is not None:
            glColor4f(1.0, 1.0, 1.0, 1.0)
            target_img.gl_load(0, GL_NEAREST, GL_NEAREST)
            glBindTexture(GL_TEXTURE_2D, target_img.bindcode[0])
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glEnable(GL_TEXTURE_2D)
            draw_full_quad()

        # Translate the gl context by grid matrix
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glDisable(GL_TEXTURE_2D)
        glLineWidth(2)

        def draw_selection(min, max):
            sel_vtx = [
                (min[0], min[1]),
                (max[0], min[1]),
                (max[0], max[1]),
                (min[0], max[1])
            ]
            glBegin(GL_LINE_STRIP)
            for vtx in sel_vtx:
                glVertex2f(vtx[0], vtx[1])
            glVertex2f(sel_vtx[0][0], sel_vtx[0][1])
            glEnd()

        # Draw box for currently selected tile(s)
        grid_size = SprytileGui.loaded_grid.grid
        curr_sel = SprytileGui.loaded_grid.tile_selection
        curr_sel_min = (grid_size[0] * curr_sel[0]), (grid_size[1] * curr_sel[1])
        curr_sel_max = [
            (curr_sel_min[0] + grid_size[0] * curr_sel[2]),
            (curr_sel_min[1] + grid_size[1] * curr_sel[3])
        ]
        draw_selection(curr_sel_min, curr_sel_max)

        # Inside gui, draw box for tile under mouse
        if context.scene.sprytile_ui.use_mouse is True:
            glColor4f(1.0, 0.0, 0.0, 1.0)
            glLineWidth(1)
            cursor_pos = SprytileGui.cursor_grid_pos
            cursor_min = int(cursor_pos.x * grid_size[0]), int(cursor_pos.y * grid_size[1])
            cursor_max = [
                cursor_min[0] + grid_size[0],
                cursor_min[1] + grid_size[1],
            ]
            draw_selection(cursor_min, cursor_max)

        offscreen.unbind()

    @staticmethod
    def draw_to_viewport(min, max):
        """Draw the offscreen texture into the viewport"""
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, SprytileGui.texture)
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, bgl.GL_NEAREST)
        bgl.glEnable(bgl.GL_TEXTURE_2D)
        bgl.glEnable(bgl.GL_BLEND)

        bgl.glColor4f(1.0, 1.0, 1.0, 1.0)
        bgl.glBegin(bgl.GL_QUADS)

        uv = [(0, 0), (0, 1), (1, 1), (1, 0)]
        vtx = [(min.x, min.y), (min.x, max.y), (max.x, max.y), (max.x, min.y)]
        for i in range(4):
            glTexCoord2f(uv[i][0], uv[i][1])
            glVertex2f(vtx[i][0], vtx[i][1])

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
