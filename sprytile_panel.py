import bpy
from . import sprytile_utils
from bpy.types import Panel, UIList


class VIEW3D_UL_SprytileMaterialGridList(bpy.types.UIList):
    use_order_name : bpy.props.BoolProperty(default=False, name="Order by Name")
    use_order_invert : bpy.props.BoolProperty(default=False, name="Reverse Order")
    obj_mats_only : bpy.props.BoolProperty(default=False, name="Object Materials Only", description="Show only materials already added to the selected object")

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.mat_id != "":
            mat_data = sprytile_utils.get_mat_data(context, item.mat_id)
            if mat_data is None or item.mat_id not in bpy.data.materials:
                layout.label(text="Invalid Data")
                return
            material = bpy.data.materials[item.mat_id]
            if material is None:
                layout.label(text="Invalid Data")
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
                split = layout.split(factor=0.65, align=True)
                split.prop(grid, "name", text="")
                split.label(text="%dx%d" % (grid.grid[0], grid.grid[1]))
            else:
                layout.label(text="Invalid Data")
        else:
            layout.label(text="Invalid Data")

    def draw_filter(self, context, layout):
        row = layout.row()

        subrow = row.row(align=True)
        subrow.prop(self, "filter_name", text="")
        icon = 'ZOOM_OUT' if self.use_filter_invert else 'ZOOM_IN'
        subrow.prop(self, "use_filter_invert", text="", icon=icon)
        row = layout.row()
        subrow = row.row(align=True)
        subrow.prop(self, "use_order_name", text="", icon='SORTALPHA')
        icon = 'SORT_DESC' if self.use_order_invert else 'SORT_ASC'
        subrow.prop(self, "use_order_invert", text="", icon=icon)
        subrow.prop(self, "obj_mats_only", text="", icon='MESH_CUBE')

    def filter_items(self, context, data, propname):
        display = getattr(data, propname)
        
        helper_funcs = bpy.types.UI_UL_list
        flt_flags = []
        flt_neworder = []

        # Filtering by name
        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(self.filter_name, self.bitflag_filter_item, display, "search_name",
                                                          reverse=False)
        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(display)

        # Filtering by selected object
        if self.obj_mats_only and context.object and context.object.type == "MESH":
            obj_mats = []
            for slot in context.object.material_slots:
                if slot.material:
                    obj_mats.append(slot.material)

            def filter_func(item):
                nonlocal display
                if item[1] == 0:
                    return True

                mat_id = display[item[0]].mat_id or display[item[0]].parent_mat_id
                mat_idx = bpy.data.materials.find(mat_id)
                if mat_idx < 0:
                    return False
                
                return not bpy.data.materials[mat_id] in obj_mats

            flt_flags = [0 if filter_func(x) else self.bitflag_filter_item for x in list(enumerate(flt_flags))]

        sort_list = list(enumerate(display))
        if self.use_order_name:
            sort_list.sort(key=lambda item: item[1].search_name)

        if self.use_order_invert:
            invert_list = list(enumerate(sort_list))
            invert_list_len = len(invert_list) - 1
            invert_list_cp = invert_list.copy()

            def sort_invert(item):
                nonlocal invert_list_cp
                if item[1][1].mat_id:
                    return (invert_list_len - item[0], 0)
                else:
                    i = item[0] - 1
                    while i >= 0:
                        if invert_list_cp[i][1][1].mat_id:
                            return (invert_list_len - i, 1)
                        i -= 1

                    return (item[0], 1)
            
            invert_list.sort(key=sort_invert)
            sort_list = [x[1] for x in invert_list]

        flt_neworder = [x[0] for x in sort_list]

        return flt_flags, flt_neworder


class VIEW3D_MT_SprytileGridDropDown(bpy.types.Menu):
    bl_idname = 'VIEW3D_MT_SprytileGridDropDown'
    bl_label = "Grid drop down"

    def draw(self, context):
        layout = self.layout
        layout.operator("sprytile.tileset_new", icon="PRESET_NEW")
        layout.separator()
        layout.operator("sprytile.validate_grids", icon="GRID")


