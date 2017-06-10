import bpy
from mathutils import Vector, Matrix, Quaternion
from mathutils.geometry import distance_point_to_plane

import sprytile_utils
import sprytile_uv


def get_build_vertices(position, x_vector, y_vector, up_vector, right_vector):
    """Get the world position vertices for a new face, at the given position"""
    x_dot = right_vector.dot(x_vector.normalized())
    y_dot = up_vector.dot(y_vector.normalized())
    x_positive = x_dot > 0
    y_positive = y_dot > 0

    # These are in world positions
    vtx1 = position
    vtx2 = position + y_vector
    vtx3 = position + x_vector + y_vector
    vtx4 = position + x_vector

    # Quadrant II, IV
    face_order = (vtx1, vtx2, vtx3, vtx4)
    # Quadrant I, III
    if x_positive == y_positive:
        face_order = (vtx1, vtx4, vtx3, vtx2)

    return face_order


class ToolBuild:
    modal = None
    left_down = False

    def __init__(self, modal, rx_source):
        self.modal = modal
        rx_source.filter(
            lambda modal_evt: modal_evt.paint_mode == 'MAKE_FACE'
        ).subscribe(
            on_next=lambda modal_evt: self.process_tool(modal_evt),
            on_error=lambda err: self.handle_error(err),
            on_completed=lambda: self.handle_complete()
        )

    def process_tool(self, modal_evt):
        if self.modal.rx_data is None:
            return

        # get the context arguments
        context = self.modal.rx_data.context
        scene = context.scene
        ray_origin = self.modal.rx_data.ray_origin
        ray_vector = self.modal.rx_data.ray_vector

        if modal_evt.left_down:
            self.left_down = True
            self.execute(context, scene, ray_origin, ray_vector)
        elif self.left_down:
            self.left_down = False
            bpy.ops.ed.undo_push()

        if modal_evt.build_preview:
            self.build_preview(context, scene, ray_origin, ray_vector)

    def execute(self, context, scene, ray_origin, ray_vector):
        grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])

        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene)
        hit_loc, hit_normal, face_index, hit_dist = self.modal.raycast_object(context.object, ray_origin, ray_vector)

        # Used to move raycast slightly along ray vector
        shift_vec = ray_vector.normalized() * 0.001

        # If raycast hit the mesh...
        if face_index is not None:
            # The face is valid for painting if hit face
            # is facing same way as plane normal and is coplanar to target plane
            check_dot = abs(plane_normal.dot(hit_normal))
            check_dot -= 1
            check_coplanar = distance_point_to_plane(hit_loc, scene.cursor_location, plane_normal)

            check_coplanar = abs(check_coplanar) < 0.05
            check_dot = abs(check_dot) < 0.05
            # Hit a face that is valid for painting
            if check_dot and check_coplanar:
                self.modal.add_virtual_cursor(hit_loc)
                # Change UV of this face instead
                face_up, face_right = self.modal.get_face_up_vector(context, face_index)
                if face_up is not None and face_up.dot(up_vector) < 0.95:
                    data = context.scene.sprytile_data
                    rotate_matrix = Matrix.Rotation(data.mesh_rotate, 4, hit_normal)
                    up_vector = rotate_matrix * face_up
                    right_vector = rotate_matrix * face_right
                sprytile_uv.uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.modal.bmesh)
                if scene.sprytile_data.cursor_flow:
                    self.modal.flow_cursor(context, face_index, hit_loc)
                return

        # Raycast did not hit the mesh, raycast to the virtual grid
        face_position, x_vector, y_vector, plane_cursor = sprytile_utils.raycast_grid(
            scene, context,
            up_vector, right_vector, plane_normal,
            ray_origin, ray_vector
        )
        # Failed to hit the grid
        if face_position is None:
            return

        # If raycast hit mesh, compare distance of grid hit and mesh hit
        if hit_loc is not None:
            grid_hit_dist = (face_position - ray_origin).magnitude
            # Mesh hit closer than grid hit, don't do anything
            if hit_dist < grid_hit_dist:
                return

        # store plane_cursor, for deciding where to move actual cursor if auto cursor mode is on
        self.modal.add_virtual_cursor(plane_cursor)
        # Build face and UV map it
        face_vertices = get_build_vertices(face_position, x_vector, y_vector, up_vector, right_vector)
        face_index = self.modal.create_face(context, face_vertices)

        face_up, face_right = self.modal.get_face_up_vector(context, face_index)
        if face_up is not None and face_up.dot(up_vector) < 0.95:
            data = context.scene.sprytile_data
            rotate_matrix = Matrix.Rotation(data.mesh_rotate, 4, plane_normal)
            up_vector = rotate_matrix * face_up
            right_vector = rotate_matrix * face_right

        sprytile_uv.uv_map_face(context, up_vector, right_vector, tile_xy, face_index, self.modal.bmesh)

        if scene.sprytile_data.auto_merge:
            face = self.modal.bmesh.faces[face_index]
            face.select = True
            # Find the face center, to raycast from later
            face_center = context.object.matrix_world * face.calc_center_bounds()
            # Move face center back a little for ray casting
            face_center -= shift_vec

            threshold = (1 / context.scene.sprytile_data.world_pixels) * 2
            bpy.ops.mesh.remove_doubles(threshold=threshold, use_unselected=True)

            for el in [self.modal.bmesh.faces, self.modal.bmesh.verts, self.modal.bmesh.edges]:
                el.index_update()
                el.ensure_lookup_table()

            # Modified the mesh, refresh and raycast to find the new face index
            self.modal.update_bmesh_tree(context)
            loc, norm, new_face_idx, hit_dist = self.modal.raycast_object(context.object, face_center, ray_vector)
            if new_face_idx is not None:
                self.modal.bmesh.faces[new_face_idx].select = False
                face_index = new_face_idx
            else:
                face_index = -1

        # Auto merge refreshes the mesh automatically
        self.modal.refresh_mesh = not scene.sprytile_data.auto_merge

        if scene.sprytile_data.cursor_flow and face_index is not None and face_index > -1:
            self.modal.flow_cursor(context, face_index, plane_cursor)

    def build_preview(self, context, scene, ray_origin, ray_vector):
        obj = context.object
        data = scene.sprytile_data

        grid_id = obj.sprytile_gridid
        target_grid = sprytile_utils.get_grid(context, grid_id)

        target_img = sprytile_utils.get_grid_texture(obj, target_grid)
        if target_img is None:
            return

        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene, False)

        # Raycast to the virtual grid
        face_position, x_vector, y_vector, plane_cursor = sprytile_utils.raycast_grid(
            scene, context,
            up_vector, right_vector, plane_normal,
            ray_origin, ray_vector
        )

        if face_position is None:
            return

        preview_verts = get_build_vertices(face_position, x_vector, y_vector,
                                           up_vector, right_vector)

        # Get the center of the preview verts
        vtx_center = Vector((0, 0, 0))
        for vtx in preview_verts:
            vtx_center += vtx
        vtx_center /= len(preview_verts)

        rotate_normal = plane_normal

        rotation = Quaternion(rotate_normal, data.mesh_rotate)
        up_vector = rotation * up_vector
        right_vector = rotation * right_vector

        up_vector.normalize()
        right_vector.normalize()

        tile_xy = (target_grid.tile_selection[0], target_grid.tile_selection[1])
        preview_uvs = sprytile_uv.get_uv_positions(data, target_img.size, target_grid,
                                                   up_vector, right_vector, tile_xy,
                                                   preview_verts, vtx_center)

        self.modal.set_preview_data(preview_verts, preview_uvs)

    def handle_error(self, err):
        print("Error in build mode: {0}".format(err))
        pass

    def handle_complete(self):
        pass


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)


if __name__ == '__main__':
    register()
