#    Addon info
bl_info = {
  "name": "Sprytile Painter",
  'author': 'Jeiel Aranal',
  "location": "View3D > UI panel > Add meshes",
  "category": "Paint"
  }

if "bpy" in locals():
    import imp
    imp.reload(sprytile_modal)
    imp.reload(sprytile_panel)
else:
    from . import sprytile_modal, sprytile_panel

import bpy

def register():
  print ("Registering ", __name__)
  bpy.utils.register_module(__name__)

def unregister():
  print ("Unregistering ", __name__)
  bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
  register()
