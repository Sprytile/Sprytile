bl_info = {
    "name": "Sprytile Painter",
    "author": "Jeiel Aranal",
    # Final version number must be two numerals to support x.x.00
    "version": (0, 5, 20),
    "blender": (2, 80, 0),
    "description": "A utility for creating tile based low spec scenes with paint/map editor tools",
    "location": "View3D > UI panel > Sprytile",
    "wiki_url": "http://itch.sprytile.xyz",
    "tracker_url": "https://github.com/ChemiKhazi/Sprytile/issues",
    "category": "Paint"
}

# Put Sprytile directory is sys.path so modules can be loaded
import os
import sys
import inspect
cmd_subfolder = os.path.realpath(os.path.abspath(os.path.split(inspect.getfile(inspect.currentframe()))[0]))
if cmd_subfolder not in sys.path:
    sys.path.insert(0, cmd_subfolder)

locals_list = locals()
if "bpy" in locals_list:
    from importlib import reload
    #reload(addon_updater_ops)
    reload(sprytile_gui)
    reload(sprytile_modal)
    reload(sprytile_panel)
    reload(sprytile_utils)
    reload(sprytile_uv)
    reload(tool_build)
    reload(tool_paint)
    reload(tool_fill)
else:
    from . import sprytile_gui, sprytile_modal, sprytile_panel, sprytile_utils, sprytile_uv
    from sprytile_tools import *

import bpy
import bpy.utils.previews
from bpy.app.handlers import persistent
#from . import addon_updater_ops
from bpy.utils.toolsystem import ToolDef
from bpy.props import *
import rna_keymap_ui


