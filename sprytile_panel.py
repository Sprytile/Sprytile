import bpy
from . import sprytile_utils
from bpy.types import Panel, UIList

class SprytileMaterialGridList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.mat_id != "":
            mat_data = sprytile_utils.get_mat_data(context, item.mat_id)
            material = bpy.data.materials[item.mat_id]
            if material is None:
                layout.label("Invalid Data")
                return

            display_icon = layout.icon(material)

            row = layout.row(align=True)
            if mat_data is not None:
                show_icon = "TRIA_DOWN" if mat_data.is_expanded else "TRIA_RIGHT"
                row.prop(mat_data, "is_expanded", text="", icon=show_icon, emboss=False)
            row.prop(item, "mat_name", text="", emboss=False, icon_value=display_icon)

        elif item.grid_id != "":
            grid = sprytile_utils.get_grid(context, item.grid_id)
            if grid is not None:
                split = layout.split(0.6, align=True)
                split.prop(grid, "name", text="")
                split.label("%dx%d" % (grid.grid[0], grid.grid[1]))
            else:
                layout.label("Invalid Data")
        else:
            layout.label("Invalid Data")

class SprytileGridDropDown(bpy.types.Menu):
    bl_idname = "SPRYTILE_grid_drop"
    bl_label = "Grid drop down"
    def draw(self, context):
        layout = self.layout
        layout.operator("sprytile.validate_grids", icon="GRID")
        layout.operator("sprytile.material_setup", icon="MATERIAL_DATA")
        layout.operator("sprytile.texture_setup", icon="FORCE_TEXTURE")
        layout.operator("sprytile.add_new_material", icon="NEW")

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
        sprytile_data = context.scene.sprytile_data

        layout.operator("sprytile.modal_tool", icon='BRUSH_DATA')

        layout.prop(sprytile_data, "paint_mode", expand=True)

        row = layout.row(align=True)
        row.prop(sprytile_data, "normal_mode", expand=True)
        row.prop(sprytile_data, "lock_normal", toggle=True)

        row = layout.row()

        row.template_list("SprytileMaterialGridList", "",
                          scene.sprytile_list, "display",
                          scene.sprytile_list, "idx", rows=4)

        col = row.column(align=True)
        col.operator("sprytile.grid_add", icon='ZOOMIN', text="")
        col.operator("sprytile.grid_remove", icon='ZOOMOUT', text="")
        col.menu("SPRYTILE_grid_drop", icon='DOWNARROW_HLT', text="")

        if len(scene.sprytile_mats) == 0:
            return

        selected_grid = sprytile_utils.get_grid(context, obj.sprytile_gridid)
        if selected_grid is None:
            return

        layout.label("Tile Grid Settings", icon='GRID')

        layout.prop(selected_grid, "grid", text="Grid Size")

        show_icon = "TRIA_DOWN" if sprytile_data.show_extra else "TRIA_RIGHT"
        layout.prop(sprytile_data, "show_extra", icon=show_icon, emboss=False)

        if not sprytile_data.show_extra:
            return

        layout.prop(selected_grid, "offset")
        layout.prop(selected_grid, "rotate")


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
