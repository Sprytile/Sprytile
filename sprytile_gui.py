import bpy
import bgl
import blf
from math import floor, ceil
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
            if len(context.scene.sprytile_mats) < 1:
                return {'CANCELLED'}

            # Try to setup offscreen
            setup_off_return = SprytileGui.setup_offscreen(self, context)
            if setup_off_return is not None:
                return setup_off_return

            context.scene.sprytile_ui.zoom = 1.0
            self.prev_in_region = False
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

        tilegrid = sprytile_utils.get_grid(context, obj.sprytile_gridid)
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

        if mouse_pt is not None and event.type in {'MOUSEMOVE'}:
            mouse_in_region = 0 <= mouse_pt.x <= region.width and 0 <= mouse_pt.y <= region.height
            mouse_in_gui = gui_min.x <= mouse_pt.x <= gui_max.x and gui_min.y <= mouse_pt.y <= gui_max.y

            context.scene.sprytile_ui.use_mouse = mouse_in_gui

            if mouse_in_gui:
                context.window.cursor_modal_set('DEFAULT')
            elif mouse_in_region or context.scene.sprytile_ui.is_dirty:
                is_snapping = context.scene.sprytile_data.is_snapping
                cursor_data = 'PAINT_BRUSH' if not is_snapping else 'CROSSHAIR'
                if context.scene.sprytile_data.paint_mode == 'MAKE_FACE':
                    cursor_data = 'KNIFE'
                if event.alt:
                    cursor_data = 'EYEDROPPER'
                context.window.cursor_modal_set(cursor_data)

            if not mouse_in_region and self.prev_in_region:
                context.window.cursor_modal_restore()
            self.prev_in_region = mouse_in_region

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
            tex_pos = Vector((ratio_pos.x * tex_size[0], ratio_pos.y * tex_size[1], 0))
            # Apply grid matrix to tex_pos
            grid_matrix = sprytile_utils.get_grid_matrix(SprytileGui.loaded_grid)
            tex_pos = grid_matrix.inverted() * tex_pos

            grid_max = Vector((ceil(tex_size[0]/tilegrid.grid[0])-1, ceil(tex_size[1]/tilegrid.grid[1])-1))
            grid_pos = Vector((tex_pos.x / tilegrid.grid[0], tex_pos.y / tilegrid.grid[1]))
            grid_pos.x = max(0, min(grid_max.x, floor(grid_pos.x)))
            grid_pos.y = max(0, min(grid_max.y, floor(grid_pos.y)))

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
        obj = context.object

        grid_id = obj.sprytile_gridid

        # Get the current tile grid, to fetch the texture size to render to
        tilegrid = sprytile_utils.get_grid(context, grid_id)
        target_img = None

        tex_size = 128, 128
        if tilegrid is not None:
            target_img = sprytile_utils.get_grid_texture(obj, tilegrid)
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
        sprytile_data = context.scene.sprytile_data
        show_extra = sprytile_data.show_extra or sprytile_data.show_overlay

        SprytileGui.draw_offscreen(self, context)
        SprytileGui.draw_to_viewport(self.gui_min, self.gui_max, show_extra)

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
            # first draw the texture
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glEnable(GL_TEXTURE_2D)
            draw_full_quad()

        # Translate the gl context by grid matrix
        grid_matrix = sprytile_utils.get_grid_matrix(SprytileGui.loaded_grid)
        matrix_vals = [grid_matrix[j][i] for i in range(4) for j in range(4)]
        grid_buff = bgl.Buffer(bgl.GL_FLOAT, 16, matrix_vals)

        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glLoadMatrixf(grid_buff)

        glDisable(GL_TEXTURE_2D)

        def draw_selection(min, max):
            sel_vtx = [
                (min[0] + 1, min[1] + 1),
                (max[0], min[1]),
                (max[0], max[1]),
                (min[0], max[1])
            ]
            glBegin(GL_LINE_STRIP)
            for vtx in sel_vtx:
                glVertex2i(vtx[0], vtx[1])
            glVertex2i(sel_vtx[0][0], sel_vtx[0][1] - 1)
            glEnd()

        glColor4f(1.0, 1.0, 1.0, 1.0)
        glLineWidth(1)
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
            cursor_pos = SprytileGui.cursor_grid_pos
            cursor_min = int(cursor_pos.x * grid_size[0]), int(cursor_pos.y * grid_size[1])
            cursor_max = [
                cursor_min[0] + grid_size[0],
                cursor_min[1] + grid_size[1],
                ]
            draw_selection(cursor_min, cursor_max)

        glPopMatrix()
        offscreen.unbind()

    @staticmethod
    def draw_to_viewport(min, max, show_extra):
        """Draw the offscreen texture into the viewport"""
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, SprytileGui.texture)
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, bgl.GL_NEAREST)
        bgl.glEnable(bgl.GL_TEXTURE_2D)
        bgl.glEnable(bgl.GL_BLEND)

        # Save the original scissor box, and then set new scissor setting
        scissor_box = bgl.Buffer(bgl.GL_INT, [4])
        bgl.glGetIntegerv(bgl.GL_SCISSOR_BOX, scissor_box)
        view_size = int(max.x - min.x), int(max.y - min.y)
        bgl.glScissor(int(min.x) + scissor_box[0], int(min.y) + scissor_box[1], view_size[0], view_size[1])

        bgl.glColor4f(1.0, 1.0, 1.0, 1.0)
        # Draw the texture in first
        bgl.glBegin(bgl.GL_QUADS)
        uv = [(0, 0), (0, 1), (1, 1), (1, 0)]
        # vtx = [(0, 0), (0, view_size[1]), view_size, (view_size[0], 0)]
        vtx = [(min.x, min.y), (min.x, max.y), (max.x, max.y), (max.x, min.y)]
        for i in range(4):
            glTexCoord2f(uv[i][0], uv[i][1])
            glVertex2f(vtx[i][0], vtx[i][1])
        bgl.glEnd()

        if show_extra:
            # Draw the tile grid overlay

            # Translate the gl context by grid matrix
            tex_size = SprytileGui.tex_size
            scale_factor = view_size[0] / tex_size[1]

            offset_matrix = Matrix.Translation((min.x, min.y, 0))
            grid_matrix = sprytile_utils.get_grid_matrix(SprytileGui.loaded_grid)
            grid_matrix = Matrix.Scale(scale_factor, 4) * grid_matrix
            calc_matrix = offset_matrix * grid_matrix
            matrix_vals = [calc_matrix[j][i] for i in range(4) for j in range(4)]
            grid_buff = bgl.Buffer(bgl.GL_FLOAT, 16, matrix_vals)
            glPushMatrix()
            glLoadIdentity()
            glLoadMatrixf(grid_buff)
            glDisable(GL_TEXTURE_2D)

            glColor4f(0.0, 0.0, 0.0, 0.5)
            glLineWidth(1)
            # Draw the grid
            grid_size = SprytileGui.loaded_grid.grid
            x_divs = ceil(tex_size[0] / grid_size[0])
            y_divs = ceil(tex_size[1] / grid_size[1])
            # x_size = (grid_size[0] / tex_size[0]) * (max.x - min.x)
            # y_size = (grid_size[1] / tex_size[1]) * (max.y - min.y)
            x_end = x_divs * grid_size[0]
            y_end = y_divs * grid_size[1]
            for x in range(x_divs + 1):
                x_pos = (x * grid_size[0])
                glBegin(GL_LINES)
                glVertex2f(x_pos, 0)
                glVertex2f(x_pos, y_end)
                glEnd()
            for y in range(y_divs + 1):
                y_pos = (y * grid_size[1])
                glBegin(GL_LINES)
                glVertex2f(0, y_pos)
                glVertex2f(x_end, y_pos)
                glEnd()

            glPopMatrix()

        # restore opengl defaults
        bgl.glScissor(scissor_box[0], scissor_box[1], scissor_box[2], scissor_box[3])
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
