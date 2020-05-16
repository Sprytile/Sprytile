import bpy
from math import floor, ceil
from mathutils import Vector, Quaternion
from mathutils.geometry import distance_point_to_plane

import sprytile_utils
import sprytile_uv
import sprytile_preview

class ToolBuild:
    modal = None
    left_down = False
    start_coord = None
    can_build = False

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
            is_start = self.left_down is False
            self.left_down = True
            self.execute(context, scene, ray_origin, ray_vector, is_start)
        elif self.left_down:
            self.left_down = False
            self.start_coord = None
            # self.modal.virtual_cursor.clear()
            bpy.ops.ed.undo_push()

        #if modal_evt.build_preview:
        #    self.build_preview(context, scene, ray_origin, ray_vector)

    def execute(self, context, scene, ray_origin, ray_vector, is_start):
        data = scene.sprytile_data
        grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
        tile_xy = (grid.tile_selection[0], grid.tile_selection[1])

        # Get vectors for grid, without rotation
        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(
            scene,
            with_rotation=False
        )
        # If building on decal layer, modify plane normal to the one under mouse
        if data.work_layer == 'DECAL_1' and data.lock_normal is False:

            location, hit_normal, face_index, distance = self.modal.raycast_object(context.object,
                                                                                   ray_origin,
                                                                                   ray_vector)
            if hit_normal is not None:
                face_up, face_right = VIEW3D_OP_SprytileModalTool.get_face_up_vector(context, face_index, 0.4, bias_right=True)
                if face_up is not None and face_right is not None:
                    plane_normal = hit_normal
                    up_vector = face_up
                    right_vector = face_right

        # Rotate the vectors
        rotation = Quaternion(plane_normal, data.mesh_rotate)
        up_vector = rotation @ up_vector
        right_vector = rotation @ right_vector

        # raycast grid to get the grid position under the mouse
        grid_coord, grid_right, grid_up, plane_pos = sprytile_utils.raycast_grid(
            scene, context,
            up_vector, right_vector, plane_normal,
            ray_origin, ray_vector,
            as_coord=True
        )

        # Record starting grid position of stroke
        if is_start:
            self.start_coord = grid_coord
        # Not starting stroke, filter out when can build
        elif self.start_coord is not None:
            start_offset = (grid_coord[0] - self.start_coord[0],
                            grid_coord[1] - self.start_coord[1])
            coord_mod = (start_offset[0] % grid.tile_selection[2],
                         start_offset[1] % grid.tile_selection[3])
            # Isn't at exact position for grid made by tile selection, with start_coord as origin
            if coord_mod[0] > 0 or coord_mod[1] > 0:
                # Try to snap grid_coord
                tolerance_min = (floor(grid.tile_selection[2] * 0.25),
                                 floor(grid.tile_selection[3] * 0.25))
                tolerance_max = (grid.tile_selection[2] - tolerance_min[0],
                                 grid.tile_selection[3] - tolerance_min[1])
                allow_snap_x = tolerance_min[0] <= coord_mod[0] <= tolerance_max[0]
                allow_snap_y = tolerance_min[1] <= coord_mod[1] <= tolerance_max[1]

                # If neither x or y can be snapped, return
                if not allow_snap_x and not allow_snap_y:
                    return

                coord_frac = [start_offset[0] / grid.tile_selection[2],
                              start_offset[1] / grid.tile_selection[3]]
                if coord_mod[0] > (grid.tile_selection[2] / 2.0):
                    coord_frac[0] = ceil(coord_frac[0])
                else:
                    coord_frac[0] = floor(coord_frac[0])

                if coord_mod[1] > (grid.tile_selection[3] / 2.0):
                    coord_frac[1] = ceil(coord_frac[1])
                else:
                    coord_frac[1] = floor(coord_frac[1])
                grid_coord = (self.start_coord[0] + (coord_frac[0] * grid.tile_selection[2]),
                              self.start_coord[1] + (coord_frac[1] * grid.tile_selection[3]))

        # Get the area to build
        offset_tile_id, offset_grid, coord_min, coord_max = sprytile_utils.get_grid_area(
            grid.tile_selection[2],
            grid.tile_selection[3],
            data.uv_flip_x, data.uv_flip_y
        )

        # Check if joining multi tile faces
        grid_no_spacing = sprytile_utils.grid_no_spacing(grid)
        is_single_pixel = sprytile_utils.grid_is_single_pixel(grid)
        do_join = is_single_pixel
        if do_join is False:
            do_join = grid_no_spacing and data.auto_join
        
        # 1x1 tile selections cannot be auto joined
        tile_area = grid.tile_selection[2] * grid.tile_selection[3]
        if do_join and tile_area == 1:
            do_join = False

        # Store vertices of constructed faces for cursor flow
        faces_verts = []
        require_base_layer = data.work_layer != 'BASE'

        # Get the work layer filter, based on layer settings
        work_layer_mask = sprytile_utils.get_work_layer_data(data)

        # Build mode with join multi
        if do_join:
            origin_coord = ((grid_coord[0] + coord_min[0]),
                            (grid_coord[1] + coord_min[1]))

            size_x = (coord_max[0] - coord_min[0]) + 1
            size_y = (coord_max[1] - coord_min[1]) + 1

            tile_origin = (grid.tile_selection[0],
                           grid.tile_selection[1])
            tile_coord = (tile_origin[0] + grid.tile_selection[2],
                          tile_origin[1] + grid.tile_selection[3])

            face_index = self.modal.construct_face(context, origin_coord, [size_x, size_y],
                                                   tile_coord, tile_origin,
                                                   grid_up, grid_right,
                                                   up_vector, right_vector, plane_normal,
                                                   require_base_layer=require_base_layer,
                                                   work_layer_mask=work_layer_mask)
            if face_index is not None:
                face_verts = self.modal.face_to_world_verts(context, face_index)
                faces_verts.extend(face_verts)
        # Build mode without auto join, try operation on each build coordinate
        else:
            virtual_cursor = scene.cursor.location + \
                             (grid_coord[0] * grid_right) + \
                             (grid_coord[1] * grid_up)
            self.modal.add_virtual_cursor(virtual_cursor)
            # Loop through grid coordinates to build
            for i in range(len(offset_grid)):
                grid_offset = offset_grid[i]
                tile_offset = offset_tile_id[i]

                grid_pos = [grid_coord[0] + grid_offset[0], grid_coord[1] + grid_offset[1]]
                tile_pos = [tile_xy[0] + tile_offset[0], tile_xy[1] + tile_offset[1]]

                face_index = self.modal.construct_face(context, grid_pos, [1, 1],
                                                       tile_pos, tile_xy,
                                                       grid_up, grid_right,
                                                       up_vector, right_vector, plane_normal,
                                                       require_base_layer=require_base_layer,
                                                       work_layer_mask=work_layer_mask)
                if face_index is not None:
                    face_verts = self.modal.face_to_world_verts(context, face_index)
                    faces_verts.extend(face_verts)

        if plane_pos is not None:
            self.modal.add_virtual_cursor(plane_pos)

        if data.cursor_flow and data.work_layer == "BASE" and len(faces_verts) > 0:
            # Find which vertex the cursor should flow to
            new_cursor_pos = self.modal.flow_cursor_verts(context, faces_verts, plane_pos)
            if new_cursor_pos is not None:
                # Not base layer, move position back by offset
                if data.work_layer != 'BASE':
                    new_cursor_pos -= plane_normal * data.mesh_decal_offset
                # Calculate the world position of old start_coord
                old_start_pos = scene.cursor.location + (self.start_coord[0] * grid_right) + (self.start_coord[1] * grid_up)
                # find the offset of the old start position from the new cursor position
                new_start_offset = old_start_pos - new_cursor_pos
                # get how much the grid x/y vectors need to scale by to normalize
                scale_right = 1.0 / grid_right.magnitude
                scale_up = 1.0 / grid_up.magnitude
                # scale the offset by grid x/y, so can use normalized dot product to
                # find the grid coordinates the start position is from new cursor pos
                new_start_coord = Vector((
                    (new_start_offset * scale_right).dot(grid_right.normalized()),
                    (new_start_offset * scale_up).dot(grid_up.normalized())
                ))
                # Record the new offset starting coord,
                # for the nice painting snap
                self.start_coord = new_start_coord

                scene.cursor.location = new_cursor_pos

    @staticmethod
    def build_preview(context, scene, ray_origin, ray_vector):
        obj = context.object
        data = scene.sprytile_data

        grid_id = obj.sprytile_gridid
        target_grid = sprytile_utils.get_grid(context, grid_id)

        if target_grid is None:
            return

        # Reset can build flag
        ToolBuild.can_build = False
            
        target_img = sprytile_utils.get_grid_texture(obj, target_grid)
        if target_img is None:
            sprytile_preview.clear_preview_data()
            return

        # If building on base layer, get from current virtual grid
        up_vector, right_vector, plane_normal = sprytile_utils.get_current_grid_vectors(scene, False)
        # Building on decal layer, get from face under mouse
        if data.work_layer == 'DECAL_1' and data.lock_normal is False:
            location, hit_normal, face_index, distance = sprytile_modal.VIEW3D_OP_SprytileModalTool.raycast_object(context.object,
                                                                                   ray_origin,
                                                                                   ray_vector)
            # For decals, if not hitting the object don't draw preview
            if hit_normal is None:
                sprytile_preview.clear_preview_data()
                return

            # Do a coplanar check between hit location and cursor
            grid_origin = scene.cursor.location.copy()
            grid_origin += hit_normal * data.mesh_decal_offset

            check_coplanar = distance_point_to_plane(location, grid_origin, hit_normal)
            check_coplanar = abs(check_coplanar) < 0.05
            if check_coplanar is False:
                sprytile_preview.clear_preview_data()
                return

            face_up, face_right = VIEW3D_OP_SprytileModalTool.get_face_up_vector(context, face_index, 0.4, bias_right=True)
            if face_up is not None and face_right is not None:
                plane_normal = hit_normal
                up_vector = face_up
                right_vector = face_right
            else:
                sprytile_preview.clear_preview_data()
                return

        rotation = Quaternion(plane_normal, data.mesh_rotate)

        up_vector = rotation @ up_vector
        right_vector = rotation @ right_vector

        # Raycast to the virtual grid
        face_position, x_vector, y_vector, plane_cursor = sprytile_utils.raycast_grid(
            scene, context,
            up_vector, right_vector, plane_normal,
            ray_origin, ray_vector
        )

        if face_position is None:
            sprytile_preview.clear_preview_data()
            return

        # Passed can build checks, set flag to true
        ToolBuild.can_build = True

        offset_tile_id, offset_grid, coord_min, coord_max = sprytile_utils.get_grid_area(
                                                                    target_grid.tile_selection[2],
                                                                    target_grid.tile_selection[3],
                                                                    data.uv_flip_x,
                                                                    data.uv_flip_y)

        grid_no_spacing = sprytile_utils.grid_no_spacing(target_grid)
        # No spacing in grid, automatically join the preview together
        if grid_no_spacing:
            origin_coord = face_position + coord_min[0] * x_vector + coord_min[1] * y_vector

            size_x = (coord_max[0] - coord_min[0]) + 1
            size_y = (coord_max[1] - coord_min[1]) + 1

            size_x *= target_grid.grid[0]
            size_y *= target_grid.grid[1]

            x_vector *= size_x / target_grid.grid[0]
            y_vector *= size_y / target_grid.grid[1]

            preview_verts = sprytile_utils.get_build_vertices(origin_coord,
                                                          x_vector, y_vector,
                                                          up_vector, right_vector)
            vtx_center = Vector((0, 0, 0))
            for vtx in preview_verts:
                vtx_center += vtx
            vtx_center /= len(preview_verts)

            origin_xy = (target_grid.tile_selection[0],
                         target_grid.tile_selection[1])

            preview_uvs = sprytile_uv.get_uv_pos_size(data, target_img.size, target_grid,
                                                      origin_xy, size_x, size_y,
                                                      up_vector, right_vector,
                                                      preview_verts, vtx_center)
            sprytile_preview.set_preview_data(preview_verts, preview_uvs)
            return

        # Spaced grids need to be tiled
        preview_verts = []
        preview_uvs = []
        for i in range(len(offset_tile_id)):
            grid_offset = offset_grid[i]
            tile_offset = offset_tile_id[i]

            x_offset = x_vector * grid_offset[0]
            y_offset = y_vector * grid_offset[1]

            coord_position = face_position + x_offset + y_offset
            coord_verts = sprytile_utils.get_build_vertices(coord_position, x_vector, y_vector,
                                                        up_vector, right_vector)
            # Get the center of the preview verts
            vtx_center = Vector((0, 0, 0))
            for vtx in coord_verts:
                vtx_center += vtx
            vtx_center /= len(coord_verts)

            # Calculate the tile with offset
            tile_xy = (target_grid.tile_selection[0] + tile_offset[0],
                       target_grid.tile_selection[1] + tile_offset[1])

            coord_uvs = sprytile_uv.get_uv_positions(data, target_img.size, target_grid,
                                                     up_vector, right_vector, tile_xy,
                                                     coord_verts, vtx_center)

            preview_verts.extend(coord_verts)
            preview_uvs.extend(coord_uvs)

        sprytile_preview.set_preview_data(preview_verts, preview_uvs)

    def handle_error(self, err):
        print("Error in build mode: {0}".format(err))
        pass

    def handle_complete(self):
        pass


def register():
    pass


def unregister():
    pass


if __name__ == '__main__':
    register()
