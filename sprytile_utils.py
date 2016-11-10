import bpy
from mathutils import Matrix, Vector
from bpy.types import Panel

def GetGridMatrix(srpytile_grid):
    """Returns the transform matrix of a sprytile grid"""

class SprytileValidateGridList(bpy.types.Operator):
    bl_idname = "sprytile.validate_grids"
    bl_label = "Validate Material Grids"

    @classmethod
    def poll(cls,context):
        return True

    def validate_grids(self, context):
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
            if is_mat_valid == False:
                grid_setting = grids.add()
                grid_setting.mat_id = mat.name
                grid_setting.is_main = True

    def execute(self, context):
        self.validate_grids(context)
        return self.invoke(context, None)

    def invoke(self, context, event):
        if event is not None:
            self.validate_grids(context)
        return {'FINISHED'}

class SprytileWorkflowPanel(bpy.types.Panel):
    bl_label = "Workflow"
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
        layout.prop(context.scene.sprytile_data, "world_pixels")
        layout.prop(context.scene.sprytile_data, "cursor_snap", expand=True)

def register():
    bpy.utils.register_module(__name__)

def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
