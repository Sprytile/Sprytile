import bpy
from bpy.types import Panel, UIList

class SprytileMaterialGridList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """
        """
        if isinstance(item.mat_id, str) is False:
            layout.label("Invalid Material")
        elif bpy.data.materials.find(item.mat_id) == -1:
            layout.label("Invalid Material")
        elif self.layout_type in {'DEFAULT', 'COMPACT'}:
            material = bpy.data.materials[item.mat_id]
            split = layout.split(0.6)
            split.prop(material, "name", text="", emboss=False, icon_value=layout.icon(material))
            split.label("%dx%d" % (item.grid[0], item.grid[1]))
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
        row = layout.row(align=True)
        row.prop(context.scene.sprytile_data, "normal_mode", expand=True)
        row.prop(context.scene.sprytile_data, "lock_normal", toggle=True)

        layout.template_list("SprytileMaterialGridList", "", scene, "sprytile_grids", obj, "sprytile_gridid", rows=2)

        if len(scene.sprytile_grids) == 0:
            return

        selected_grid = scene.sprytile_grids[obj.sprytile_gridid]

        layout.label("Grid Settings", icon='GRID')

        layout.prop(selected_grid, "grid")
        layout.prop(selected_grid, "offset")

def register():
    bpy.utils.register_module(__name__)

def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
