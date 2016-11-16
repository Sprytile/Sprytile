bl_info = {
    "name": "Sprytile Painter",
    "author": "Jeiel Aranal",
    "version": (0, 1, 0),
    "blender": (2, 7, 0),
    "description": "A utility for creating tile based low spec scenes with paint/map editor tools",
    "location": "View3D > UI panel > Sprytile",
    "tracker_url": "https://github.com/ChemiKhazi/Sprytile/issues",
    "category": "Paint"
}

if "bpy" in locals():
    import imp

    imp.reload(sprytile_gui)
    imp.reload(sprytile_modal)
    imp.reload(sprytile_panel)
    imp.reload(sprytile_utils)
else:
    from . import sprytile_gui, sprytile_modal, sprytile_panel, sprytile_utils

import bpy
from bpy.props import *


class SprytileSceneSettings(bpy.types.PropertyGroup):
    def set_normal(self, value):
        if self.lock_normal is True:
            return
        self["normal_mode"] = value

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
        description="Normal to create the mesh on",
        default='Z',
        set=set_normal,
        get=get_normal
    )

    lock_normal = BoolProperty(
        name="Lock",
        description="Lock normal used to create meshes",
        default=False
    )

    paint_mode = EnumProperty(
        items=[
            ("PAINT", "Paint", "", 1),
            ("MAKE_FACE", "Build", "Only create new faces", 3),
            ("SET_NORMAL", "Set Normal", "Select a normal to use for face creation", 2)
        ],
        name="Sprytile Paint Mode",
        description="Paint mode",
        default='MAKE_FACE'
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
        default=False
    )
    uv_flip_y = BoolProperty(
        name="Flip Y",
        default=False
    )
    mesh_rotate = FloatProperty(
        name="Grid Rotation",
        description="Rotation of mesh creation",
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

    is_running = BoolProperty(
        name="Sprytile Running",
        description="Is Sprytile modal tool currently running"
    )
    is_snapping = BoolProperty(
        name="Is Cursor Snap",
        description="Is cursor snapping currently activated"
    )


class SprytileMaterialGridSettings(bpy.types.PropertyGroup):
    mat_id = StringProperty(
        name="Material Id",
        description="Name of the material this grid references",
        default=""
    )
    is_main = BoolProperty(
        name="Main grid flag",
        default=False
    )
    name = StringProperty(
        name="Grid Name"
    )
    grid = IntVectorProperty(
        name="Size",
        description="Grid size, in pixels",
        min=2,
        size=2,
        subtype='XYZ',
        default=(32, 32)
    )
    offset = IntVectorProperty(
        name="Offset",
        description="Offset of the grid",
        subtype='TRANSLATION',
        size=2,
        default=(0, 0)
    )
    rotate = FloatProperty(
        name="Grid Rotation",
        description="Rotation of the grid",
        subtype='ANGLE',
        unit='ROTATION',
        default=0.0
    )
    tile_selection = IntVectorProperty(
        name="Tile Selection",
        size=4,
        default=(0, 0, 1, 1)
    )
    show_extra = BoolProperty(
        name="Extra UV Grid Settings",
        default=False
    )


def setup_props():
    bpy.types.Scene.sprytile_data = bpy.props.PointerProperty(type=SprytileSceneSettings)
    bpy.types.Scene.sprytile_grids = bpy.props.CollectionProperty(type=SprytileMaterialGridSettings)

    bpy.types.Scene.sprytile_ui = bpy.props.PointerProperty(type=sprytile_gui.SprytileGuiData)

    bpy.types.Object.sprytile_gridid = IntProperty(
        name="Grid ID",
        description="Grid index used for object"
    )


def teardown_props():
    del bpy.types.Scene.sprytile_data
    del bpy.types.Scene.sprytile_grids
    del bpy.types.Scene.sprytile_ui
    del bpy.types.Object.sprytile_gridid

addon_keymaps = []


def setup_keymap():
    win_mgr = bpy.context.window_manager
    key_config = win_mgr.keyconfigs.addon
    km = key_config.keymaps.new(name='Mesh', space_type='EMPTY')
    km.keymap_items.new("sprytile.modal_tool", 'SPACE', 'PRESS', ctrl=True, shift=True)
    addon_keymaps.append(km)


def teardown_keymap():
    win_mgr = bpy.context.window_manager
    for keymap in addon_keymaps:
        win_mgr.keyconfigs.addon.keymaps.remove(keymap)
    addon_keymaps.clear()


def register():
    bpy.utils.register_module(__name__)
    setup_props()
    setup_keymap()


def unregister():
    bpy.utils.unregister_module(__name__)
    teardown_props()
    teardown_keymap()


if __name__ == "__main__":
    register()
