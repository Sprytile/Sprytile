bl_info = {
    "name": "Sprytile Painter",
    "author": "Jeiel Aranal",
    # Final version number must be two numerals to support x.x.00
    "version": (0, 4, 50),
    "blender": (2, 7, 7),
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
    reload(addon_updater_ops)
    reload(sprytile_gui)
    reload(sprytile_modal)
    reload(sprytile_panel)
    reload(sprytile_utils)
    reload(sprytile_uv)
    reload(tool_build)
    reload(tool_paint)
    reload(tool_fill)
    reload(tool_set_normal)
else:
    from . import sprytile_gui, sprytile_modal, sprytile_panel, sprytile_utils, sprytile_uv
    from sprytile_tools import *

import bpy
import bpy.utils.previews
from . import addon_updater_ops
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
        bpy.ops.sprytile.axis_update('INVOKE_REGION_WIN')

    def get_normal(self):
        if "normal_mode" not in self.keys():
            self["normal_mode"] = 3
        return self["normal_mode"]

    normal_mode = EnumProperty(
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

    lock_normal = BoolProperty(
        name="Lock",
        description="Lock axis used to create tiles",
        default=False
    )

    snap_translate = BoolProperty(
        name="Snap Translate",
        description="Snap pixel translations to pixel grid",
        default=True
    )

    paint_mode = EnumProperty(
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

    def set_show_tools(self, value):
        keys = self.keys()
        if "show_tools" not in keys:
            self["show_tools"] = False
        self["show_tools"] = value
        if value is False:
            if "paint_mode" not in keys:
                self["paint_mode"] = 3
            if self["paint_mode"] in {2, 4}:
                self["paint_mode"] = 3

    def get_show_tools(self):
        if "show_tools" not in self.keys():
            self["show_tools"] = False
        return self["show_tools"]

    show_tools = BoolProperty(
        default=False,
        set=set_show_tools,
        get=get_show_tools
    )

    def set_dummy(self, value):
        current_value = self.get_dummy_actual(True)
        value = list(value)
        for idx in range(len(value)):
            if current_value[idx] and current_value[idx] & value[idx]:
                value[idx] = False

        mode_value_idx = [1, 3, 2, 4]

        def get_mode_value(arr_value):
            for i in range(len(arr_value)):
                if arr_value[i]:
                    return mode_value_idx[i]
            return -1

        run_modal = True
        paint_mode = get_mode_value(value)
        if paint_mode > 0:
            self["paint_mode"] = paint_mode
        else:
            run_modal = False
            if "is_running" in self.keys():
                if self["is_running"]:
                    self["is_running"] = False
                else:
                    run_modal = True

        if run_modal:
            bpy.ops.sprytile.modal_tool('INVOKE_REGION_WIN')

    def get_dummy_actual(self, force_real):
        if "paint_mode" not in self.keys():
            self["paint_mode"] = 3

        out_value = [False, False, False, False]
        if self["is_running"] or force_real:
            index_value_lookup = 1, 3, 2, 4
            set_idx = index_value_lookup.index(self["paint_mode"])
            out_value[set_idx] = True
        return out_value

    def get_dummy(self):
        if "is_running" not in self.keys():
            self["is_running"] = False
        is_running = self["is_running"]
        return self.get_dummy_actual(is_running)

    set_paint_mode = BoolVectorProperty(
        name="Set Paint Mode",
        description="Set Sprytile Tool Mode",
        size=4,
        set=set_dummy,
        get=get_dummy
    )

    work_layer = EnumProperty(
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

    set_work_layer = BoolVectorProperty(
        name="Work Layer",
        description="Layer for creating new faces",
        size=2,
        get=get_layer,
        set=set_layer
    )

    work_layer_mode = EnumProperty(
        items=[
            ("MESH_DECAL", "Mesh Decal", "Create an overlay mesh. More compatible but less performant.", 1),
            ("UV_DECAL", "UV Layer", "Use UV layers. More performant in engine but requires shader support.", 2)
        ],
        name="Mode",
        description="Method used for layering",
        default="MESH_DECAL"
    )

    mesh_decal_offset = FloatProperty(
        name="Decal Offset",
        description="Distance to offset mesh decal, to prevent z-fighting",
        default=0.002,
        min=0.001,
        max=0.2,
        precision=4,
        subtype='DISTANCE',
    )

    world_pixels = IntProperty(
        name="World Pixel Density",
        description="How many pixels are displayed in one world unit",
        subtype='PIXEL',
        default=32,
        min=8,
        max=2048
    )

    paint_normal_vector = FloatVectorProperty(
        name="Srpytile Last Paint Normal",
        description="Last saved painting normal used by Sprytile",
        subtype='DIRECTION',
        default=(0.0, 0.0, 1.0)
    )

    paint_up_vector = FloatVectorProperty(
        name="Sprytile Last Paint Up Vector",
        description="Last saved painting up vector used by Sprytile",
        subtype='DIRECTION',
        default=(0.0, 1.0, 0.0)
    )

    uv_flip_x = BoolProperty(
        name="Flip X",
        description="Flip tile horizontally",
        default=False
    )
    uv_flip_y = BoolProperty(
        name="Flip Y",
        description="Flip tile vertically",
        default=False
    )
    mesh_rotate = FloatProperty(
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

    cursor_snap = EnumProperty(
        items=[
            ('VERTEX', "Vertex", "Snap cursor to nearest vertex", "SNAP_GRID", 1),
            ('GRID', "Grid", "Snap cursor to grid", "SNAP_VERTEX", 2)
        ],
        name="Cursor snap mode",
        description="Sprytile cursor snap mode"
    )

    cursor_flow = BoolProperty(
        name="Cursor Flow",
        description="Cursor automatically follows mesh building",
        default=False
    )
    paint_align = EnumProperty(
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

    paint_align_top = BoolVectorProperty(
        name="Align",
        size=3,
        set=set_align_top,
        get=get_align_top
    )
    paint_align_middle = BoolVectorProperty(
        name="Align",
        size=3,
        set=set_align_middle,
        get=get_align_middle
    )
    paint_align_bottom = BoolVectorProperty(
        name="Align",
        size=3,
        set=set_align_bottom,
        get=get_align_bottom
    )

    paint_hinting = BoolProperty(
        name="Hinting",
        description="Selected edge is used as X axis for UV mapping."
    )
    paint_stretch_x = BoolProperty(
        name="Stretch X",
        description="Stretch face over X axis of tile"
    )
    paint_stretch_y = BoolProperty(
        name="Stretch Y",
        description="Stretch face over Y axis of tile"
    )
    paint_edge_snap = BoolProperty(
        name="Snap To Edge",
        description="Snap UV vertices to edges of tile when close enough.",
        default=True
    )
    edge_threshold = FloatProperty(
        name="Threshold",
        description="Ratio of UV tile near to edge to apply snap",
        min=0.01,
        max=0.5,
        soft_min=0.01,
        soft_max=0.5,
        default=0.35
    )
    paint_uv_snap = BoolProperty(
        name="UV Snap",
        default=True,
        description="Snap UV vertices to texture pixels"
    )

    is_running = BoolProperty(
        name="Sprytile Running",
        description="Exit Sprytile tool"
    )
    is_snapping = BoolProperty(
        name="Is Cursor Snap",
        description="Is cursor snapping currently activated"
    )
    has_selection = BoolProperty(
        name="Has selection",
        description="Is there a mesh element selected"
    )
    is_grid_translate = BoolProperty(
        name="Is Grid Translate",
        description="Grid translate operator is running"
    )
    show_extra = BoolProperty(
        name="Extra UV Grid Settings",
        default=False
    )
    show_overlay = BoolProperty(
        name="Show Grid Overlay",
        description="Show grid on tile selection UI",
        default=True
    )
    outline_preview = BoolProperty(
        name="Outline Preview",
        description="Draw an outline on tile placement preview",
        default=True
    )
    auto_merge = BoolProperty(
        name="Auto Merge",
        description="Automatically merge vertices when creating faces",
        default=True
    )
    auto_join = BoolProperty(
        name="Join Multi",
        description="Join multi tile faces when possible",
        default=False
    )

    def set_reload(self, value):
        self["auto_reload"] = value
        if value is True:
            bpy.ops.sprytile.reload_auto('INVOKE_REGION_WIN')

    def get_reload(self):
        if "auto_reload" not in self.keys():
            self["auto_reload"] = False
        return self["auto_reload"]

    auto_reload = BoolProperty(
        name="Auto",
        description="Automatically reload images every few seconds",
        default=False,
        set=set_reload,
        get=get_reload
    )

    fill_lock_transform = BoolProperty(
        name="Lock Transforms",
        description="Filled faces keep current rotations",
        default=False,
    )

    axis_plane_display = EnumProperty(
        items=[
            ('OFF', "Off", "Always Off", "RADIOBUT_OFF", 1),
            ('ON', "On", "Always On", "RADIOBUT_ON", 2),
            ('MIDDLE_MOUSE', "View", "Only when changing view", "CAMERA_DATA", 3)
        ],
        name="Work Plane Cursor",
        description="Display mode of Work Plane Cursor",
        default='MIDDLE_MOUSE'
    )

    axis_plane_settings = BoolProperty(
        name="Axis Plane Settings",
        description="Show Work Plane Cursor settings",
        default=False
    )

    axis_plane_size = IntVectorProperty(
        name="Plane Size",
        description="Size of the Work Plane Cursor",
        size=2,
        default=(2, 2),
        min=1,
        soft_min=1
    )

    axis_plane_color = FloatVectorProperty(
        name="Plane Color",
        description="Color Work Plane Cursor is drawn with",
        size=3,
        default=(0.7, 0.7, 0.7),
        subtype='COLOR'
    )

    fill_plane_size = IntVectorProperty(
        name="Fill Plane Size",
        description="Size of the Fill Plane",
        size=2,
        default=(10, 10),
        min=1,
        soft_min=1
    )


class SprytileMaterialGridSettings(bpy.types.PropertyGroup):
    mat_id = StringProperty(
        name="Material Id",
        description="Name of the material this grid references",
        default=""
    )
    id = IntProperty(
        name="Grid ID",
        default=-1
    )
    name = StringProperty(
        name="Grid Name"
    )
    grid = IntVectorProperty(
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
            self["padding"] = (0, 0)
        return self["padding"]

    padding = IntVectorProperty(
        name="Padding",
        description="Cell padding, in pixels",
        min=0,
        size=2,
        subtype='XYZ',
        default=(0, 0),
        set=set_padding,
        get=get_padding
    )

    margin = IntVectorProperty(
        name="Margin",
        description="Spacing between tiles (top, right, bottom, left)",
        min=0,
        size=4,
        subtype='XYZ',
        default=(0, 0, 0, 0)
    )
    offset = IntVectorProperty(
        name="Offset",
        description="Offset of the grid",
        subtype='TRANSLATION',
        size=2,
        default=(0, 0)
    )
    rotate = FloatProperty(
        name="UV Rotation",
        description="Rotation of UV grid",
        subtype='ANGLE',
        unit='ROTATION',
        default=0.0
    )
    tile_selection = IntVectorProperty(
        name="Tile Selection",
        size=4,
        default=(0, 0, 1, 1)
    )
    auto_pad = BoolProperty(
        name="Auto Pad",
        description="Apply a subpixel padding to tiles of this grid",
        default=True
    )
    auto_pad_offset = FloatProperty(
        name="Pad Offset",
        description="Subpixel padding amount",
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

    mat_id = StringProperty(
        name="Material Id",
        description="Name of the material this grid references",
        default=""
    )
    is_expanded = BoolProperty(
        default=True,
        description="Toggle tile material",
        get=get_expanded,
        set=set_expanded
    )
    grids = CollectionProperty(type=SprytileMaterialGridSettings)


class SprytileGridDisplay(bpy.types.PropertyGroup):
    mat_id = StringProperty(default="")
    grid_id = IntProperty(default=-1)

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

    mat_name = StringProperty(
        get=get_mat_name,
        set=set_mat_name
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

    display = bpy.props.CollectionProperty(type=SprytileGridDisplay)
    idx = IntProperty(
        default=0,
        get=get_idx,
        set=set_idx
    )


class SprytilePropsSetup(bpy.types.Operator):
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


class SprytilePropsTeardown(bpy.types.Operator):
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

    preview_transparency = bpy.props.FloatProperty(
        name="Preview Alpha",
        description="Transparency level of build preview cursor",
        default=0.8,
        min=0,
        max=1
    )

    def set_picker(self, value):
        if "tile_picker_key" not in self.keys():
            self["tile_picker_key"] = 1
        if "tile_sel_move_key" not in self.keys():
            self["tile_sel_move_key"] = 2
        if value != self["tile_sel_move_key"]:
            self["tile_picker_key"] = value

    def get_picker(self):
        if "tile_picker_key" not in self.keys():
            self["tile_picker_key"] = 1
        return self["tile_picker_key"]

    tile_picker_key = EnumProperty(
        items=[
            ("Alt", "Alt", "Press Alt to pick tiles", 1),
            ("Ctrl", "Ctrl", "Press Ctrl to pick tiles", 2),
            ("Shift", "Shift", "Press Shift to pick tiles", 3)
        ],
        name="Tile Picker Key",
        description="Key for using the tile picker eyedropper",
        default='Alt',
        set=set_picker,
        get=get_picker
    )

    def set_sel_move(self, value):
        if "tile_picker_key" not in self.keys():
            self["tile_picker_key"] = 1
        if "tile_sel_move_key" not in self.keys():
            self["tile_sel_move_key"] = 2
        if value != self["tile_picker_key"]:
            self["tile_sel_move_key"] = value

    def get_sel_move(self):
        if "tile_sel_move_key" not in self.keys():
            self["tile_sel_move_key"] = 1
        return self["tile_sel_move_key"]

    tile_sel_move_key = EnumProperty(
        items=[
            ("Alt", "Alt", "Press Alt to move tile selection", 1),
            ("Ctrl", "Ctrl", "Press Ctrl to move tile selection", 2),
            ("Shift", "Shift", "Press Shift to move tile selection", 3)
        ],
        name="Tile Selection Move Key",
        description="Key for moving the tile selection",
        default='Ctrl',
        set=set_sel_move,
        get=get_sel_move
    )

    # addon updater preferences
    auto_check_update = bpy.props.BoolProperty(
        name="Auto-check for Update",
        description="If enabled, auto-check for updates using an interval",
        default=False,
    )
    updater_intrval_months = bpy.props.IntProperty(
        name='Months',
        description="Number of months between checking for updates",
        default=0,
        min=0
    )
    updater_intrval_days = bpy.props.IntProperty(
        name='Days',
        description="Number of days between checking for updates",
        default=7,
        min=0,
    )
    updater_intrval_hours = bpy.props.IntProperty(
        name='Hours',
        description="Number of hours between checking for updates",
        default=0,
        min=0,
        max=23
    )
    updater_intrval_minutes = bpy.props.IntProperty(
        name='Minutes',
        description="Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59
    )

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "preview_transparency")

        box = layout.box()
        box.label("Keyboard Shortcuts")
        box.prop(self, "tile_picker_key")
        box.prop(self, "tile_sel_move_key")

        kc = bpy.context.window_manager.keyconfigs.user
        km = kc.keymaps['Mesh']
        kmi_idx = km.keymap_items.find('sprytile.modal_tool')
        if kmi_idx >= 0:
            box.label(text="Tile Mode Shortcut")
            col = box.column()

            kmi = km.keymap_items[kmi_idx]
            km = km.active()
            col.context_pointer_set("keymap", km)
            rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)

        addon_updater_ops.update_settings_ui(self, context)

def setup_keymap():
    km_array = sprytile_modal.SprytileModalTool.keymaps
    win_mgr = bpy.context.window_manager
    key_config = win_mgr.keyconfigs.addon

    keymap = key_config.keymaps.new(name='Mesh', space_type='EMPTY')
    km_array[keymap] = [
        keymap.keymap_items.new("sprytile.modal_tool", 'SPACE', 'PRESS', ctrl=True, shift=True)
    ]

    keymap = key_config.keymaps.new(name="Sprytile Paint Modal Map", space_type='EMPTY', region_type='WINDOW', modal=True)
    km_items = keymap.keymap_items
    km_array[keymap] = [
        km_items.new_modal('CANCEL', 'ESC', 'PRESS'),
        km_items.new_modal('SNAP', 'S', 'ANY'),
        km_items.new_modal('FOCUS', 'W', 'PRESS'),
        km_items.new_modal('ROTATE_LEFT', 'ONE', 'PRESS'),
        km_items.new_modal('ROTATE_RIGHT', 'TWO', 'PRESS'),
        km_items.new_modal('FLIP_X', 'THREE', 'PRESS'),
        km_items.new_modal('FLIP_Y', 'FOUR', 'PRESS')
    ]
    sprytile_modal.SprytileModalTool.modal_values = [
        'Cancel',
        'Cursor Snap',
        'Cursor Focus',
        'Rotate Left',
        'Rotate Right',
        'Flip X',
        'Flip Y'
    ]


def teardown_keymap():
    for keymap in sprytile_modal.SprytileModalTool.keymaps:
        kmi_list = keymap.keymap_items
        for keymap_item in kmi_list:
            keymap.keymap_items.remove(keymap_item)
    sprytile_modal.SprytileModalTool.keymaps.clear()


def register():
    addon_updater_ops.register(bl_info)

    sprytile_panel.icons = bpy.utils.previews.new()
    dirname = os.path.dirname(__file__)
    icon_names = ('SPRYTILE_ICON_BUILD',
                  'SPRYTILE_ICON_PAINT',
                  'SPRYTILE_ICON_FILL',
                  'SPRYTILE_ICON_NORMAL')
    icon_paths = ('icon-build.png',
                  'icon-paint.png',
                  'icon-fill.png',
                  'icon-setnormal.png')

    for i in range(0, len(icon_names)):
        icon_path = os.path.join(dirname, "icons")
        icon_path = os.path.join(icon_path, icon_paths[i])
        sprytile_panel.icons.load(icon_names[i], icon_path, 'IMAGE')

    bpy.utils.register_class(sprytile_panel.SprytilePanel)
    bpy.utils.register_module(__name__)
    SprytilePropsSetup.props_setup()
    setup_keymap()


def unregister():
    teardown_keymap()
    SprytilePropsTeardown.props_teardown()
    bpy.utils.unregister_class(sprytile_panel.SprytilePanel)
    bpy.utils.unregister_module(__name__)

    bpy.utils.previews.remove(sprytile_panel.icons)

    # Unregister self from sys.path as well
    cmd_subfolder = os.path.realpath(os.path.abspath(os.path.split(inspect.getfile(inspect.currentframe()))[0]))
    sys.path.remove(cmd_subfolder)


if __name__ == "__main__":
    register()
