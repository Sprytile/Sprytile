import bpy
from mathutils import Matrix, Vector
from bpy.types import Panel

def GetGridMatrix(srpytile_grid):
    """Returns the transform matrix of a sprytile grid"""

def get_grid_texture(sprytile_grid):
    mat_idx = bpy.data.materials.find(sprytile_grid.mat_id)
    if mat_idx == -1:
        return None
    material = bpy.data.materials[mat_idx]
    target_img = None
    for texture_slot in material.texture_slots:
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
    return target_img

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

        row = layout.row(align=False)
        row.label("", icon="SNAP_ON")
        row.prop(context.scene.sprytile_data, "cursor_snap", expand=True)

        row = layout.row(align=False)
        row.label("", icon="CURSOR")
        row.prop(context.scene.sprytile_data, "cursor_flow", toggle=True)

        layout.prop(context.scene.sprytile_data, "world_pixels")

def register():
    bpy.utils.register_module(__name__)

def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
