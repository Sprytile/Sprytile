#    Addon info
bl_info = {
    "name": "Sprytile Painter",
    "author": "Jeiel Aranal",
    "location": "View3D > UI panel > Add meshes",
    "category": "Paint"
    }

if "bpy" in locals():
    import imp
    imp.reload(sprytile_gui)
    imp.reload(sprytile_modal)
    imp.reload(sprytile_panel)
else:
    from . import sprytile_gui, sprytile_modal, sprytile_panel

import bpy
from bpy.props import EnumProperty, IntProperty, FloatVectorProperty

def setup_props():
    # Scene properties
    bpy.types.Scene.sprytile_normalmode = EnumProperty(
        items = [
            ("X",           "X",    "World X-Axis",     1),
            ("Y",           "Y",    "World Y-Axis",     2),
            ("Z",           "Z",    "World X-Axis",     3),
            ("LAST_NORMAL", "Last", "Last Used Normal", 4)
        ],
        name = "Normal Mode",
        description = "Normal to create the mesh on",
        default = 'Z'
    )

    bpy.types.Scene.sprytile_paintmode = EnumProperty(
        items = [
            ("PAINT",       "Paint",        "", 1),
            ("MAKE_FACE",   "Build",        "Only create new faces", 3),
            ("SET_NORMAL",  "Set Normal",   "Select a normal to use for face creation", 2)
        ],
        name = "Sprytile Paint Mode",
        description = "Paint mode",
        default = 'PAINT'
    )
    bpy.types.Scene.sprytile_normal_data = FloatVectorProperty(
        name = "Srpytile Last Paint Normal",
        description = "Last saved painting normal used by Sprytile",
        default = (0.0, 0.0, 1.0)
    )
    bpy.types.Scene.sprytile_upvector_data = FloatVectorProperty(
        name = "Sprytile Last Paint Up Vector",
        description = "Last saved painting up vector used by Srpytile",
        default = (0.0, 1.0, 0.0)
    )
    bpy.types.Scene.sprytile_world_pixels = IntProperty(
        name = "World Pixel Density",
        description = "How many pixels are displayed in one world unit",
        default = 32,
        min = 8,
        max = 2048
    )

    # Object properties
    bpy.types.Object.sprytile_matid = IntProperty(
        name = "Material ID",
        description = "Material index used for object"
    )
    bpy.types.Material.sprytile_mat_grid_x = IntProperty(
        name = "Width",
        description = "Texture grid width, in pixels",
        min = 8,
        max = 2048,
        default = 32
    )
    bpy.types.Material.sprytile_mat_grid_y = IntProperty(
        name = "Height",
        description = "Texture grid height, in pixels",
        min = 8,
        max = 2048,
        default = 32
    )

def teardown_props():
    del bpy.types.Scene.sprytile_normalmode
    del bpy.types.Scene.sprytile_paintmode
    del bpy.types.Scene.sprytile_normal_data
    del bpy.types.Scene.sprytile_upvector_data
    del bpy.types.Scene.sprytile_world_pixels

    del bpy.types.Object.sprytile_matid
    del bpy.types.Material.sprytile_mat_grid_x
    del bpy.types.Material.sprytile_mat_grid_y

def register():
    bpy.utils.register_module(__name__)
    setup_props()

def unregister():
    bpy.utils.unregister_module(__name__)
    teardown_props()

if __name__ == "__main__":
    register()
