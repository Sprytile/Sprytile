import bpy
from . import sprytile_utils
from bpy.types import Panel, UIList

icons = None


class SprytileMaterialGridList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.mat_id != "":
            mat_data = sprytile_utils.get_mat_data(context, item.mat_id)
            if mat_data is None or item.mat_id not in bpy.data.materials:
                layout.label("Invalid Data")
                return
            material = bpy.data.materials[item.mat_id]
            if material is None:
                layout.label("Invalid Data")
                return

            display_icon = layout.icon(material)
            texture = sprytile_utils.get_grid_texture(context.object, mat_data.grids[0])
            if texture is not None:
                display_icon = layout.icon(texture)

            row = layout.row(align=True)
            if mat_data is not None:
                show_icon = "TRIA_DOWN" if mat_data.is_expanded else "TRIA_RIGHT"
                row.prop(mat_data, "is_expanded", text="", icon=show_icon, emboss=False)
            row.prop(item, "mat_name", text="", emboss=False, icon_value=display_icon)

        elif item.grid_id != "":
            grid = sprytile_utils.get_grid(context, item.grid_id)
            if grid is not None:
                split = layout.split(0.65, align=True)
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
        layout.operator("sprytile.tileset_new", icon="NEW")
        layout.separator()
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

        if hasattr(context.scene, "sprytile_data") is False:
            layout.label("No Sprytile Data")
            return

        sprytile_data = context.scene.sprytile_data

        if icons is not None:
            icon_build = icons['SPRYTILE_ICON_BUILD'].icon_id
            icon_paint = icons['SPRYTILE_ICON_PAINT'].icon_id
            icon_fill = icons['SPRYTILE_ICON_FILL'].icon_id
            icon_normal = icons['SPRYTILE_ICON_NORMAL'].icon_id
            row = layout.row(align=True)
            row.alignment = 'CENTER'
            row.scale_y = 1.3
            row.scale_x = 10
            row.prop(sprytile_data, "set_paint_mode", index=2, text="",
                     toggle=True, icon_value=icon_normal, expand=True, icon_only=True)
            row.prop(sprytile_data, "set_paint_mode", index=3, text="Fill",
                     toggle=True, icon_value=icon_fill, expand=True, icon_only=True)
            row.prop(sprytile_data, "set_paint_mode", index=0, text="Paint",
                     toggle=True, icon_value=icon_paint, expand=True, icon_only=True)
            row.prop(sprytile_data, "set_paint_mode", index=1, text="Build",
                     toggle=True, icon_value=icon_build, expand=True, icon_only=True)
        else:
            row = layout.row(align=True)

            dropdown_icon = "TRIA_DOWN" if sprytile_data.show_tools else "TRIA_RIGHT"
            row.prop(sprytile_data, "show_tools", icon=dropdown_icon, emboss=True, text="")

            col = row.column(align=True)

            row = col.row(align=True)
            row.prop(sprytile_data, "set_paint_mode", index=0, text="Paint", toggle=True)
            row.prop(sprytile_data, "set_paint_mode", index=1, text="Build", toggle=True)

            if sprytile_data.show_tools:
                row = col.row(align=True)
                row.prop(sprytile_data, "set_paint_mode", index=2, text="Set Normal", toggle=True)
                row.prop(sprytile_data, "set_paint_mode", index=3, text="Fill", toggle=True)

        row = layout.row(align=True)
        row.prop(sprytile_data, "uv_flip_x", toggle=True)
        row.prop(sprytile_data, "uv_flip_y", toggle=True)

        row = layout.row(align=True)
        row.operator("sprytile.rotate_left", icon="TRIA_DOWN", text="")
        row.prop(sprytile_data, "mesh_rotate")
        row.operator("sprytile.rotate_right", icon="TRIA_UP", text="")

        if sprytile_data.paint_mode == 'MAKE_FACE':
            row = layout.row(align=True)
            row.prop(sprytile_data, "auto_merge", toggle=True)
            row.prop(sprytile_data, "auto_join", toggle=True)

        if sprytile_data.paint_mode == 'PAINT':
            row = layout.row(align=False)
            split = row.split(percentage=0.65)

            left_col = split.column(align=True)
            left_col.prop(sprytile_data, "paint_uv_snap", text="Pixel Snap")
            left_col.prop(sprytile_data, "paint_stretch_x")
            left_col.prop(sprytile_data, "paint_stretch_y")

            sub_col = left_col.column(align=True)
            sub_col.enabled = sprytile_data.paint_stretch_x or sprytile_data.paint_stretch_y
            sub_col.prop(sprytile_data, "paint_edge_snap")
            sub_col.prop(sprytile_data, "edge_threshold")

            right_col = split.column(align=True)
            right_col.label(text="UV Align")
            right_col.row(align=True).prop(sprytile_data, "paint_align_top", toggle=True, text="")
            right_col.row(align=True).prop(sprytile_data, "paint_align_middle", toggle=True, text="")
            right_col.row(align=True).prop(sprytile_data, "paint_align_bottom", toggle=True, text="")
            right_col.row(align=True).prop(sprytile_data, "paint_hinting")

        if sprytile_data.paint_mode == 'SET_NORMAL':
            layout.prop(sprytile_data, "paint_hinting")

        if sprytile_data.paint_mode == 'FILL':
            layout.prop(sprytile_data, "auto_merge", toggle=True)
            box = layout.box()
            box.prop(sprytile_data, "fill_lock_transform", toggle=True)
            box.row().prop(sprytile_data, "fill_plane_size", text="Fill Plane")

        row = layout.row(align=True)
        row.prop(sprytile_data, "lock_normal", toggle=True)
        row.prop(sprytile_data, "normal_mode", expand=True)

        layout.separator()

        row = layout.row()
        row.template_list("SprytileMaterialGridList", "",
                          scene.sprytile_list, "display",
                          scene.sprytile_list, "idx", rows=4)

        col = row.column(align=True)
        col.operator("sprytile.grid_add", icon='ZOOMIN', text="")
        col.operator("sprytile.grid_remove", icon='ZOOMOUT', text="")
        col.menu("SPRYTILE_grid_drop", icon='DOWNARROW_HLT', text="")
        col.separator()
        col.operator("sprytile.grid_move", icon='TRIA_UP', text="").direction = -1
        col.operator("sprytile.grid_move", icon='TRIA_DOWN', text="").direction = 1

        if len(scene.sprytile_mats) == 0:
            return

        selected_grid = sprytile_utils.get_grid(context, obj.sprytile_gridid)
        if selected_grid is None:
            return

        layout.prop(selected_grid, "grid", text="Grid Size")

        row = layout.row()
        row.prop(sprytile_data, "show_overlay", text="", icon='GRID')
        row.prop(sprytile_data, "outline_preview", text="", icon="BORDER_RECT")

        show_icon = "TRIA_DOWN" if sprytile_data.show_extra else "TRIA_RIGHT"
        row.prop(sprytile_data, "show_extra", icon=show_icon, emboss=False)

        if not sprytile_data.show_extra:
            return

        split = layout.split(percentage=0.3, align=True)
        split.prop(selected_grid, "auto_pad", toggle=True)

        pad_row = split.row(align=True)
        pad_row.enabled = selected_grid.auto_pad
        pad_row.prop(selected_grid, "auto_pad_offset")

        layout.prop(selected_grid, "padding")

        row = layout.row(align=True)
        row.label("Margins")

        col = row.column(align=True)
        
        row_margins = col.row(align=True)
        row_margins.prop(selected_grid, "margin", text="Left", index=3)
        row_margins.prop(selected_grid, "margin", text="Right", index=1)

        row_margins = col.row(align=True)
        row_margins.prop(selected_grid, "margin", text="Top", index=0)
        row_margins.prop(selected_grid, "margin", text="Bottom", index=2)

        layout.prop(selected_grid, "rotate")
        layout.prop(selected_grid, "offset")


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
