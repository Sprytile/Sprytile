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

class SprytileGridAdd(bpy.types.Operator):
    bl_idname = "sprytile.grid_add"
    bl_label = "Add New Grid"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        if event is not None:
            self.add_new_grid(context)
        return {'FINISHED'}

    def add_new_grid(self, context):
        grid_array = context.scene.sprytile_grids
        if len(grid_array) < 1:
            return
        grid_idx = context.object.sprytile_gridid
        selected_grid = grid_array[grid_idx]

        new_idx = len(grid_array)
        new_grid = grid_array.add()
        new_grid.mat_id = selected_grid.mat_id
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

    def delete_grid(self, context):
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
        if has_main == True:
            return
        # Mark the first grid that references material as main
        for grid in grid_array:
            if grid.mat_id != del_mat_id:
                continue
            grid.is_main = True
            break

class SprytileNewMaterial(bpy.types.Operator):
    bl_idname = "sprytile.add_new_material"
    bl_label = "Create New Material"

class SprytileValidateGridList(bpy.types.Operator):
    bl_idname = "sprytile.validate_grids"
    bl_label = "Validate Material Grids"

    @classmethod
    def poll(cls,context):
        return True

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.validate_grids(context)
        return {'FINISHED'}

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

        # Loop through grids again, making sure each material
        # has one main material

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
