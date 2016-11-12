import bpy
from . import sprytile_utils
from bpy.types import Panel, UIList

class SprytileMaterialGridList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if isinstance(item.mat_id, str) is False:
            layout.label("Invalid Material")
        elif bpy.data.materials.find(item.mat_id) == -1:
            layout.label("Invalid Material")
        elif self.layout_type in {'DEFAULT', 'COMPACT'}:
            split = layout.split(0.6)
            if item.is_main:
                material = bpy.data.materials[item.mat_id]
                grid_tex = sprytile_utils.get_grid_texture(context.object, item)
                if grid_tex is None:
                    grid_tex = material
                split.prop(material, "name", text="", emboss=False, icon_value=layout.icon(grid_tex))
            else:
                split.label("")
            split.label("%dx%d" % (item.grid[0], item.grid[1]))
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class SprytileGridDropDown(bpy.types.Menu):
    bl_idname = "SPRYTILE_grid_drop"
    bl_label = "Grid drop down"
    def draw(self, context):
        layout = self.layout
        layout.operator("sprytile.add_new_material", icon="NEW")
        layout.operator("sprytile.validate_grids", icon="GRID")

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

        row = layout.row()

        row.template_list("SprytileMaterialGridList", "", scene, "sprytile_grids", obj, "sprytile_gridid", rows=2)

        col = row.column(align=True)
        col.operator("sprytile.grid_add", icon='ZOOMIN', text="")
        col.operator("sprytile.grid_remove", icon='ZOOMOUT', text="")
        col.menu("SPRYTILE_grid_drop", icon='DOWNARROW_HLT', text="")

        if len(scene.sprytile_grids) == 0:
            return

        selected_grid = scene.sprytile_grids[obj.sprytile_gridid]

        layout.label("Tile Grid Settings", icon='GRID')

        layout.prop(selected_grid, "grid", text="Grid Size")

        show_icon = "TRIA_DOWN" if selected_grid.show_extra else "TRIA_RIGHT"
        layout.prop(selected_grid, "show_extra", icon=show_icon, emboss=False)

        if not selected_grid.show_extra:
            return

        layout.prop(selected_grid, "offset")
        layout.prop(selected_grid, "rotate")


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
