import bpy
from bpy.types import Panel, UIList

class SprytileValidateGridList(bpy.types.Operator):
    bl_idname = "sprytile.validate_grids"
    bl_label = "Sprytile Validate Grids"

    @classmethod
    def poll(cls,context):
        return True

    def execute(self, context):
        """
        """
        grids = context.scene.sprytile_grids
        grids.clear()
        mats_valid = []
        print("Material count: %d" % len(bpy.data.materials))
        # Loop through available materials, checking if grids has
        # at least one entry with the id
        for mat_id, mat in enumerate(bpy.data.materials):
            is_mat_valid = False
            for grid in grids:
                if grid.mat_id == mat_id:
                    is_mat_valid = True
                    break
            mats_valid.append(is_mat_valid)

        # Check the mats valid list and add a new grid for any invalid setting
        for mat_id, mat_valid in enumerate(mats_valid):
            if mat_valid is True:
                continue
            grid_setting = grids.add()
            grid_setting.mat_id = mat_id
            grid_setting.is_main = True

        # Remove any grids with invalid material ids
        invalid_id = []
        mat_size = len(bpy.data.materials)
        for idx, grid in enumerate(grids):
            if grid.mat_id >= mat_size:
                invalid_id.append(idx)
                print("Remove index ", idx)
        invalid_id.reverse()
        for idx in invalid_id:
            grids.remove(idx)

        print(context.scene.sprytile_grids)

        return self.invoke(context, None)

    def invoke(self, context, event):
        return {'FINISHED'}

class SprytileMaterialGridList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """
        """
        if item.mat_id >= len(bpy.data.materials):
            layout.label("Invalid Material")
        elif self.layout_type in {'DEFAULT', 'COMPACT'}:
            material = bpy.data.materials[item.mat_id]
            split = layout.split(0.6)
            split.prop(material, "name", text="", emboss=False)
            split.label("%dx%d" % (item.grid_x, item.grid_y))
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class SprytilePanel(bpy.types.Panel):
    bl_label = "Sprytile Painter"
    bl_idname = "sprytile.panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Sprytile"

    # Only show panel when selected object is a mesh and in edit mode
    @classmethod
    def poll(self, context):
        if context.object and context.object.type == 'MESH':
            return context.object.mode == 'EDIT'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.object

        layout.operator("sprytile.modal_tool", icon='BRUSH_DATA')

        layout.prop(context.scene.sprytile_data, "paint_mode", expand=True)

        layout.label("Face Normal")
        row = layout.row(align=True)
        row.prop(context.scene.sprytile_data, "normal_mode", expand=True)
        row.prop(context.scene.sprytile_data, "lock_normal", toggle=True)

        layout.prop(context.scene.sprytile_data, "world_pixels")

        layout.label("Select Material", icon='MATERIAL_DATA')
        layout.template_list("SprytileMaterialGridList", "", scene, "sprytile_grids", obj, "sprytile_gridid", rows=3)

        if obj.sprytile_gridid in {None, -1}:
            return

        selected_grid = scene.sprytile_grids[obj.sprytile_gridid]

        layout.label("Grid Settings", icon='GRID')
        row = layout.row(align=True)
        row.prop(selected_grid, "grid_x")
        row.prop(selected_grid, "grid_y")

        layout.prop(selected_grid, "offset")

class SprytileWorkflowPanel(bpy.types.Panel):
    bl_label = "Sprytile Workflow"
    bl_idname = "sprytile.panel_workflow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Sprytile"

    @classmethod
    def poll(self, context):
        if context.object and context.object.type == 'MESH':
            return context.object.mode == 'EDIT'

    def draw(self, context):
        layout = self.layout
        layout.operator("sprytile.validate_grids")

def register():
    bpy.utils.register_module(__name__)

def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