class SprytileSceneSettings(bpy.types.PropertyGroup):
    def set_normal(self, value):
        if "lock_normal" not in self.keys():
            self["lock_normal"] = False

        if self["lock_normal"] is True:
            return
        if self["normal_mode"] == value:
            self["lock_normal"] = not self["lock_normal"]
            return
        self["normal_mode"] = value
        self["lock_normal"] = True
        
        try:
            bpy.ops.sprytile.axis_update('INVOKE_REGION_WIN')
        except:
            pass
        

    def get_normal(self):
        if "normal_mode" not in self.keys():
            self["normal_mode"] = 3
        return self["normal_mode"]

    normal_mode : EnumProperty(
        items=[
            ("X", "X", "World X-Axis", 1),
            ("Y", "Y", "World Y-Axis", 2),
            ("Z", "Z", "World X-Axis", 3)
        ],
        name="Normal Mode",
        description="World axis tiles will be built on",
        default='Z',
        set=set_normal,
        get=get_normal
    )

    lock_normal : BoolProperty(
        name="Lock",
        description="Lock axis used to create tiles",
        default=False
    )

    snap_translate : BoolProperty(
        name="Snap Translate",
        description="Snap pixel translations to pixel grid",
        default=True
    )

    paint_mode : EnumProperty(
        items=[
            ("PAINT", "Paint", "Advanced UV paint tools", 1),
            ("MAKE_FACE", "Build", "Only create new faces", 3),
            ("SET_NORMAL", "Set Normal", "Select a normal to use for face creation", 2),
            ("FILL", "Fill", "Fill the work plane cursor", 4)
        ],
        name="Sprytile Paint Mode",
        description="Paint mode",
        default='MAKE_FACE'
    )

    work_layer : EnumProperty(
        items=[
            ("BASE", "Base", "Base layer", 1),
            ("DECAL_1", "Decal 1", "Decal layer 1", 2)
        ],
        name="Build Layer",
        description="Layer for creating new faces",
        default='BASE'
    )

    def set_layer(self, value):
        keys = self.keys()
        if "work_layer" not in keys:
            self["work_layer"] = 1

        current_value = self.get_layer()
        value = list(value)
        for idx in range(len(value)):
            if current_value[idx] and current_value[idx] & value[idx]:
                value[idx] = False

        for idx in range(len(value)):
            if value[idx]:
                self["work_layer"] = (idx + 1)
                break

    def get_layer(self):
        keys = self.keys()
        if "work_layer" not in keys:
            self["work_layer"] = 1

        out_value = [False, False]
        index_value_lookup = 1, 2
        set_idx = index_value_lookup.index(self["work_layer"])
        out_value[set_idx] = True
        return out_value

    set_work_layer : BoolVectorProperty(
        name="Work Layer",
        description="Layer for creating new faces",
        size=2,
        get=get_layer,
        set=set_layer
    )

    work_layer_mode : EnumProperty(
        items=[
            ("MESH_DECAL", "Mesh Decal", "Create an overlay mesh. More compatible but less performant.", 1),
            ("UV_DECAL", "UV Layer", "Use UV layers. More performant in engine but requires shader support.", 2)
        ],
        name="Mode",
        description="Method used for layering",
        default="MESH_DECAL"
    )

    mesh_decal_offset : FloatProperty(
        name="Decal Offset",
        description="Distance to offset mesh decal, to prevent z-fighting",
        default=0.002,
        min=0.001,
        max=0.2,
        precision=4,
        subtype='DISTANCE',
    )

    world_pixels : IntProperty(
        name="World Pixel Density",
        description="How many pixels are displayed in one world unit",
        subtype='PIXEL',
        default=32,
        min=8,
        max=2048
    )

    paint_normal_vector : FloatVectorProperty(
        name="Srpytile Last Paint Normal",
        description="Last saved painting normal used by Sprytile",
        subtype='DIRECTION',
        default=(0.0, 0.0, 1.0)
    )

    paint_up_vector : FloatVectorProperty(
        name="Sprytile Last Paint Up Vector",
        description="Last saved painting up vector used by Sprytile",
        subtype='DIRECTION',
        default=(0.0, 1.0, 0.0)
    )

    uv_flip_x : BoolProperty(
        name="Flip X",
        description="Flip tile horizontally",
        default=False
    )
    uv_flip_y : BoolProperty(
        name="Flip Y",
        description="Flip tile vertically",
        default=False
    )
    mesh_rotate : FloatProperty(
        name="Grid Rotation",
        description="Rotation of tile",
        subtype='ANGLE',
        unit='ROTATION',
        step=9000,
        precision=0,
        min=-6.28319,
        max=6.28319,
        default=0.0
    )

    cursor_snap : EnumProperty(
        items=[
            ('VERTEX', "Vertex", "Snap cursor to nearest vertex", "SNAP_GRID", 1),
            ('GRID', "Grid", "Snap cursor to grid", "SNAP_VERTEX", 2)
        ],
        name="Cursor snap mode",
        description="Sprytile cursor snap mode"
    )

    cursor_flow : BoolProperty(
        name="Cursor Flow",
        description="Cursor automatically follows mesh building",
        default=False
    )
    paint_align : EnumProperty(
        items=[
            ('TOP_LEFT', "Top Left", "", 1),
            ('TOP', "Top", "", 2),
            ('TOP_RIGHT', "Top Right", "", 3),
            ('LEFT', "Left", "", 4),
            ('CENTER', "Center", "", 5),
            ('RIGHT', "Right", "", 6),
            ('BOTTOM_LEFT', "Bottom Left", "", 7),
            ('BOTTOM', "Bottom", "", 8),
            ('BOTTOM_RIGHT', "Bottom Right", "", 9),
        ],
        name="Paint Align",
        description="Paint alignment mode",
        default='CENTER'
    )

    def set_align_toggle(self, value, row):
        prev_value = self.get_align_toggle(row)
        row_val = 0
        if row == 'top':
            row_val = 0
        elif row == 'middle':
            row_val = 3
        elif row == 'bottom':
            row_val = 6
        else:
            return
        col_val = 0
        if value[0] and prev_value[0] != value[0]:
            col_val = 1
        elif value[1] and prev_value[1] != value[1]:
            col_val = 2
        elif value[2] and prev_value[2] != value[2]:
            col_val = 3
        else:
            return
        self["paint_align"] = row_val + col_val

    def set_align_top(self, value):
        self.set_align_toggle(value, "top")

    def set_align_middle(self, value):
        self.set_align_toggle(value, "middle")

    def set_align_bottom(self, value):
        self.set_align_toggle(value, "bottom")

    def get_align_toggle(self, row):
        if "paint_align" not in self.keys():
            self["paint_align"] = 5
        align = self["paint_align"]
        if row == 'top':
            return align == 1, align == 2, align == 3
        if row == 'middle':
            return align == 4, align == 5, align == 6
        if row == 'bottom':
            return align == 7, align == 8, align == 9
        return False, False, False

    def get_align_top(self):
        return self.get_align_toggle("top")

    def get_align_middle(self):
        return self.get_align_toggle("middle")

    def get_align_bottom(self):
        return self.get_align_toggle("bottom")

    paint_align_top : BoolVectorProperty(
        name="Align",
        size=3,
        set=set_align_top,
        get=get_align_top
    )
    paint_align_middle : BoolVectorProperty(
        name="Align",
        size=3,
        set=set_align_middle,
        get=get_align_middle
    )
    paint_align_bottom : BoolVectorProperty(
        name="Align",
        size=3,
        set=set_align_bottom,
        get=get_align_bottom
    )

    paint_hinting : BoolProperty(
        name="Hinting",
        description="Selected edge is used as X axis for UV mapping."
    )
    paint_stretch_x : BoolProperty(
        name="Stretch X",
        description="Stretch face over X axis of tile"
    )
    paint_stretch_y : BoolProperty(
        name="Stretch Y",
        description="Stretch face over Y axis of tile"
    )
    paint_edge_snap : BoolProperty(
        name="Snap To Edge",
        description="Snap UV vertices to edges of tile when close enough.",
        default=True
    )
    edge_threshold : FloatProperty(
        name="Threshold",
        description="Ratio of UV tile near to edge to apply snap",
        min=0.01,
        max=0.5,
        soft_min=0.01,
        soft_max=0.5,
        default=0.35
    )
    paint_uv_snap : BoolProperty(
        name="UV Snap",
        default=True,
        description="Snap UV vertices to texture pixels"
    )

    is_snapping : BoolProperty(
        name="Is Cursor Snap",
        description="Is cursor snapping currently activated"
    )
    is_picking : BoolProperty(
        name="Is Tile Picking",
        description="Is tile picking currently activated"
    )
    has_selection : BoolProperty(
        name="Has selection",
        description="Is there a mesh element selected"
    )
    is_grid_translate : BoolProperty(
        name="Is Grid Translate",
        description="Grid translate operator is running"
    )
    show_extra : BoolProperty(
        name="Extra UV Grid Settings",
        default=False
    )
    show_overlay : BoolProperty(
        name="Show Grid Overlay",
        description="Show grid on tile selection UI",
        default=True
    )
    outline_preview : BoolProperty(
        name="Outline Preview",
        description="Draw an outline on tile placement preview",
        default=True
    )
    auto_merge : BoolProperty(
        name="Auto Merge",
        description="Automatically merge vertices when creating faces",
        default=True
    )
    auto_join : BoolProperty(
        name="Join Multi",
        description="Join multi tile faces when possible",
        default=False
    )

    allow_backface: bpy.props.BoolProperty(
        name="Backface",
        description="Should Sprytile work on backfaces",
        default=False,
    )

    def set_reload(self, value):
        self["auto_reload"] = value
        if value is True:
            bpy.ops.sprytile.reload_auto('INVOKE_REGION_WIN')

    def get_reload(self):
        if "auto_reload" not in self.keys():
            self["auto_reload"] = False
        return self["auto_reload"]

    auto_reload: bpy.props.BoolProperty(
        name="Auto",
        description="Automatically reload images every few seconds",
        default=False,
        set=set_reload,
        get=get_reload
    )

    fill_lock_transform : BoolProperty(
        name="Lock Transforms",
        description="Filled faces keep current rotations",
        default=False,
    )

    axis_plane_display : EnumProperty(
        items=[
            ('OFF', "Off", "Always Off", "RADIOBUT_OFF", 1),
            ('ON', "On", "Always On", "RADIOBUT_ON", 2),
            ('MIDDLE_MOUSE', "View", "Only when changing view", "CAMERA_DATA", 3)
        ],
        name="Work Plane Cursor",
        description="Display mode of Work Plane Cursor",
        default='MIDDLE_MOUSE'
    )

    axis_plane_settings : BoolProperty(
        name="Axis Plane Settings",
        description="Show Work Plane Cursor settings",
        default=False
    )

    axis_plane_size : IntVectorProperty(
        name="Plane Size",
        description="Size of the Work Plane Cursor",
        size=2,
        default=(2, 2),
        min=1,
        soft_min=1
    )

    axis_plane_color : FloatVectorProperty(
        name="Plane Color",
        description="Color Work Plane Cursor is drawn with",
        size=3,
        default=(0.7, 0.7, 0.7),
        subtype='COLOR'
    )

    fill_plane_size : IntVectorProperty(
        name="Fill Plane Size",
        description="Size of the Fill Plane",
        size=2,
        default=(10, 10),
        min=1,
        soft_min=1
    )


