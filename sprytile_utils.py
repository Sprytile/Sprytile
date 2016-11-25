import bpy
import bgl
import blf
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace
from mathutils import Matrix, Vector
from . import sprytile_modal


def get_grid_matrix(sprytile_grid):
    """Returns the transform matrix of a sprytile grid"""
    offset_mtx = Matrix.Translation((sprytile_grid.offset[0], sprytile_grid.offset[1], 0))
    rotate_mtx = Matrix.Rotation(sprytile_grid.rotate, 4, 'Z')
    return offset_mtx * rotate_mtx


def get_grid_texture(obj, sprytile_grid):
    mat_idx = obj.material_slots.find(sprytile_grid.mat_id)
    if mat_idx == -1:
        return None
    material = obj.material_slots[mat_idx].material
    if material is None:
        return None
    target_img = None
    for texture_slot in material.texture_slots:
        if texture_slot is None:
            continue
        if texture_slot.texture is None:
            continue
        if texture_slot.texture.type == 'NONE':
            continue
        if texture_slot.texture.type == 'IMAGE':
            # Cannot use the texture slot image reference directly
            # Have to get it through bpy.data.images to be able to use with BGL
            target_img = bpy.data.images.get(texture_slot.texture.image.name)
            break
    return target_img


class SprytileGridAdd(bpy.types.Operator):
    bl_idname = "sprytile.grid_add"
    bl_label = "Add New Grid"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.add_new_grid(context)
        return {'FINISHED'}

    @staticmethod
    def add_new_grid(context):
        grid_array = context.scene.sprytile_grids
        if len(grid_array) < 1:
            return
        grid_idx = context.object.sprytile_gridid
        selected_grid = grid_array[grid_idx]

        new_idx = len(grid_array)
        new_grid = grid_array.add()
        new_grid.mat_id = selected_grid.mat_id
        new_grid.grid = selected_grid.grid
        new_grid.is_main = False

        grid_array.move(new_idx, grid_idx + 1)


class SprytileGridRemove(bpy.types.Operator):
    bl_idname = "sprytile.grid_remove"
    bl_label = "Remove Grid"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.delete_grid(context)
        return {'FINISHED'}

    @staticmethod
    def delete_grid(context):
        grid_array = context.scene.sprytile_grids
        if len(grid_array) <= 1:
            return
        grid_idx = context.object.sprytile_gridid

        del_grid = grid_array[grid_idx]
        del_mat_id = del_grid.mat_id

        # Check the grid array has
        has_main = False
        grid_count = 0
        for idx, grid in enumerate(grid_array.values()):
            if grid.mat_id != del_mat_id:
                continue
            if idx == grid_idx:
                continue
            grid_count += 1
            if grid.is_main:
                has_main = True

        # No grid will be left referencing the material
        # Don't allow deletion
        if grid_count < 1:
            return

        grid_array.remove(grid_idx)
        context.object.sprytile_gridid -= 1
        # A main grid is left, exit
        if has_main:
            return
        # Mark the first grid that references material as main
        for grid in grid_array:
            if grid.mat_id != del_mat_id:
                continue
            grid.is_main = True
            break


class SprytileGridCycle(bpy.types.Operator):
    bl_idname = "sprytile.grid_cycle"
    bl_label = "Cycle grid settings"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.cycle_grid(context)
        return {'FINISHED'}

    @staticmethod
    def cycle_grid(context):
        obj = context.object
        grids = context.scene.sprytile_grids
        curr_grid_idx = obj.sprytile_gridid
        curr_mat_id = grids[curr_grid_idx].mat_id
        next_grid_idx = curr_grid_idx + 1
        if next_grid_idx < len(grids):
            if grids[next_grid_idx].mat_id == curr_mat_id:
                obj.sprytile_gridid = next_grid_idx
        else:
            for grid_idx, check_grid in enumerate(grids):
                if check_grid.mat_id == curr_mat_id:
                    obj.sprytile_gridid = grid_idx
                    break


class SprytileNewMaterial(bpy.types.Operator):
    bl_idname = "sprytile.add_new_material"
    bl_label = "New Shadeless Material"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def invoke(self, context, event):
        obj = context.object

        mat = bpy.data.materials.new(name="Material")
        mat.use_shadeless = True
        mat.use_transparency = True
        mat.transparency_method = 'MASK'
        mat.alpha = 0.0

        set_idx = len(obj.data.materials)
        obj.data.materials.append(mat)
        obj.active_material_index = set_idx

        bpy.ops.sprytile.validate_grids()
        return {'FINISHED'}


