import bpy
import bmesh
from bpy_extras import view3d_utils
from mathutils.bvhtree import BVHTree

def ray_cast(self, context, event):
    """Run this function on left mouse, execute the ray cast"""
    if self.tree is None:
        return
    if context.object.type != 'MESH':
        return

    # get the context arguments
    scene = context.scene
    region = context.region
    rv3d = context.region_data
    coord = event.mouse_region_x, event.mouse_region_y

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

    ray_target = ray_origin + view_vector

    def obj_ray_cast(obj, matrix):
        """Wrapper for ray casting that moves the ray into object space"""

        # get the ray relative to the object
        matrix_inv = matrix.inverted()
        ray_origin_obj = matrix_inv * ray_origin
        ray_target_obj = matrix_inv * ray_target
        ray_direction_obj = ray_target_obj - ray_origin_obj

        location, normal, face_index, distance = self.tree.ray_cast(ray_origin_obj, ray_direction_obj)

        if location is None:
            return None, None, None, None
        else:
            return location, normal, face_index, distance

    obj = context.object
    matrix = obj.matrix_world.copy()

    location, normal, face_index, distance = obj_ray_cast(obj, matrix)
    if face_index is not None:
        hit_world = matrix * location
        scene.cursor_location = hit_world

class SprytileModalTool(bpy.types.Operator):
    """Modal object selection with a ray cast"""
    bl_idname = "sprytile.modal_tool"
    bl_label = "Tile Paint"

    def modal(self, context, event):
        print(event.type)
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'LEFTMOUSE':
            self.left_down = event.value == 'PRESS'
            ray_cast(self, context, event)
            return {'RUNNING_MODAL'}
        elif event.type == 'MOUSEMOVE' and self.left_down:
            ray_cast(self, context, event)
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.tree = None
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            context.window_manager.modal_handler_add(self)

            obj = context.object
            if obj.hide or obj.type != 'MESH':
                self.report({'WARNING'}, "Active object must be a visible mesh")
                return {'CANCELLED'}

            self.left_down = False
            self.tree = BVHTree.FromObject(context.object, context.scene)

            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

def register():
    bpy.utils.register_module(__name__)

def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