class VIEW3D_PT_SprytilePanel(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_SprytilePanel"
    bl_label = "Sprytile Painter"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
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
            layout.label(text="No Sprytile Data")
            return

        sprytile_data = context.scene.sprytile_data

        row = layout.row(align=True)
        row.prop(sprytile_data, "uv_flip_x", toggle=True)
        row.prop(sprytile_data, "uv_flip_y", toggle=True)

        row = layout.row(align=True)
        row.operator("sprytile.rotate_left", icon="TRIA_DOWN", text="")
        row.prop(sprytile_data, "mesh_rotate")
        row.operator("sprytile.rotate_right", icon="TRIA_UP", text="")

        if sprytile_data.paint_mode == 'PAINT':
            box = layout.box()
            row = box.row(align=False)
            split = row.split(factor=0.65)

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

        #if sprytile_data.paint_mode == 'SET_NORMAL':
        #    layout.prop(sprytile_data, "paint_hinting")

        if sprytile_data.paint_mode == 'FILL':
            box = layout.box()
            row = box.row(align=True)
            row.prop(sprytile_data, "fill_plane_size", text="Fill Size")
            row.separator()
            row.prop(sprytile_data, "fill_lock_transform", toggle=True, text="", icon="CON_ROTLIMIT")
        
        # View axis and options
        row = layout.row(align=True)
        row.prop(sprytile_data, "lock_normal", toggle=True, text="", icon="LOCKVIEW_{0}".format("ON" if sprytile_data.lock_normal else "OFF"))
        row.prop(sprytile_data, "normal_mode", expand=True)

        if sprytile_data.paint_mode == 'FILL':
            row.separator()
            row.prop(sprytile_data, "auto_merge", toggle=True, text="", icon="AUTOMERGE_{0}".format("ON" if sprytile_data.auto_merge else "OFF"))

        if sprytile_data.paint_mode == 'MAKE_FACE':
            # row = layout.row(align=True)
            row.separator()
            row.prop(sprytile_data, "auto_merge", toggle=True, text="", icon="AUTOMERGE_{0}".format("ON" if sprytile_data.auto_merge else "OFF"))
            row.prop(sprytile_data, "auto_join", toggle=True, text="", icon="MESH_GRID")
            row.prop(sprytile_data, "allow_backface", toggle=True, text="", icon="NORMALS_FACE")

        if sprytile_data.paint_mode == 'PAINT':
            row.separator()
            row.prop(sprytile_data, "allow_backface", toggle=True, text="", icon="NORMALS_FACE")

        layout.separator()

        row = layout.row()
        row.template_list("VIEW3D_UL_SprytileMaterialGridList", "",
                          scene.sprytile_list, "display",
                          scene.sprytile_list, "idx", rows=4)

        col = row.column(align=True)
        col.operator('sprytile.grid_add', icon='ADD', text='')
        col.operator('sprytile.grid_remove', icon='REMOVE', text='')
        col.menu('VIEW3D_MT_SprytileGridDropDown', icon='DOWNARROW_HLT', text='')
        col.separator()
        col.operator('sprytile.grid_move', icon='TRIA_UP', text='').direction = -1
        col.operator('sprytile.grid_move', icon='TRIA_DOWN', text='').direction = 1

        if len(scene.sprytile_mats) == 0:
            return

        selected_grid = sprytile_utils.get_grid(context, obj.sprytile_gridid)
        if selected_grid is None:
            return

        layout.prop(selected_grid, "grid", text="Grid Size")

        row = layout.row()
        row.prop(sprytile_data, "show_overlay", text="", icon='GRID')
        row.prop(sprytile_data, "outline_preview", text="", icon="BORDERMOVE")

        show_icon = "TRIA_DOWN" if sprytile_data.show_extra else "TRIA_RIGHT"
        row.prop(sprytile_data, "show_extra", icon=show_icon, emboss=False)

        if not sprytile_data.show_extra:
            return

        split = layout.split(factor=0.3, align=True)
        split.prop(selected_grid, "auto_pad", toggle=True)

        pad_row = split.row(align=True)
        pad_row.enabled = selected_grid.auto_pad
        pad_row.prop(selected_grid, "auto_pad_offset")

        layout.prop(selected_grid, "padding")

        row = layout.row(align=True)
        row.label(text="Margins")

        col = row.column(align=True)

        row_margins = col.row(align=True)
        row_margins.prop(selected_grid, "margin", text="Left", index=3)
        row_margins.prop(selected_grid, "margin", text="Right", index=1)

        row_margins = col.row(align=True)
        row_margins.prop(selected_grid, "margin", text="Top", index=0)
        row_margins.prop(selected_grid, "margin", text="Bottom", index=2)

        layout.prop(selected_grid, "rotate")
        layout.prop(selected_grid, "offset")


# module classes
classes = (
    VIEW3D_PT_SprytilePanel,
    VIEW3D_UL_SprytileMaterialGridList,
    VIEW3D_MT_SprytileGridDropDown,
)


def register():
    for cl in classes:
        bpy.utils.register_class(cl)


def unregister():
    for cl in classes:
        bpy.utils.unregister_class(cl)

if __name__ == '__main__':
    register()
