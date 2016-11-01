import bpy
import bmesh
import math
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

    plane_normal = scene.sprytile_normal_data
    up_vector = scene.sprytile_upvector_data
    # When calculating up vector for normal data,
    # dot compare with other X/Y/Z normals, whichever closer
    if scene.sprytile_normalmode == 'X':
        plane_normal = Vector((1.0, 0.0, 0.0))
        up_vector = Vector((0.0, 0.0, 1.0))
    elif scene.sprytile_normalmode == 'Y':
        plane_normal = Vector((0.0, 1.0, 0.0))
        up_vector = Vector((0.0, 0.0, 1.0))
    elif scene.sprytile_normalmode == 'Z':
        plane_normal = Vector((0.0, 0.0, 1.0))
        up_vector = Vector((0.0, 1.0, 0.0))

    plane_normal.normalize()
    up_vector.normalize()

    plane_pos = intersect_line_plane(ray_origin, ray_origin + ray_target, scene.cursor_location, plane_normal)
    # Intersected with the normal plane...
    if plane_pos is not None:
        world_pixels = scene.sprytile_world_pixels
        target_mat = bpy.data.materials[context.object.sprytile_matid]
        grid_x = target_mat.sprytile_mat_grid_x
        grid_y = target_mat.sprytile_mat_grid_y

        face_position, x_vector, y_vector = get_grid_pos(plane_pos, scene.cursor_location,
                                                        plane_normal, up_vector,
                                                        world_pixels, grid_x, grid_y)

        bm = bmesh.from_edit_mesh(context.object.data)
        print(bm.verts)
        bm.faces.new((
            bm.verts.new(face_position),
            bm.verts.new(face_position + y_vector),
            bm.verts.new(face_position + x_vector + y_vector),
            bm.verts.new(face_position + x_vector)
        ))
        bmesh.update_edit_mesh(context.object.data)

def get_grid_pos(position, grid_center, normal, up_vector, world_pixels, grid_x, grid_y):
    print("Input position:", position)
    right_vector = normal.cross(up_vector)

    position_vector = position - grid_center
    x_magnitude = position_vector.dot(right_vector)
    y_magnitude = position_vector.dot(up_vector)

    x_unit = grid_x / world_pixels
    y_unit = grid_y / world_pixels

    x_snap = round(x_magnitude / x_unit)
    y_snap = round(y_magnitude / y_unit)

    grid_pos = grid_center + (right_vector * x_snap) + (up_vector * y_snap)
    print("Output position", grid_pos)
    return grid_pos, x_unit * right_vector, y_unit * up_vector

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