class SprytileMaterialGridSettings(bpy.types.PropertyGroup):
    mat_id : StringProperty(
        name="Material Id",
        description="Name of the material this grid references",
        default=""
    )
    id : IntProperty(
        name="Grid ID",
        default=-1
    )
    name : StringProperty(
        name="Grid Name"
    )
    grid : IntVectorProperty(
        name="Size",
        description="Grid size, in pixels",
        min=1,
        size=2,
        subtype='XYZ',
        default=(32, 32)
    )

    def set_padding(self, value):
        current_padding = self.get_padding()
        if "grid" not in self.keys():
            self["grid"] = (32, 32)
        padding_delta = [ (value[0] - current_padding[0]) * 2, (value[1] - current_padding[1]) * 2]
        new_grid = [self["grid"][0] - padding_delta[0], self["grid"][1] - padding_delta[1]]
        if new_grid[0] < 1 or new_grid[1] < 1:
            return
        self["grid"] = (new_grid[0], new_grid[1])
        self["padding"] = value

    def get_padding(self):
        if "padding" not in self.keys():
            try:
                self["padding"] = (0, 0)
            except:
                return (0, 0)
        return self["padding"]

    padding : IntVectorProperty(
        name="Padding",
        description="Cell padding, in pixels",
        min=0,
        size=2,
        subtype='XYZ',
        default=(0, 0),
        set=set_padding,
        get=get_padding
    )

    margin : IntVectorProperty(
        name="Margin",
        description="Spacing between tiles (top, right, bottom, left)",
        min=0,
        size=4,
        subtype='XYZ',
        default=(0, 0, 0, 0)
    )
    offset : IntVectorProperty(
        name="Offset",
        description="Offset of the grid",
        subtype='TRANSLATION',
        size=2,
        default=(0, 0)
    )
    rotate : FloatProperty(
        name="UV Rotation",
        description="Rotation of UV grid",
        subtype='ANGLE',
        unit='ROTATION',
        default=0.0
    )
    tile_selection : IntVectorProperty(
        name="Tile Selection",
        size=4,
        default=(0, 0, 1, 1)
    )
    auto_pad : BoolProperty(
        name="Auto Pad",
        description="Apply a subpixel padding to tiles of this grid",
        default=True
    )
    auto_pad_offset : FloatProperty(
        name="Pad Offset",
        description="Subpixel padding amount around edges of tiles",
        default=0.05,
        min=0.05,
        max=0.20
    )


