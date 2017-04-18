import bpy
import bgl
import blf
from bpy_extras import view3d_utils
from math import floor, ceil, copysign
from bgl import *
from bpy.props import *
from mathutils import Vector, Matrix
from . import sprytile_utils, sprytile_modal


class SprytileGuiData(bpy.types.PropertyGroup):
    zoom = FloatProperty(
        name="Sprytile UI zoom",
        default=1.0
    )
    use_mouse = BoolProperty(name="GUI use mouse")
    middle_btn = BoolProperty(name="GUI middle mouse")
    is_dirty = BoolProperty(name="Srpytile GUI redraw flag")


class SprytileGui:
    bl_idname = "sprytile.gui_win"
    bl_label = "Sprytile GUI"

    mouse_pt = None
    label_frames = 50

    def __init__(self, context, event):
        self.did_setup = False

        if context.space_data.type != 'VIEW_3D':
            return
        if context.scene.sprytile_data.is_running is False:
            return
        if len(context.scene.sprytile_mats) < 1:
            return

        # Try to setup offscreen
        setup_off_return = SprytileGui.setup_offscreen(self, context)
        if setup_off_return is not None:
            return

        # Initial setup of variables
        self.did_setup = True
        self.get_zoom_level(context)
        self.prev_in_region = False
        self.handle_ui(context, event)
        self.label_counter = 0
        self.gui_min = Vector((0, 0))
        self.gui_max = Vector((0, 0))

        context.scene.sprytile_ui.is_dirty = True

        # Add the draw handler call back, for drawing into viewport
        SprytileGui.handler_add(self, context, context.region)

    def modal(self, context, event):
        if self.did_setup is False:
            return

        if event.type == 'TIMER':
            if self.label_counter > 0:
                self.label_counter -= 1

        # Check if current_grid is different from current sprytile grid
        if context.object.sprytile_gridid != SprytileGui.current_grid:
            # Setup the offscreen texture for the new grid
            setup_off_return = SprytileGui.setup_offscreen(self, context)
            if setup_off_return is not None:
                return setup_off_return
            # Skip redrawing on this frame
            return

        self.handle_ui(context, event)
        context.scene.sprytile_ui.is_dirty = False
        context.area.tag_redraw()

    def exit(self, context):
        SprytileGui.handler_remove(self, context)
        context.area.tag_redraw()

    def set_zoom_level(self, context, zoom_shift):
        region = context.region
        zoom_level = context.scene.sprytile_ui.zoom
        zoom_level = self.calc_zoom(zoom_level, zoom_shift)
        display_size = SprytileGui.display_size

        calc_size = round(display_size[0] * zoom_level), round(display_size[1] * zoom_level)
        height_min = min(128, display_size[1])
        while calc_size[1] < height_min:
            zoom_level = self.calc_zoom(zoom_level, 1)
            calc_size = round(display_size[0] * zoom_level), round(display_size[1] * zoom_level)

        while calc_size[0] > region.width or calc_size[1] > region.height:
            zoom_level = self.calc_zoom(zoom_level, -1)
            calc_size = round(display_size[0] * zoom_level), round(display_size[1] * zoom_level)

        context.scene.sprytile_ui.zoom = zoom_level

    def calc_zoom(self, zoom, steps):
        if steps == 0:
            return zoom
        step = copysign(1, steps)
        count = 0
        while count != steps:
            # Zooming in
            if steps > 0:
                if zoom >= 2.0:
                    zoom += 0.5
                elif zoom >= 0.25:
                    zoom += 0.25
                else:
                    zoom *= 2
            # Zooming out
            else:
                if zoom <= 0.25:
                    zoom *= 0.5
                elif zoom <= 2.0:
                    zoom -= 0.25
                else:
                    zoom -= 0.5
            count += step
        return zoom

    def get_zoom_level(self, context):
        region = context.region
        display_size = SprytileGui.display_size
        target_height = region.height * 0.35

        zoom_level = round(region.height / display_size[1])
        calc_height = round(display_size[1] * zoom_level)
        while calc_height > target_height:
            zoom_level = self.calc_zoom(zoom_level, -1)
            calc_height = round(display_size[1] * zoom_level)

        context.scene.sprytile_ui.zoom = zoom_level

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

        if event.type == 'MIDDLEMOUSE':
            context.scene.sprytile_ui.middle_btn = True
        if context.scene.sprytile_ui.middle_btn and event.value == 'RELEASE':
            context.scene.sprytile_ui.middle_btn = False

        if mouse_pt is not None and event.type in {'MOUSEMOVE'}:
            mouse_in_region = 0 <= mouse_pt.x <= region.width and 0 <= mouse_pt.y <= region.height
            mouse_in_gui = gui_min.x <= mouse_pt.x <= gui_max.x and gui_min.y <= mouse_pt.y <= gui_max.y

            context.scene.sprytile_ui.use_mouse = mouse_in_gui

            if mouse_in_gui:
                context.window.cursor_modal_restore()
            elif mouse_in_region or context.scene.sprytile_ui.is_dirty:
                is_snapping = context.scene.sprytile_data.is_snapping
                cursor_data = 'PAINT_BRUSH' if not is_snapping else 'CROSSHAIR'
                paint_mode = context.scene.sprytile_data.paint_mode
                if paint_mode == 'MAKE_FACE':
                    cursor_data = 'KNIFE'
                elif paint_mode == 'SET_NORMAL':
                    cursor_data = 'CROSSHAIR'
                elif paint_mode == 'FILL':
                    cursor_data = 'SCROLL_XY'
                if event.alt:
                    cursor_data = 'EYEDROPPER'
                context.window.cursor_modal_set(cursor_data)

            if not mouse_in_region and self.prev_in_region:
                context.window.cursor_modal_restore()
            self.prev_in_region = mouse_in_region

        if context.scene.sprytile_ui.use_mouse is False:
            return

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            if event.ctrl is False:
                zoom_shift = 1 if event.type == 'WHEELUPMOUSE' else -1
                self.set_zoom_level(context, zoom_shift)
            else:
                direction = 1 if 'DOWN' in event.type else -1
                bpy.ops.sprytile.grid_cycle('INVOKE_REGION_WIN', direction=direction)
                self.label_counter = SprytileGui.label_frames

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
            self.label_counter = SprytileGui.label_frames

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
    def handler_add(self, context, region):
        space = bpy.types.SpaceView3D
        SprytileGui.draw_callback = space.draw_handler_add(self.draw_callback_handler,
                                                           (self, context, region),
                                                           'WINDOW', 'POST_PIXEL')

    @staticmethod
    def handler_remove(self, context):
        context.window.cursor_modal_restore()
        if hasattr(SprytileGui, "draw_callback") and SprytileGui.draw_callback is not None:
            bpy.types.SpaceView3D.draw_handler_remove(SprytileGui.draw_callback, 'WINDOW')
        SprytileGui.draw_callback = None

    @staticmethod
    def draw_callback_handler(self, context, region):
        """Callback handler"""
        if region.id is not context.region.id:
            return
        sprytile_data = context.scene.sprytile_data
        if sprytile_data.is_running is False:
            return
        show_extra = sprytile_data.show_extra or sprytile_data.show_overlay
        tilegrid = sprytile_utils.get_selected_grid(context)

        region = context.region
        rv3d = context.region_data

        middle_btn = context.scene.sprytile_ui.middle_btn

        SprytileGui.draw_offscreen(self, context)
        SprytileGui.draw_to_viewport(self.gui_min, self.gui_max, show_extra,
                                     self.label_counter, tilegrid, sprytile_data,
                                     context.scene.cursor_location, region, rv3d,
                                     middle_btn, context)

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
            # We need to backup and restore the MAG_FILTER to avoid messing up the Blender viewport
            old_mag_filter = Buffer(GL_INT, 1)
            glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, old_mag_filter)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glEnable(GL_TEXTURE_2D)
            draw_full_quad()
            glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, old_mag_filter)

        # Translate the gl context by grid matrix
        grid_matrix = sprytile_utils.get_grid_matrix(SprytileGui.loaded_grid)
        matrix_vals = [grid_matrix[j][i] for i in range(4) for j in range(4)]
        grid_buff = bgl.Buffer(bgl.GL_FLOAT, 16, matrix_vals)

        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glLoadMatrixf(grid_buff)

        glDisable(GL_TEXTURE_2D)

        def draw_selection(sel_min, sel_max):
            sel_vtx = [
                (sel_min[0] + 1, sel_min[1] + 1),
                (sel_max[0], sel_min[1]),
                (sel_max[0], sel_max[1]),
                (sel_min[0], sel_max[1])
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
    def draw_work_plane(grid_size, sprytile_data, cursor_loc, region, rv3d, middle_btn):
        force_draw = sprytile_data.paint_mode == 'FILL'
        # Decide if should draw, only draw if middle mouse?
        if force_draw is False:
            if sprytile_data.axis_plane_display == 'OFF':
                return
            if sprytile_data.axis_plane_display == 'MIDDLE_MOUSE':
                if middle_btn is False and sprytile_data.is_snapping is False:
                    return

        # First, draw the world grid size overlay
        paint_up_vector = sprytile_data.paint_up_vector
        paint_right_vector = sprytile_data.paint_normal_vector.cross(paint_up_vector)

        indicator_x = sprytile_data.axis_plane_size[0]
        indicator_y = sprytile_data.axis_plane_size[1]

        pixel_unit = 1 / sprytile_data.world_pixels
        paint_up_vector = paint_up_vector * pixel_unit * grid_size[1]
        paint_right_vector = paint_right_vector * pixel_unit * grid_size[0]

        x_min = cursor_loc - paint_right_vector * indicator_x
        x_max = cursor_loc + paint_right_vector * indicator_x

        y_min = cursor_loc - paint_up_vector * indicator_y
        y_max = cursor_loc + paint_up_vector * indicator_y

        def draw_world_line(world_start, world_end):
            start = view3d_utils.location_3d_to_region_2d(region, rv3d, world_start)
            end = view3d_utils.location_3d_to_region_2d(region, rv3d, world_end)
            if start is None or end is None:
                return
            glBegin(GL_LINES)
            glVertex2f(start.x, start.y)
            glVertex2f(end.x, end.y)
            glEnd()

        def draw_interior_grid(start_loc, x_vec, y_vec, size_x, size_y):
            for x_dir in [-1, 1]:
                for grid_x in range(1, size_x):
                    start_pos = start_loc + (x_vec * x_dir * grid_x)
                    end_pos = start_pos + y_vec * size_y * 2
                    draw_world_line(start_pos, end_pos)

        plane_col = sprytile_data.axis_plane_color
        glColor4f(plane_col[0], plane_col[1], plane_col[2], 1)
        glLineWidth(2)

        draw_interior_grid(y_min, paint_right_vector, paint_up_vector, indicator_x, indicator_y)
        draw_interior_grid(x_min, paint_up_vector, paint_right_vector, indicator_y, indicator_x)
        # Origin lines
        draw_world_line(x_min, x_max)
        draw_world_line(y_min, y_max)

        paint_right_vector *= sprytile_data.axis_plane_size[0]
        paint_up_vector *= sprytile_data.axis_plane_size[1]

        p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor_loc - paint_right_vector - paint_up_vector)
        p1 = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor_loc - paint_right_vector + paint_up_vector)
        p2 = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor_loc + paint_right_vector + paint_up_vector)
        p3 = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor_loc + paint_right_vector - paint_up_vector)

        if p0 is None or p1 is None or p2 is None or p3 is None:
            return

        glBegin(GL_LINE_STRIP)
        glVertex2f(p0.x, p0.y)
        glVertex2f(p1.x, p1.y)
        glVertex2f(p2.x, p2.y)
        glVertex2f(p3.x, p3.y)
        glVertex2f(p0.x, p0.y)
        glEnd()

    @staticmethod
    def draw_tile_select_ui(view_min, view_max, view_size, tex_size, grid_size, show_extra):
        # Draw the texture quad
        bgl.glColor4f(1.0, 1.0, 1.0, 1.0)
        bgl.glBegin(bgl.GL_QUADS)
        uv = [(0, 0), (0, 1), (1, 1), (1, 0)]
        vtx = [(view_min.x, view_min.y), (view_min.x, view_max.y),
               (view_max.x, view_max.y), (view_max.x, view_min.y)]
        for i in range(4):
            glTexCoord2f(uv[i][0], uv[i][1])
            glVertex2f(vtx[i][0], vtx[i][1])
        bgl.glEnd()

        # Not drawing tile grid overlay
        if show_extra is False:
            return

        # Translate the gl context by grid matrix
        scale_factor = (view_size[0] / tex_size[0], view_size[1] / tex_size[1])

        offset_matrix = Matrix.Translation((view_min.x, view_min.y, 0))
        grid_matrix = sprytile_utils.get_grid_matrix(SprytileGui.loaded_grid)
        grid_matrix = Matrix.Scale(scale_factor[0], 4, Vector((1, 0, 0))) * Matrix.Scale(scale_factor[1], 4, Vector((0, 1, 0))) * grid_matrix
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
        x_divs = ceil(tex_size[0] / grid_size[0])
        y_divs = ceil(tex_size[1] / grid_size[1])
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

    @staticmethod
    def draw_preview_tile(sprytile_data, context, tilegrid, region, rv3d):
        if sprytile_modal.SprytileModalTool.world_verts is None:
            return
        if context.scene.sprytile_ui.use_mouse:
            return

        bgl.glColor4f(1.0, 1.0, 1.0, 0.6)
        bgl.glBegin(bgl.GL_QUADS)
        uv = [(0, 0), (0, 1), (1, 1), (1, 0)]
        world_verts = sprytile_modal.SprytileModalTool.world_verts
        screen_verts = []
        for world_vtx in world_verts:
            screen_verts.append(view3d_utils.location_3d_to_region_2d(region, rv3d, world_vtx))
        for i in range(4):
            glTexCoord2f(uv[i][0], uv[i][1])
            glVertex2f(screen_verts[i][0], screen_verts[i][1])
        bgl.glEnd()

    @staticmethod
    def draw_to_viewport(view_min, view_max, show_extra, label_counter, tilegrid, sprytile_data,
                         cursor_loc, region, rv3d, middle_btn, context):
        """Draw the offscreen texture into the viewport"""

        # Prepare some data that will be used for drawing
        grid_size = SprytileGui.loaded_grid.grid

        # Draw work plane
        SprytileGui.draw_work_plane(grid_size, sprytile_data, cursor_loc, region, rv3d, middle_btn)

        # Setup GL for drawing the offscreen texture
        bgl.glColor4f(1.0, 1.0, 1.0, 1.0)
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, SprytileGui.texture)
        # Backup texture filter
        old_mag_filter = Buffer(bgl.GL_INT, [1])
        bgl.glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, old_mag_filter)
        # Set texture filter
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, bgl.GL_NEAREST)
        bgl.glEnable(bgl.GL_TEXTURE_2D)
        bgl.glEnable(bgl.GL_BLEND)

        # Draw the preview tile
        # if middle_btn is False:
        #     SprytileGui.draw_preview_tile(sprytile_data, context, tilegrid, region, rv3d)

        # Calculate actual view size
        view_size = int(view_max.x - view_min.x), int(view_max.y - view_min.y)

        # Save the original scissor box, and then set new scissor setting
        scissor_box = bgl.Buffer(bgl.GL_INT, [4])
        bgl.glGetIntegerv(bgl.GL_SCISSOR_BOX, scissor_box)
        bgl.glScissor(int(view_min.x) + scissor_box[0], int(view_min.y) + scissor_box[1], view_size[0], view_size[1])

        # Draw the tile select UI
        SprytileGui.draw_tile_select_ui(view_min, view_max, view_size, SprytileGui.tex_size, grid_size, show_extra)

        # restore opengl defaults
        bgl.glScissor(scissor_box[0], scissor_box[1], scissor_box[2], scissor_box[3])
        bgl.glLineWidth(1)
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, old_mag_filter[0])

        # Draw label
        if label_counter > 0:
            import math

            def ease_out_circ(t, b, c, d):
                t /= d
                t -= 1
                return c * math.sqrt(1 - t * t) + b

            font_id = 0
            font_size = 16
            pad = 5
            box_pad = font_size + (pad * 2)
            fade = label_counter
            fade = ease_out_circ(fade, 0, SprytileGui.label_frames, SprytileGui.label_frames)
            fade /= SprytileGui.label_frames

            bgl.glColor4f(0.0, 0.0, 0.0, 0.75 * fade)
            bgl.glBegin(bgl.GL_QUADS)
            uv = [(0, 0), (0, 1), (1, 1), (1, 0)]
            vtx = [(view_min.x, view_max.y), (view_min.x, view_max.y + box_pad), (view_max.x, view_max.y + +box_pad), (view_max.x, view_max.y)]
            for i in range(4):
                glTexCoord2f(uv[i][0], uv[i][1])
                glVertex2f(vtx[i][0], vtx[i][1])
            bgl.glEnd()

            bgl.glColor4f(1.0, 1.0, 1.0, 1.0 * fade)
            blf.size(font_id, font_size, 72)

            x_pos = view_min.x + pad
            y_pos = view_max.y + pad

            label_string = "%dx%d" % (tilegrid.grid[0], tilegrid.grid[1])
            if tilegrid.name != "":
                label_string = "%s - %s" % (label_string, tilegrid.name)
            blf.position(font_id, x_pos, y_pos, 0)
            blf.draw(font_id, label_string)

        bgl.glDisable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_TEXTURE_2D)
        bgl.glColor4f(0.0, 0.0, 0.0, 1.0)


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()
