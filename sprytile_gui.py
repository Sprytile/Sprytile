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


class SprytileGui(bpy.types.Operator):
    bl_idname = "sprytile.gui_win"
    bl_label = "Sprytile GUI"

    mouse_pt = None
    label_frames = 50
    is_selecting = False
    is_moving = False
    sel_start = None
    sel_origin = None

    # ================
    # Modal functions
    # ================
    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        if context.space_data.type != 'VIEW_3D':
            return {'CANCELLED'}
        if context.scene.sprytile_data.is_running is False:
            return {'CANCELLED'}
        if len(context.scene.sprytile_mats) < 1:
            return {'CANCELLED'}

        # Try to setup offscreen
        setup_off_return = SprytileGui.setup_offscreen(self, context)
        if setup_off_return is not None:
            return setup_off_return

        self.label_counter = 0
        self.get_zoom_level(context)
        self.prev_in_region = False
        self.handle_ui(context, event)

        # Add the draw handler call back, for drawing into viewport
        SprytileGui.handler_add(self, context, context.region)

        if context.area:
            context.area.tag_redraw()
        context.scene.sprytile_ui.is_dirty = True
        # Add actual modal handler
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.scene.sprytile_data.is_running is False:
            self.exit(context)
            return {'CANCELLED'}

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
            return {'PASS_THROUGH'}

        self.handle_ui(context, event)
        context.scene.sprytile_ui.is_dirty = False
        context.area.tag_redraw()
        return {'PASS_THROUGH'}

    def exit(self, context):
        SprytileGui.handler_remove(self, context)
        context.area.tag_redraw()

    def set_zoom_level(self, context, zoom_shift):
        region = context.region
        zoom_level = context.scene.sprytile_ui.zoom
        zoom_level = self.calc_zoom(region, zoom_level, zoom_shift)
        display_size = SprytileGui.display_size

        calc_size = round(display_size[0] * zoom_level), round(display_size[1] * zoom_level)
        height_min = min(128, display_size[1])
        while calc_size[1] < height_min:
            zoom_level = self.calc_zoom(region, zoom_level, 1)
            calc_size = round(display_size[0] * zoom_level), round(display_size[1] * zoom_level)

        while calc_size[0] > region.width or calc_size[1] > region.height:
            zoom_level = self.calc_zoom(region, zoom_level, -1)
            calc_size = round(display_size[0] * zoom_level), round(display_size[1] * zoom_level)

        context.scene.sprytile_ui.zoom = zoom_level

    def calc_zoom(self, region, zoom, steps):
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

        if SprytileGui.display_size[1] > region.height:
            zoom = min(region.height / SprytileGui.display_size[1], zoom)

        return zoom

    def get_zoom_level(self, context):
        region = context.region
        display_size = SprytileGui.display_size
        target_height = region.height * 0.35

        zoom_level = round(region.height / display_size[1])

        if zoom_level <= 0:
            zoom_level = self.calc_zoom(region, 1, -1)

        calc_height = round(display_size[1] * zoom_level)
        while calc_height > target_height:
            zoom_level = self.calc_zoom(region, zoom_level, -1)
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

                addon_prefs = context.user_preferences.addons[__package__].preferences
                if addon_prefs.tile_picker_key == 'Alt' and event.alt:
                    cursor_data = 'EYEDROPPER'
                if addon_prefs.tile_picker_key == 'Ctrl' and event.ctrl:
                    cursor_data = 'EYEDROPPER'
                if addon_prefs.tile_picker_key == 'Shift' and event.shift:
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
            cell_size = Vector((
                tilegrid.grid[0] + (tilegrid.padding[0] * 2) + tilegrid.margin[1] + tilegrid.margin[3],
                tilegrid.grid[1] + (tilegrid.padding[1] * 2) + tilegrid.margin[0] + tilegrid.margin[2]
            ))
            grid_pos = Vector((tex_pos.x / cell_size.x, tex_pos.y / cell_size.y))
            grid_pos.x = max(0, min(grid_max.x, floor(grid_pos.x)))
            grid_pos.y = max(0, min(grid_max.y, floor(grid_pos.y)))

            SprytileGui.cursor_grid_pos = grid_pos

            if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and SprytileGui.is_selecting is False:
                addon_prefs = context.user_preferences.addons[__package__].preferences
                move_mod_pressed = False
                if addon_prefs.tile_sel_move_key == 'Alt':
                    move_mod_pressed = event.alt
                if addon_prefs.tile_sel_move_key == 'Ctrl':
                    move_mod_pressed = event.ctrl
                if addon_prefs.tile_sel_move_key == 'Shift':
                    move_mod_pressed = event.shift

                SprytileGui.is_selecting = move_mod_pressed is False
                SprytileGui.is_moving = move_mod_pressed is True
                if SprytileGui.is_selecting or SprytileGui.is_moving:
                    SprytileGui.sel_start = grid_pos
                    SprytileGui.sel_origin = (tilegrid.tile_selection[0], tilegrid.tile_selection[1])

            if SprytileGui.is_moving:
                move_delta = Vector((grid_pos.x - SprytileGui.sel_start.x, grid_pos.y - SprytileGui.sel_start.y))
                # Restrict movement inside tile grid
                move_min = (SprytileGui.sel_origin[0] + move_delta.x,
                            SprytileGui.sel_origin[1] + move_delta.y)
                if move_min[0] < 0:
                    move_delta.x -= move_min[0]
                if move_min[1] < 0:
                    move_delta.y -= move_min[1]

                move_max = (move_min[0] + tilegrid.tile_selection[2] - 1,
                            move_min[1] + tilegrid.tile_selection[3] - 1)
                if move_max[0] > grid_max.x:
                    move_delta.x -= (move_max[0] - grid_max.x)
                if move_max[1] > grid_max.y:
                    move_delta.y -= (move_max[1] - grid_max.y)

                tilegrid.tile_selection[0] = SprytileGui.sel_origin[0] + move_delta.x
                tilegrid.tile_selection[1] = SprytileGui.sel_origin[1] + move_delta.y

            if SprytileGui.is_selecting:
                sel_min = Vector((
                    min(grid_pos.x, SprytileGui.sel_start.x),
                    min(grid_pos.y, SprytileGui.sel_start.y)
                ))
                sel_max = Vector((
                    max(grid_pos.x, SprytileGui.sel_start.x),
                    max(grid_pos.y, SprytileGui.sel_start.y)
                ))

                tilegrid.tile_selection[0] = sel_min.x
                tilegrid.tile_selection[1] = sel_min.y
                tilegrid.tile_selection[2] = (sel_max.x - sel_min.x) + 1
                tilegrid.tile_selection[3] = (sel_max.y - sel_min.y) + 1

            do_release = event.type == 'LEFTMOUSE' and event.value == 'RELEASE'
            if do_release and (SprytileGui.is_selecting or SprytileGui.is_moving):
                SprytileGui.is_selecting = False
                SprytileGui.is_moving = False
                SprytileGui.sel_start = None
                SprytileGui.sel_origin = None

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
            offscreen = gpu.offscreen.new(tex_size[0], tex_size[1], samples=0)
        except Exception as e:
            print(e)
            SprytileGui.clear_offscreen(self)
            offscreen = None

        SprytileGui.texture_grid = target_img
        SprytileGui.tex_size = tex_size
        SprytileGui.display_size = tex_size
        SprytileGui.current_grid = grid_id
        SprytileGui.loaded_grid = tilegrid
        self.get_zoom_level(context)
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

        SprytileGui.draw_offscreen(context)
        SprytileGui.draw_to_viewport(self.gui_min, self.gui_max, show_extra,
                                     self.label_counter, tilegrid, sprytile_data,
                                     context.scene.cursor_location, region, rv3d,
                                     middle_btn, context)

    @staticmethod
    def draw_selection(sel_min, sel_max, adjust=1):
        sel_vtx = [
            (sel_min[0] + adjust, sel_min[1] + adjust),
            (sel_max[0], sel_min[1]),
            (sel_max[0], sel_max[1]),
            (sel_min[0], sel_max[1])
        ]
        glBegin(GL_LINE_STRIP)
        for vtx in sel_vtx:
            glVertex2i(vtx[0], vtx[1])
        glVertex2i(sel_vtx[0][0], sel_vtx[0][1] - adjust)
        glEnd()

    @staticmethod
    def draw_offscreen(context):
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

        # Get data for drawing additional overlays
        grid_size = SprytileGui.loaded_grid.grid
        padding = SprytileGui.loaded_grid.padding
        margin = SprytileGui.loaded_grid.margin
        curr_sel = SprytileGui.loaded_grid.tile_selection
        is_pixel_grid = sprytile_utils.grid_is_single_pixel(SprytileGui.loaded_grid)
        is_use_mouse = context.scene.sprytile_ui.use_mouse
        is_selecting = SprytileGui.is_selecting

        glLineWidth(1)

        # Draw box for currently selected tile(s)
        # Pixel grid selection is drawn in draw_tile_select_ui
        sprytile_data = context.scene.sprytile_data
        is_not_base_layer = sprytile_data.work_layer != "BASE"
        draw_outline = sprytile_data.outline_preview or is_not_base_layer
        if draw_outline and is_selecting is False and not is_pixel_grid:
            if is_not_base_layer:
                glColor4f(0.98, 0.94, 0.12, 1.0)
            elif SprytileGui.is_moving:
                glColor4f(1.0, 0.0, 0.0, 1.0)
            else:
                glColor4f(1.0, 1.0, 1.0, 1.0)
            curr_sel_min, curr_sel_max = SprytileGui.get_sel_bounds(
                                                    grid_size, padding, margin,
                                                    curr_sel[0], curr_sel[1],
                                                    curr_sel[2], curr_sel[3]
                                                )
            SprytileGui.draw_selection(curr_sel_min, curr_sel_max)

        # Inside gui, draw appropriate selection for under mouse
        if is_use_mouse and is_selecting is False and SprytileGui.cursor_grid_pos is not None:

            cursor_pos = SprytileGui.cursor_grid_pos
            # In pixel grid, draw cross hair
            if is_pixel_grid and SprytileGui.is_moving is False:
                glColor4f(1.0, 1.0, 1.0, 0.5)
                glBegin(GL_LINE_STRIP)
                glVertex2i(0, int(cursor_pos.y + 1))
                glVertex2i(tex_size[0], int(cursor_pos.y + 1))
                glEnd()

                glBegin(GL_LINE_STRIP)
                glVertex2i(int(cursor_pos.x + 1), 0)
                glVertex2i(int(cursor_pos.x + 1), tex_size[1])
                glEnd()
            # Draw box around selection
            elif SprytileGui.is_moving is False:
                glColor4f(1.0, 0.0, 0.0, 1.0)
                cursor_min, cursor_max = SprytileGui.get_sel_bounds(grid_size, padding, margin,
                                                                    int(cursor_pos.x), int(cursor_pos.y),)
                SprytileGui.draw_selection(cursor_min, cursor_max)

        glPopMatrix()
        offscreen.unbind()

    @staticmethod
    def get_sel_bounds(grid_size, padding, margin, x, y, size_x=1, size_y=1):
        total_size = Vector(
            (
                grid_size[0] + (padding[0]*2) + margin[1] + margin[3],
                grid_size[1] + (padding[1]*2) + margin[0] + margin[2]
             )
        )
        sel_min = [
            int(total_size[0]) * x,
            int(total_size[1]) * y
        ]
        sel_max = [
            sel_min[0] + total_size[0] * size_x,
            sel_min[1] + total_size[1] * size_y
        ]
        sel_min[0] += padding[0] + margin[3]
        sel_min[1] += padding[1] + margin[0]
        sel_max[0] -= padding[0] + margin[1]
        sel_max[1] -= padding[1] + margin[2]
        sel_min = int(sel_min[0]), int(sel_min[1])
        sel_max = int(sel_max[0]), int(sel_max[1])
        return sel_min, sel_max

    @staticmethod
    def draw_work_plane(grid_size, sprytile_data, cursor_loc, region, rv3d, middle_btn):
        display_grid = (grid_size[0], grid_size[1])
        # For single pixel grids, use world pixel density
        if grid_size[0] == 1 or grid_size[1] == 1:
            display_grid = (
                SprytileGui.loaded_grid.tile_selection[2],
                SprytileGui.loaded_grid.tile_selection[3]
            )
        if display_grid[0] == 1 or display_grid[1] == 1:
            return

        force_draw = sprytile_data.paint_mode == 'FILL' or sprytile_data.lock_normal
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

        pixel_unit = 1 / sprytile_data.world_pixels
        paint_up_vector = paint_up_vector * pixel_unit * display_grid[1]
        paint_right_vector = paint_right_vector * pixel_unit * display_grid[0]

        plane_size = sprytile_data.axis_plane_size
        if sprytile_data.paint_mode == "FILL":
            plane_size = sprytile_data.fill_plane_size

        grid_min, grid_max = sprytile_utils.get_workplane_area(plane_size[0], plane_size[1])

        def draw_world_line(world_start, world_end):
            start = view3d_utils.location_3d_to_region_2d(region, rv3d, world_start)
            end = view3d_utils.location_3d_to_region_2d(region, rv3d, world_end)
            if start is None or end is None:
                return
            glBegin(GL_LINES)
            glVertex2f(start.x, start.y)
            glVertex2f(end.x, end.y)
            glEnd()

        plane_col = sprytile_data.axis_plane_color
        glColor4f(plane_col[0], plane_col[1], plane_col[2], 1)
        glLineWidth(2)

        for x in range(grid_min[0] + 1, grid_max[0]):
            draw_start = cursor_loc + (paint_right_vector * x) + (paint_up_vector * grid_min[1])
            draw_end = draw_start + paint_up_vector * plane_size[1]
            draw_world_line(draw_start, draw_end)
        for y in range(grid_min[1] + 1, grid_max[1]):
            draw_start = cursor_loc + (paint_right_vector * grid_min[0]) + (paint_up_vector * y)
            draw_end = draw_start + paint_right_vector * plane_size[0]
            draw_world_line(draw_start, draw_end)

        x_offset_min = paint_right_vector * grid_min[0]
        x_offset_max = paint_right_vector * grid_max[0]
        y_offset_min = paint_up_vector * grid_min[1]
        y_offset_max = paint_up_vector * grid_max[1]

        p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor_loc + x_offset_min + y_offset_min)
        p1 = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor_loc + x_offset_min + y_offset_max)
        p2 = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor_loc + x_offset_max + y_offset_max)
        p3 = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor_loc + x_offset_max + y_offset_min)

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
    def draw_tile_select_ui(view_min, view_max, view_size,
                            tex_size, grid_size, tile_selection,
                            padding, margin, show_extra, is_pixel):
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
        
        # Translate the gl context by grid matrix
        scale_factor = (view_size[0] / tex_size[0], view_size[1] / tex_size[1])

        # Setup to draw grid into viewport
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

        glLineWidth(1)

        # Draw tileset grid, if not pixel size and show extra is on
        if show_extra and is_pixel is False:
            glColor4f(0.0, 0.0, 0.0, 0.5)
            # Draw the grid
            cell_size = (
                grid_size[0] + padding[0] * 2 + margin[1] + margin[3],
                grid_size[1] + padding[1] * 2 + margin[0] + margin[2]
            )
            x_divs = ceil(tex_size[0] / cell_size[0])
            y_divs = ceil(tex_size[1] / cell_size[1])
            x_end = x_divs * cell_size[0]
            y_end = y_divs * cell_size[1]
            for x in range(x_divs + 1):
                x_pos = (x * cell_size[0])
                glBegin(GL_LINES)
                glVertex2f(x_pos, 0)
                glVertex2f(x_pos, y_end)
                glEnd()
            for y in range(y_divs + 1):
                y_pos = (y * cell_size[1])
                glBegin(GL_LINES)
                glVertex2f(0, y_pos)
                glVertex2f(x_end, y_pos)
                glEnd()

        # Draw selected tile outline
        sel_min, sel_max = SprytileGui.get_sel_bounds(grid_size, padding, margin,
                                                      tile_selection[0], tile_selection[1],
                                                      tile_selection[2], tile_selection[3])
        glColor4f(1.0, 1.0, 1.0, 1.0)
        SprytileGui.draw_selection(sel_min, sel_max, 0)

        glPopMatrix()

    @staticmethod
    def draw_preview_tile(context, region, rv3d):
        if sprytile_modal.SprytileModalTool.no_undo is True:
            return
        if sprytile_modal.SprytileModalTool.preview_verts is None:
            return
        if sprytile_modal.SprytileModalTool.preview_uvs is None:
            return

        uv = sprytile_modal.SprytileModalTool.preview_uvs
        world_verts = sprytile_modal.SprytileModalTool.preview_verts
        is_quads = sprytile_modal.SprytileModalTool.preview_is_quads

        # Turn the world vert positions into screen positions
        screen_verts = []
        for world_vtx in world_verts:
            screen_vtx = view3d_utils.location_3d_to_region_2d(region, rv3d, world_vtx)
            if screen_vtx is None:
                return
            screen_verts.append(screen_vtx)

        addon_prefs = context.user_preferences.addons[__package__].preferences
        preview_alpha = addon_prefs.preview_transparency
        sprytile_data = context.scene.sprytile_data

        if sprytile_data.has_selection:
            preview_alpha *= 0.25
        if sprytile_data.paint_mode == 'PAINT':
            preview_alpha = 0.9

        bgl.glColor4f(1.0, 1.0, 1.0, preview_alpha)

        # paint preview only draws one polygon
        if not is_quads:
            bgl.glBegin(bgl.GL_POLYGON)

        for i in range(len(uv)):
            mod = i % 4

            # Per tile polygon preview, begin and end every four verts
            if is_quads and mod == 0:
                bgl.glBegin(bgl.GL_POLYGON)

            glTexCoord2f(uv[i].x, uv[i].y)
            glVertex2f(screen_verts[i][0], screen_verts[i][1])

            if is_quads and mod == 3:
                bgl.glEnd()

        if not is_quads:
            bgl.glEnd()

    @staticmethod
    def draw_to_viewport(view_min, view_max, show_extra, label_counter, tilegrid, sprytile_data,
                         cursor_loc, region, rv3d, middle_btn, context):
        """Draw the offscreen texture into the viewport"""

        # Prepare some data that will be used for drawing
        grid_size = SprytileGui.loaded_grid.grid
        tile_sel = SprytileGui.loaded_grid.tile_selection
        padding = SprytileGui.loaded_grid.padding
        margin = SprytileGui.loaded_grid.margin
        is_pixel = sprytile_utils.grid_is_single_pixel(SprytileGui.loaded_grid)

        # Draw work plane
        SprytileGui.draw_work_plane(grid_size, sprytile_data, cursor_loc, region, rv3d, middle_btn)

        # Setup GL for drawing the offscreen texture
        bgl.glColor4f(1.0, 1.0, 1.0, 1.0)
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, SprytileGui.texture)
        # Backup texture settings
        old_mag_filter = Buffer(bgl.GL_INT, 1)
        glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, old_mag_filter)

        old_wrap_S = Buffer(GL_INT, 1)
        old_wrap_T = Buffer(GL_INT, 1)

        glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, old_wrap_S)
        glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, old_wrap_T)

        # Set texture filter
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, bgl.GL_NEAREST)
        bgl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        bgl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        bgl.glEnable(bgl.GL_TEXTURE_2D)
        bgl.glEnable(bgl.GL_BLEND)

        # Draw the preview tile
        if middle_btn is False:
            SprytileGui.draw_preview_tile(context, region, rv3d)

        # Calculate actual view size
        view_size = int(view_max.x - view_min.x), int(view_max.y - view_min.y)

        # Save the original scissor box, and then set new scissor setting
        scissor_box = bgl.Buffer(bgl.GL_INT, [4])
        bgl.glGetIntegerv(bgl.GL_SCISSOR_BOX, scissor_box)
        bgl.glScissor(int(view_min.x) + scissor_box[0], int(view_min.y) + scissor_box[1], view_size[0], view_size[1])

        # Draw the tile select UI
        SprytileGui.draw_tile_select_ui(view_min, view_max, view_size, SprytileGui.tex_size,
                                        grid_size, tile_sel, padding, margin, show_extra, is_pixel)

        # restore opengl defaults
        bgl.glScissor(scissor_box[0], scissor_box[1], scissor_box[2], scissor_box[3])
        bgl.glLineWidth(1)
        bgl.glTexParameteriv(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, old_mag_filter)
        bgl.glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, old_wrap_S)
        bgl.glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, old_wrap_T)

        # Draw label
        font_id = 0
        font_size = 16
        pad = 5
        if label_counter > 0:
            import math

            def ease_out_circ(t, b, c, d):
                t /= d
                t -= 1
                return c * math.sqrt(1 - t * t) + b
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
        if tilegrid.grid[0] == 1 and tilegrid.grid[1] == 1:
            size_text = "%dx%d" % (tile_sel[2], tile_sel[3])
            blf.size(font_id, font_size, 72)
            size = blf.dimensions(font_id, size_text)
            x_pos = view_max.x - size[0] - pad
            y_pos = view_max.y + pad
            blf.position(font_id, x_pos, y_pos, 0)
            blf.draw(font_id, size_text)

        bgl.glDisable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_TEXTURE_2D)
        bgl.glColor4f(0.0, 0.0, 0.0, 1.0)


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()