class SprytileMaterialData(bpy.types.PropertyGroup):

    def expanded_default(self):
        if 'is_expanded' not in self.keys():
            self['is_expanded'] = True

    def get_expanded(self):
        self.expanded_default()
        return self['is_expanded']

    def set_expanded(self, value):
        self.expanded_default()
        do_rebuild = self['is_expanded'] is not value
        self['is_expanded'] = value
        if do_rebuild:
            bpy.ops.sprytile.build_grid_list()

    mat_id : StringProperty(
        name="Material Id",
        description="Name of the material this grid references",
        default=""
    )
    is_expanded : BoolProperty(
        default=True,
        description="Toggle tile material",
        get=get_expanded,
        set=set_expanded
    )
    grids : CollectionProperty(type=SprytileMaterialGridSettings)


class SprytileGridDisplay(bpy.types.PropertyGroup):
    mat_id: bpy.props.StringProperty(default="")
    grid_id: bpy.props.IntProperty(default=-1)

    def get_mat_name(self):
        if self.mat_id == "":
            return ""
        data_idx = bpy.data.materials.find(self.mat_id)
        if data_idx < 0:
            return ""
        return bpy.data.materials[self.mat_id].name

    def set_mat_name(self, value):
        if self.mat_id == "":
            return
        data_idx = bpy.data.materials.find(self.mat_id)
        if data_idx < 0:
            return
        bpy.data.materials[self.mat_id].name = value
        bpy.ops.sprytile.validate_grids()

    def get_search_name(self):
        mat_name = self.get_mat_name()
        if mat_name:
            return mat_name

        return self.parent_mat_name

    mat_name: bpy.props.StringProperty(
        get=get_mat_name,
        set=set_mat_name
    )

    parent_mat_name : bpy.props.StringProperty(default="")
    parent_mat_id : bpy.props.StringProperty(default="")
    
    search_name : bpy.props.StringProperty(
        get=get_search_name,
        set=None
    )




