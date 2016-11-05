import bgl
import bpy
import bmesh
import math
from . import sprytile_gui
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_plane
from mathutils.bvhtree import BVHTree

def ray_cast(self, context, event):
    # Don't do anything if nothing to raycast on
    # or the GL GUI is using the mouse
    if self.tree is None or self.gui_use_mouse is True:
        return
    if context.object.type != 'MESH':
        return

    # get the context arguments
    scene = context.scene
    region = context.region
    rv3d = context.region_data
    coord = Vector((event.mouse_region_x, event.mouse_region_y))

    if coord.x < 0 or coord.y < 0:
        return False
    if coord.x > region.width or coord.y > region.height:
        return False

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

    # Repurpose view vector, now get it from center of screen
    # To get view camera forward vector
    coord = int(region.width/2), int(region.height/2)
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    plane_normal = scene.sprytile_data.paint_normal_vector
    up_vector = scene.sprytile_data.paint_up_vector

    if scene.sprytile_data.normal_mode == 'X':
        plane_normal = Vector((1.0, 0.0, 0.0))
        up_vector = Vector((0.0, 0.0, 1.0))
    elif scene.sprytile_data.normal_mode == 'Y':
        plane_normal = Vector((0.0, 1.0, 0.0))
        up_vector = Vector((0.0, 0.0, 1.0))
    elif scene.sprytile_data.normal_mode == 'Z':
        plane_normal = Vector((0.0, 0.0, 1.0))
        up_vector = Vector((0.0, 1.0, 0.0))

    plane_normal.normalize()
    up_vector.normalize()

    if plane_normal.dot(view_vector) > 0:
        plane_normal *= -1
    right_vector = up_vector.cross(plane_normal)

    plane_pos = intersect_line_plane(ray_origin, ray_target, scene.cursor_location, plane_normal)
    # Intersected with the normal plane...
    if plane_pos is not None:
        world_pixels = scene.sprytile_data.world_pixels
        target_mat = bpy.data.materials[context.object.sprytile_matid]
        grid_x = target_mat.sprytile_mat_grid_x
        grid_y = target_mat.sprytile_mat_grid_y

        face_position, x_vector, y_vector = get_grid_pos(plane_pos, scene.cursor_location,
                                                        right_vector.copy(), up_vector.copy(),
                                                        world_pixels, grid_x, grid_y)
        print("pos: ", face_position, "\nx_vector: ", x_vector, "\ny_vector: ", y_vector)
        print("right/x: ", right_vector, "\nup/y: ", up_vector)
        # Convert world space position to object space
        face_position = context.object.matrix_world.copy().inverted() * face_position;

        x_dot = right_vector.dot(x_vector.normalized())
        y_dot = up_vector.dot(y_vector.normalized())
        x_positive = x_dot > 0
        y_positive = y_dot > 0
        print("X dot:", x_dot, "\nY dot", y_dot)

        bm = bmesh.from_edit_mesh(context.object.data)

        vtx1 = bm.verts.new(face_position)
        vtx2 = bm.verts.new(face_position + y_vector)
        vtx3 = bm.verts.new(face_position + x_vector + y_vector)
        vtx4 = bm.verts.new(face_position + x_vector)

        # Quadrant II, IV
        face = (vtx1, vtx2, vtx3, vtx4)
        # Quadrant I, III
        if x_positive == y_positive:
            face = (vtx1, vtx4, vtx3, vtx2)

        bm.faces.new(face)
        bmesh.update_edit_mesh(context.object.data)

        # Update the collision BVHTree with new data
        self.tree = BVHTree.FromBMesh(bm)
        # Save the last normal and up vector
        scene.sprytile_data.paint_normal_vector = plane_normal
        scene.sprytile_data.paint_up_vector = up_vector
        print("Build face")

def get_grid_pos(position, grid_center, right_vector, up_vector, world_pixels, grid_x, grid_y):

    position_vector = position - grid_center
    pos_vector_normalized = position.normalized()

    if right_vector.dot(pos_vector_normalized) < 0:
        right_vector *= -1
    if up_vector.dot(pos_vector_normalized) < 0:
        up_vector *= -1

    x_magnitude = position_vector.dot(right_vector)
    y_magnitude = position_vector.dot(up_vector)

    x_unit = grid_x / world_pixels
    y_unit = grid_y / world_pixels

    x_snap = math.floor(x_magnitude / x_unit)
    y_snap = math.floor(y_magnitude / y_unit)

    right_vector *= x_unit
    up_vector *= y_unit

    grid_pos = grid_center + (right_vector * x_snap) + (up_vector * y_snap)

    return grid_pos, right_vector, up_vector

class SprytileModalTool(bpy.types.Operator):
    """Tile based mesh creation/UV layout tool"""
    bl_idname = "sprytile.modal_tool"
    bl_label = "Tile Paint"

    def find_scene_view(self, context):
        # Find the nearest world axis to the view axis
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = int(region.width/2), int(region.height/2)

        # get the ray from the viewport and mouse
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        if scene.sprytile_data.lock_normal is False:
            x_dot = 1 - abs(view_vector.dot( Vector((1.0, 0.0, 0.0)) ))
            y_dot = 1 - abs(view_vector.dot( Vector((0.0, 1.0, 0.0)) ))
            z_dot = 1 - abs(view_vector.dot( Vector((0.0, 0.0, 1.0)) ))
            dot_array = [x_dot, y_dot, z_dot]
            closest = min(dot_array)
            if closest is dot_array[0]:
                scene.sprytile_data.normal_mode = 'X'
            elif closest is dot_array[1]:
                scene.sprytile_data.normal_mode = 'Y'
            else:
                scene.sprytile_data.normal_mode = 'Z'

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            self.find_scene_view(context)
            return {'PASS_THROUGH'}
        elif event.type == 'LEFTMOUSE':
            self.gui_event = event
            self.left_down = event.value == 'PRESS'
            if self.left_down:
                if ray_cast(self, context, event) is False:
                    print("Passing left click through")
                    return {'PASS_THROUGH'}
            return {'RUNNING_MODAL'}
        elif event.type == 'MOUSEMOVE':
            self.gui_event = event
            if self.left_down:
                ray_cast(self, context, event)
                return {'RUNNING_MODAL'}
            self.find_scene_view(context)
        elif event.type in {'RIGHTMOUSE', 'ESC'} and self.gui_use_mouse is False:
            self.exit_modal()
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            obj = context.object
            if obj.hide or obj.type != 'MESH':
                self.report({'WARNING'}, "Active object must be a visible mesh")
                return {'CANCELLED'}

            # Set up for raycasting with a BVHTree
            self.left_down = False
            self.tree = BVHTree.FromObject(context.object, context.scene)

            # Set up GL draw callbacks, communication between modal and GUI
            self.gui_event = None
            self.gui_use_mouse = False
            gui_args = (self, context)
            self.glHandle = bpy.types.SpaceView3D.draw_handler_add(sprytile_gui.draw_gui, gui_args, 'WINDOW', 'POST_PIXEL')

            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

    def exit_modal(self):
        self.tree = None
        self.gui_event = None
        self.gui_use_mouse = False
        bpy.types.SpaceView3D.draw_handler_remove(self.glHandle, 'WINDOW')

def register():
    bpy.utils.register_module(__name__)

def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == '__main__':
    register()
