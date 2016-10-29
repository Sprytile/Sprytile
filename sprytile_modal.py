import bpy
import bmesh
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_plane
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
        # if paint mode is set normal, save the normal of the hit
        # set normal mode to last, switch paint mode back to paint then do nothing

        # Change the uv of the given face
        print("Hitting face index ", face_index)
        # hit_world = matrix * location
        # scene.cursor_location = hit_world
    else:
        # Didn't hit a face on this position, build a face
        build_face(self, context, event)

def build_face(self, context, event):
    # Build face depending on view

    # get the context arguments
    scene = context.scene
    region = context.region
    rv3d = context.region_data
    coord = event.mouse_region_x, event.mouse_region_y

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

    ray_target = ray_origin + view_vector

    def get_ray_plane_intersection(ray_origin, ray_direction, plane_point, plane_normal):
        d = ray_direction.dot(plane_normal)
        if abs(ray_direction.dot(plane_normal)) <= 0.00000001:
            return None
        return (plane_point-ray_origin).dot(plane_normal) / d

    camera_vector = rv3d.view_rotation * Vector((0.0, 0.0, -1.0))
    camera_vector.normalize()

    plane_normal = scene.sprytile_normal_data
    if scene.sprytile_normalmode == 'X':
        plane_normal = Vector((1.0, 0.0, 0.0))
    elif scene.sprytile_normalmode == 'Y':
        plane_normal = Vector((0.0, 1.0, 0.0))
    elif scene.sprytile_normalmode == 'Z':
        plane_normal = Vector((0.0, 0.0, 1.0))

    plane_pos = intersect_line_plane(ray_origin, ray_origin + ray_target, scene.cursor_location, plane_normal)
    if plane_pos is not None:
        print(plane_pos)

class SprytileModalTool(bpy.types.Operator):
    """Modal object selection with a ray cast"""
    bl_idname = "sprytile.modal_tool"
    bl_label = "Tile Paint"

    def modal(self, context, event):
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