class SprytileGridList(bpy.types.PropertyGroup):
    def get_idx(self):
        if "idx" not in self.keys():
            self["idx"] = 0
        return self["idx"]

    def set_idx(self, value):
        # If the selected index is a material entry
        # Move to next entry
        list_size = len(self.display)
        while value < (list_size - 1) and self.display[value].mat_id != "":
            value += 1
        value = max(0, min(len(self.display)-1, value))
        self["idx"] = value
        if value < 0 or value >= len(self.display):
            return
        # Set the object grid id to target grid
        target_entry = self.display[value]
        if target_entry.grid_id != -1:
            bpy.context.object.sprytile_gridid = target_entry.grid_id

    display: bpy.props.CollectionProperty(type=SprytileGridDisplay)
    idx: bpy.props.IntProperty(
        default=0,
        get=get_idx,
        set=set_idx
    )


class PROP_OP_SprytilePropsSetup(bpy.types.Operator):
    bl_idname = "sprytile.props_setup"
    bl_label = "Setup Sprytile data"

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.props_setup()
        return {'FINISHED'}

    @staticmethod
    def props_setup():
        bpy.types.Scene.sprytile_data = bpy.props.PointerProperty(type=SprytileSceneSettings)
        bpy.types.Scene.sprytile_mats = bpy.props.CollectionProperty(type=SprytileMaterialData)

        bpy.types.Scene.sprytile_list = bpy.props.PointerProperty(type=SprytileGridList)

        bpy.types.Scene.sprytile_ui = bpy.props.PointerProperty(type=sprytile_gui.SprytileGuiData)

        bpy.types.Object.sprytile_gridid = IntProperty(
            name="Grid ID",
            description="Grid index used for object",
            default=-1
        )


class PROP_OP_SprytilePropsTeardown(bpy.types.Operator):
    bl_idname = "sprytile.props_teardown"
    bl_label = "Remove Sprytile data"
    bl_description = "WARNING: This will clear all Sprytile data, tile grids will be lost. Continue?"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        self.props_teardown()
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def draw(self, context):
        layout = self.layout


    @staticmethod
    def props_teardown():
        del bpy.types.Scene.sprytile_data
        del bpy.types.Scene.sprytile_mats

        del bpy.types.Scene.sprytile_list

        del bpy.types.Scene.sprytile_ui

        del bpy.types.Object.sprytile_gridid


class SprytileAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    preview_transparency: bpy.props.FloatProperty(
        name="Preview Alpha",
        description="Transparency level of build preview cursor",
        default=0.8,
        min=0,
        max=1
    )

    auto_adjust_viewport_shading: bpy.props.BoolProperty(
        name="Automatically switch viewport to Material Preview mode",
        description="If enabled, viewport shading mode will change to Material Preview while using Sprytile tools",
        default=True,
    )

    auto_pixel_viewport: bpy.props.BoolProperty(
        name="Automatically setup pixel viewport",
        description="If enabled, loading a tileset will automatically setup the pixel viewport.\nDisable if you're not going for a flatshaded look",
        default=False,
    )

    default_pixel_density: bpy.props.IntProperty(
        name="Pixel Density",
        description="How many pixels are displayed in one world unit",
        default=32,
        min=8
    )

    default_grid: bpy.props.IntVectorProperty(
        name="Grid Size",
        description="Tileset grid size, in pixels",
        min=1,
        size=2,
        subtype='XYZ',
        default=(32, 32)
    )

    default_pad_offset: bpy.props.FloatProperty(
        name="Subpixel Padding",
        description="Default subpixel edge padding for tilesets",
        default=0.05,
        min=0.05,
        max=0.20
    )

    auto_grid_setup: bpy.props.BoolProperty(
        name="Automatically setup grid",
        description="If enabled, loading a tileset will set the grid size to the chosen pixel density.",
        default=True,
    )

    #def set_picker(self, value):
    #    if "tile_picker_key" not in self.keys():
    #        self["tile_picker_key"] = 1
    #    if "tile_sel_move_key" not in self.keys():
    #        self["tile_sel_move_key"] = 2
    #    if value != self["tile_sel_move_key"]:
    #        self["tile_picker_key"] = value

    #def get_picker(self):
    #    if "tile_picker_key" not in self.keys():
    #        self["tile_picker_key"] = 1
    #    return self["tile_picker_key"]

    #tile_picker_key: bpy.props.EnumProperty(
    #    items=[
    #        ("Alt", "Alt", "Press Alt to pick tiles", 1),
    #        ("Ctrl", "Ctrl", "Press Ctrl to pick tiles", 2),
    #        ("Shift", "Shift", "Press Shift to pick tiles", 3)
    #    ],
    #    name="Tile Picker Key",
    #    description="Key for using the tile picker eyedropper",
    #    default='Alt',
    #    set=set_picker,
    #    get=get_picker
    #)

    #def set_sel_move(self, value):
    #    if "tile_picker_key" not in self.keys():
    #        self["tile_picker_key"] = 1
    #    if "tile_sel_move_key" not in self.keys():
    #        self["tile_sel_move_key"] = 2
    #    if value != self["tile_picker_key"]:
    #        self["tile_sel_move_key"] = value

    #def get_sel_move(self):
    #    if "tile_sel_move_key" not in self.keys():
    #        self["tile_sel_move_key"] = 1
    #    return self["tile_sel_move_key"]

    #tile_sel_move_key: bpy.props.EnumProperty(
    #    items=[
    #        ("Alt", "Alt", "Press Alt to move tile selection", 1),
    #        ("Ctrl", "Ctrl", "Press Ctrl to move tile selection", 2),
    #        ("Shift", "Shift", "Press Shift to move tile selection", 3)
    #    ],
    #    name="Tile Selection Move Key",
    #    description="Key for moving the tile selection",
    #    default='Ctrl',
    #    set=set_sel_move,
    #    get=get_sel_move
    #)

    # addon updater preferences
    #auto_check_update: bpy.props.BoolProperty(
    #    name="Auto-check for Update",
    #    description="If enabled, auto-check for updates using an interval",
    #    default=False,
    #)
    #updater_intrval_months: bpy.props.IntProperty(
    #    name='Months',
    #    description="Number of months between checking for updates",
    #    default=0,
    #    min=0
    #)
    #updater_intrval_days: bpy.props.IntProperty(
    #    name='Days',
    #    description="Number of days between checking for updates",
    #    default=7,
    #    min=0,
    #)
    #updater_intrval_hours: bpy.props.IntProperty(
    #    name='Hours',
    #    description="Number of hours between checking for updates",
    #    default=0,
    #    min=0,
    #    max=23
    #)
    #updater_intrval_minutes: bpy.props.IntProperty(
    #    name='Minutes',
    #    description="Number of minutes between checking for updates",
    #    default=0,
    #    min=0,
    #    max=59
    #)

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "preview_transparency")

        box = layout.box()

        box.label(text="Global Options")

        row = box.row()

        size_left_col = 0.3
        
        split = row.split(factor=size_left_col)
        col = split.column()
        col.label(text="Default Settings:")

        col = split.column(align=True)
        col.prop(self, "default_pixel_density")
        col.row().prop(self, "default_grid")
        col.prop(self, "default_pad_offset")

        row = box.row()
        split = row.split(factor=size_left_col)

        col = split.column()
        col.label(text="On Load Tileset:")
        
        col = split.column()
        col.prop(self, "auto_grid_setup")
        col.prop(self, "auto_pixel_viewport")
        
        row = box.row()
        split = row.split(factor=size_left_col)

        col = split.column()
        col.label(text="On Sprytile Edit:")

        col = split.column()
        col.prop(self, "auto_adjust_viewport_shading")

        #box = layout.box()
        #box.label(text = "Keyboard Shortcuts")
        #box.prop(self, "tile_picker_key")
        #box.prop(self, "tile_sel_move_key")

        #kc = bpy.context.window_manager.keyconfigs.user
        #km = kc.keymaps['Mesh']
        #kmi_idx = km.keymap_items.find('sprytile.modal_tool')
        #if kmi_idx >= 0:
        #    box.label(text="Tile Mode Shortcut")
        #    col = box.column()

        #    kmi = km.keymap_items[kmi_idx]
        #    km = km.active()
        #    col.context_pointer_set("keymap", km)
        #    rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)

        #addon_updater_ops.update_settings_ui(self, context)