class SprytileValidateGridList(bpy.types.Operator):
    bl_idname = "sprytile.validate_grids"
    bl_label = "Validate Material Grids"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.validate_grids(context)
        return {'FINISHED'}

    @staticmethod
    def validate_grids(context):
        curr_sel = context.object.sprytile_gridid
        grids = context.scene.sprytile_grids
        mat_list = bpy.data.materials
        remove_idx = []
        print("Material count: %d" % len(bpy.data.materials))

        # Filter out grids with invalid IDs or users
        for idx, grid in enumerate(grids.values()):
            mat_idx = mat_list.find(grid.mat_id)
            if mat_idx < 0:
                remove_idx.append(idx)
                continue
            if mat_list[mat_idx].users == 0:
                remove_idx.append(idx)
        remove_idx.reverse()
        for idx in remove_idx:
            grids.remove(idx)

        # Loop through available materials, checking if grids has
        # at least one entry with the name
        for mat in mat_list:
            if mat.users == 0:
                continue
            is_mat_valid = False
            for grid in grids:
                if grid.mat_id == mat.name:
                    is_mat_valid = True
                    break
            # No grid found for this material, add new one
            if is_mat_valid is False:
                grid_setting = grids.add()
                grid_setting.mat_id = mat.name
                grid_setting.is_main = True

        grids_count = len(grids)
        if curr_sel >= grids_count:
            context.object.sprytile_gridid = grids_count-1


class SprytileRotateLeft(bpy.types.Operator):
    bl_idname = "sprytile.rotate_left"
    bl_label = "Rotate Sprytile Left"

    def invoke(self, context, event):
        curr_rotation = context.scene.sprytile_data.mesh_rotate
        curr_rotation -= 1.5708
        if curr_rotation < -6.28319:
            curr_rotation = -1.5708
        context.scene.sprytile_data.mesh_rotate = curr_rotation
        return {'FINISHED'}


class SprytileRotateRight(bpy.types.Operator):
    bl_idname = "sprytile.rotate_right"
    bl_label = "Rotate Sprytile Right"

    def invoke(self, context, event):
        curr_rotation = context.scene.sprytile_data.mesh_rotate
        curr_rotation += 1.5708
        if curr_rotation > 6.28319:
            curr_rotation = 1.5708
        context.scene.sprytile_data.mesh_rotate = curr_rotation
        return {'FINISHED'}


class SprytileReloadImages(bpy.types.Operator):
    bl_idname = "sprytile.reload_imgs"
    bl_label = "Reload All Images"

    def invoke(self, context, event):
        for img in bpy.data.images:
            if img is None:
                continue
            img.reload()
        return {'FINISHED'}