@ToolDef.from_fn
def toolbar_build():
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")

    return dict(
        idname="sprytile.tool_build",
        label="Sprytile Build",
        description=(
            "Make new tiles"
        ),
        icon=os.path.join(icons_dir, "sprytile.build_tool"),
        keymap=sprytile_modal.VIEW3D_OP_SprytileModalTool.tool_keymaps['MAKE_FACE'],
        widget="VIEW3D_GGT_sprytile_gui",
        cursor="KNIFE"
    )


@ToolDef.from_fn
def toolbar_paint():
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")

    return dict(
        idname="sprytile.tool_paint",
        label="Sprytile Paint",
        description=(
            "Paint existing tiles/faces"
        ),
        icon=os.path.join(icons_dir, "sprytile.paint_tool"),
        keymap=sprytile_modal.VIEW3D_OP_SprytileModalTool.tool_keymaps['PAINT'],
        widget="VIEW3D_GGT_sprytile_gui",
        cursor="PAINT_BRUSH"
    )


@ToolDef.from_fn
def toolbar_fill():
    def draw_settings(context, layout, tool):
        pass

    icons_dir = os.path.join(os.path.dirname(__file__), "icons")

    return dict(
        idname="sprytile.tool_fill",
        label="Sprytile Fill",
        description=(
            "Fill existing tiles/faces"
        ),
        icon=os.path.join(icons_dir, "sprytile.fill_tool"),
        keymap=sprytile_modal.VIEW3D_OP_SprytileModalTool.tool_keymaps['FILL'],
        widget="VIEW3D_GGT_sprytile_gui",
        cursor="SCROLL_XY"
    )


def get_tool_list(space_type, context_mode):
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    cls = ToolSelectPanelHelper._tool_class_from_space_type(space_type)
    return cls._tools[context_mode]


def register_tools():
    tools = get_tool_list('VIEW_3D', 'EDIT_MESH')

    for index, tool in enumerate(tools, 1):
        if isinstance(tool, ToolDef) and tool.label == "Transform":
            break

    tools[:index] += None, toolbar_build, toolbar_paint, toolbar_fill


def unregister_tools():
    tools = get_tool_list('VIEW_3D', 'EDIT_MESH')

    index = tools.index(toolbar_build) - 1 # None
    tools.pop(index)
    tools.remove(toolbar_build)
    tools.remove(toolbar_paint)
    tools.remove(toolbar_fill)


def generate_tool_keymap(keyconfig, paint_mode):
    keymap = keyconfig.keymaps.new(name=sprytile_modal.VIEW3D_OP_SprytileModalTool.tool_keymaps[paint_mode], space_type='VIEW_3D', region_type='WINDOW')
    km_items = keymap.keymap_items
    km_items.new("sprytile.modal_tool", 'LEFTMOUSE', 'PRESS')
    km_items.new("sprytile.tile_picker", 'LEFT_ALT', 'PRESS')
    km_items.new("sprytile.rotate_left", 'Q', 'PRESS')
    km_items.new("sprytile.rotate_right", 'E', 'PRESS')
    km_items.new("sprytile.flip_x_toggle", 'Q', 'PRESS').shift = True
    km_items.new("sprytile.flip_y_toggle", 'E', 'PRESS').shift = True

    if paint_mode in {'MAKE_FACE', 'FILL'}:
        km_items.new("sprytile.snap_cursor", 'S', 'PRESS')
        km_items.new("sprytile.set_normal", 'N', 'PRESS')

    return keymap


def setup_keymap():
    km_default = sprytile_modal.VIEW3D_OP_SprytileModalTool.default_keymaps
    km_addon = sprytile_modal.VIEW3D_OP_SprytileModalTool.addon_keymaps
    win_mgr = bpy.context.window_manager
    key_config = win_mgr.keyconfigs.addon
    key_config_default = win_mgr.keyconfigs.default

    tools = ['MAKE_FACE', 'PAINT', 'FILL']

    for tool in tools:
        keymap = generate_tool_keymap(key_config, tool)
        km_addon.append(keymap)
        keymap =  key_config_default.keymaps.new(name=sprytile_modal.VIEW3D_OP_SprytileModalTool.tool_keymaps[tool], space_type='VIEW_3D', region_type='WINDOW')
        km_default.append(keymap)


def teardown_keymap():
    for keymap in sprytile_modal.VIEW3D_OP_SprytileModalTool.addon_keymaps:
        bpy.context.window_manager.keyconfigs.addon.keymaps.remove(keymap)
    sprytile_modal.VIEW3D_OP_SprytileModalTool.addon_keymaps.clear()

    for keymap in sprytile_modal.VIEW3D_OP_SprytileModalTool.default_keymaps:
        bpy.context.window_manager.keyconfigs.default.keymaps.remove(keymap)
    sprytile_modal.VIEW3D_OP_SprytileModalTool.default_keymaps.clear()


# module classes
classes = (
        SprytileSceneSettings,
        SprytileMaterialGridSettings,
        SprytileMaterialData,
        SprytileGridDisplay,
        SprytileGridList,
        PROP_OP_SprytilePropsSetup,
        PROP_OP_SprytilePropsTeardown,
        SprytileAddonPreferences,
)


# submodule
submodules = (
    sprytile_gui,
    sprytile_modal,
    sprytile_panel,
    sprytile_utils,
    sprytile_uv,
    tool_build,
    tool_paint,
    tool_fill,
)

@persistent
def sprytile_load_handler(dummy):
    sprytile_data = bpy.context.scene.sprytile_data
    
    # Turn on auto reload
    if sprytile_data.auto_reload:
        bpy.ops.sprytile.reload_auto('INVOKE_REGION_WIN')

    # Reasonable assumption that a file that does not have a path
    # is new, so setup the pixel density according to preferences
    if not bpy.data.filepath:
        addon_prefs = bpy.context.preferences.addons[__package__].preferences
        if addon_prefs:
            sprytile_data.world_pixels = addon_prefs.default_pixel_density

def register():
    #addon_updater_ops.register(bl_info)

    for cl in classes:
        bpy.utils.register_class(cl)

    for submod in submodules:
        submod.register()

    PROP_OP_SprytilePropsSetup.props_setup()
    register_tools()
    setup_keymap()

    bpy.app.handlers.load_post.append(sprytile_load_handler)


def unregister():
    teardown_keymap()
    unregister_tools()
    PROP_OP_SprytilePropsTeardown.props_teardown()

    for cl in classes:
        bpy.utils.unregister_class(cl)

    for submod in submodules:
        submod.unregister()

    # Unregister self from sys.path as well
    cmd_subfolder = os.path.realpath(os.path.abspath(os.path.split(inspect.getfile(inspect.currentframe()))[0]))
    if cmd_subfolder in sys.path:
        sys.path.remove(cmd_subfolder)


if __name__ == "__main__":
    register()