class SprytileGridTranslate(bpy.types.Operator):
    bl_idname = "sprytile.translate_grid"
    bl_label = "Sprytile Pixel Translate"

    @staticmethod
    def draw_callback(self, context):
        if self.exec_counter != -1 or self.ref_pos is None:
            return None

        check_pos = self.get_ref_pos(context)
        measure_vec = check_pos - self.ref_pos
        pixel_unit = 1 / context.scene.sprytile_data.world_pixels
        for i in range(3):
            measure_vec[i] = int(round(measure_vec[i] / pixel_unit))

        screen_y = context.region.height - 45
        screen_x = 20
        padding = 5

        font_id = 0
        font_size = 16
        blf.size(font_id, font_size, 72)

        bgl.glColor4f(1, 1, 1, 1)

        readout_axis = ['X', 'Y', 'Z']
        for i in range(3):
            blf.position(font_id, screen_x, screen_y, 0)
            blf.draw(font_id, "%s : %d" % (readout_axis[i], measure_vec[i]))
            screen_y -= font_size + padding

    def modal(self, context, event):
        # User cancelled transform
        if event.type == 'ESC':
            return self.exit_modal(context)
        if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            return self.exit_modal(context)
        # On the timer events, count down the frames and execute the
        # translate operator when reach 0
        if event.type == 'TIMER':
            if self.exec_counter > 0:
                self.exec_counter -= 1

            if self.exec_counter == 0:
                self.exec_counter -= 1
                up_vec, right_vec, norm_vec = sprytile_modal.get_current_grid_vectors(context.scene)
                norm_vec = sprytile_modal.snap_vector_to_axis(norm_vec)
                axis_constraint = [
                    abs(norm_vec.x) == 0,
                    abs(norm_vec.y) == 0,
                    abs(norm_vec.z) == 0
                ]
                tool_value = bpy.ops.transform.translate(
                    'INVOKE_DEFAULT',
                    constraint_axis=axis_constraint,
                    snap=self.restore_settings is not None
                )
                # Translate tool moved nothing, exit
                if 'CANCELLED' in tool_value:
                    return self.exit_modal(context)

        # When the active operator changes, we know that translate has been completed
        if context.active_operator != self.watch_operator:
            return self.exit_modal(context)

        return {'PASS_THROUGH'}

    def get_ref_pos(self, context):
        if self.bmesh is None:
            self.bmesh = bmesh.from_edit_mesh(context.object.data)

        target = self.bmesh.select_history.active
        if isinstance(target, BMFace):
            return target.calc_center_median()
        if isinstance(target, BMEdge):
            return target.verts[0].co.copy()
        if isinstance(target, BMVert):
            return target.co.copy()
        return None

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        # When this tool is invoked, change the grid settings so that snapping
        # is on pixel unit steps. Save settings to restore later
        self.restore_settings = None
        space_data = context.space_data
        if space_data.type == 'VIEW_3D':
            self.restore_settings = {
                "grid_scale": space_data.grid_scale,
                "grid_sub": space_data.grid_subdivisions,
                "show_floor": space_data.show_floor,
                "pivot": context.space_data.pivot_point,
                "orient": context.space_data.transform_orientation,
                "snap_element": context.scene.tool_settings.snap_element
            }
            pixel_unit = 1 / context.scene.sprytile_data.world_pixels
            space_data.grid_scale = pixel_unit
            space_data.grid_subdivisions = 1
            space_data.show_floor = False
            space_data.pivot_point = 'CURSOR'
            space_data.transform_orientation = 'GLOBAL'
            context.scene.tool_settings.snap_element = 'INCREMENT'
        # Remember what the current active operator is, when it changes
        # we know that the translate operator is complete
        self.watch_operator = context.active_operator

        # Countdown the frames passed through the timer. For some reason
        # the translate tool will not use the new grid scale if we switch
        # over immediately to translate.
        self.exec_counter = 2

        # Save the bmesh, and reference position
        self.bmesh = None
        self.ref_pos = self.get_ref_pos(context)

        args = self, context
        self.draw_handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, args, 'WINDOW', 'POST_PIXEL')

        win_mgr = context.window_manager
        self.timer = win_mgr.event_timer_add(0.1, context.window)
        win_mgr.modal_handler_add(self)
        # Now go up to modal function to read the rest
        return {'RUNNING_MODAL'}

    def exit_modal(self, context):
        # Restore grid settings if changed
        if self.restore_settings is not None:
            context.space_data.grid_scale = self.restore_settings['grid_scale']
            context.space_data.grid_subdivisions = self.restore_settings['grid_sub']
            context.space_data.show_floor = self.restore_settings['show_floor']
            context.space_data.pivot_point = self.restore_settings['pivot']
            context.space_data.transform_orientation = self.restore_settings['orient']
            context.scene.tool_settings.snap_element = self.restore_settings['snap_element']
        # Didn't snap to grid, force to grid by calculating what the snapped translate would be
        else:
            op = context.active_operator
            if op is not None and op.bl_idname == 'TRANSFORM_OT_translate':
                pixel_unit = 1 / context.scene.sprytile_data.world_pixels
                # Take the translated value and snap it to pixel units
                translation = op.properties.value.copy()
                for i in range(3):
                    translation[i] = int(round(translation[i] / pixel_unit))
                    translation[i] *= pixel_unit
                # Move selection to where snapped position would be
                offset = translation - op.properties.value
                bpy.ops.transform.translate(value=offset)

        self.bmesh = None
        bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle, 'WINDOW')
        context.window_manager.event_timer_remove(self.timer)
        return {'FINISHED'}


class SprytileWorkflowPanel(bpy.types.Panel):
    bl_label = "Workflow"
    bl_idname = "sprytile.panel_workflow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Sprytile"

    @classmethod
    def poll(cls, context):
        if context.object and context.object.type == 'MESH':
            return context.object.mode == 'EDIT'

    def draw(self, context):
        layout = self.layout
        data = context.scene.sprytile_data

        row = layout.row(align=True)
        row.prop(data, "uv_flip_x", toggle=True)
        row.prop(data, "uv_flip_y", toggle=True)

        row = layout.row(align=True)
        row.operator("sprytile.rotate_left", icon="TRIA_DOWN", text="")
        row.prop(data, "mesh_rotate")
        row.operator("sprytile.rotate_right", icon="TRIA_UP", text="")

        row = layout.row(align=False)
        row.label("", icon="SNAP_ON")
        row.prop(data, "cursor_snap", expand=True)

        row = layout.row(align=False)
        row.label("", icon="CURSOR")
        row.prop(data, "cursor_flow", toggle=True)

        layout.prop(data, "world_pixels")
        layout.operator("sprytile.reload_imgs")


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()
