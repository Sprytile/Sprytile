import math
from collections import deque

import bmesh
import bpy
import numpy
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_line_plane, distance_point_to_plane

from rx import Observable
from sprytile_tools.tool_build import ToolBuild
from sprytile_tools.tool_paint import ToolPaint
from sprytile_tools.tool_fill import ToolFill
import sprytile_uv
from sprytile_uv import UvDataLayers
import sprytile_utils
import sprytile_preview


class DataObjectDict(dict):
    def __getattr__(self, name):
        if name in self:
            return self[name]
        else:
            raise AttributeError("No such attribute: " + name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        if name in self:
            del self[name]
        else:
            raise AttributeError("No such attribute: " + name)


class VIEW3D_OP_SprytileModalTool(bpy.types.Operator):
    """Tile based mesh creation/UV layout tool"""
    bl_idname = "sprytile.modal_tool"
    bl_label = "Sprytile Paint"
    bl_options = {'REGISTER'}

    no_undo = False

    addon_keymaps = []
    default_keymaps = []
    tool_keymaps = { 
        'MAKE_FACE' : "Sprytile Build Tool Map", 
        'PAINT' : "Sprytile Paint Tool Map", 
        'FILL' : "Sprytile Fill Tool Map"
        }

    @staticmethod
    def calculate_view_axis(context):
        if context.area.type != 'VIEW_3D':
            return None, None

        region = context.region
        rv3d = context.region_data
        if rv3d is None:
            return None, None

        # Get the view ray from center of screen
        coord = Vector((int(region.width / 2), int(region.height / 2)))
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        # Get the up vector. The default scene view camera is pointed
        # downward, with up on Y axis. Apply view rotation to get current up
        view_up_vector = rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))

        plane_normal = sprytile_utils.snap_vector_to_axis(view_vector, mirrored=True)
        up_vector = sprytile_utils.snap_vector_to_axis(view_up_vector)

        # calculated vectors are not perpendicular, don't set data
        if plane_normal.dot(up_vector) != 0.0:
            return None, None

        return plane_normal, up_vector

    @staticmethod
    def find_view_axis(context):
        scene = context.scene
        if scene.sprytile_data.lock_normal is True:
            return
        plane_normal, up_vector = VIEW3D_OP_SprytileModalTool.calculate_view_axis(context)
        if plane_normal is None:
            return

        scene.sprytile_data.paint_normal_vector = plane_normal
        scene.sprytile_data.paint_up_vector = up_vector

        if abs(plane_normal.x) > 0:
            new_mode = 'X'
        elif abs(plane_normal.y) > 0:
            new_mode = 'Y'
        else:
            new_mode = 'Z'

        return new_mode

    def get_tiledata_from_index(self, face_index):
        return VIEW3D_OP_SprytileModalTool.get_face_tiledata(self.bmesh, self.bmesh.faces[face_index])

    @staticmethod
    def get_face_tiledata(bmesh, face):
        grid_id_layer = bmesh.faces.layers.int.get(UvDataLayers.GRID_INDEX)
        tile_id_layer = bmesh.faces.layers.int.get(UvDataLayers.GRID_TILE_ID)
        if grid_id_layer is None or tile_id_layer is None:
            return None, None, None, None, None

        grid_id = face[grid_id_layer]
        tile_packed_id = face[tile_id_layer]

        width = 1
        width_layer = bmesh.faces.layers.int.get(UvDataLayers.GRID_SEL_WIDTH)
        if width_layer is not None:
            width = face[width_layer]
            if width is None:
                width = 1

        height = 1
        height_layer = bmesh.faces.layers.int.get(UvDataLayers.GRID_SEL_HEIGHT)
        if height_layer is not None:
            height = face[height_layer]
            if height is None:
                height = 1

        origin = -1
        origin_layer = bmesh.faces.layers.int.get(UvDataLayers.GRID_SEL_ORIGIN)
        if origin_layer is not None:
            origin = face[origin_layer]
            if origin is None:
                origin = -1

        # For backwards compatibility. Origin/width/height
        # did not exist before 0.4.2
        if origin == 0 and height == 0 and width == 0:
            origin = tile_packed_id
        height = max(1, height)
        width = max(1, width)

        # print("get tile data - grid:{0}, tile_id:{1}, w:{2}, h:{3}, o:{4}"
        #       .format(grid_id, tile_packed_id, width, height, origin))
        return grid_id, tile_packed_id, width, height, origin

    def add_virtual_cursor(self, cursor_pos):
        cursor_len = len(self.virtual_cursor)
        if cursor_len == 0:
            self.virtual_cursor.append(cursor_pos)
            return

        last_pos = self.virtual_cursor[cursor_len - 1]
        last_vector = cursor_pos - last_pos
        if last_vector.magnitude < 0.1:
            return

        self.virtual_cursor.append(cursor_pos)

    def get_virtual_cursor_vector(self):
        cursor_direction = Vector((0.0, 0.0, 0.0))
        cursor_len = len(self.virtual_cursor)
        if cursor_len <= 1:
            return cursor_direction
        for idx in range(cursor_len - 1):
            segment = self.virtual_cursor[idx + 1] - self.virtual_cursor[idx]
            cursor_direction += segment
        cursor_direction /= cursor_len
        return cursor_direction

    def face_to_world_verts(self, context, face_index):
        if face_index is None:
            pass
        face = self.bmesh.faces[face_index]
        world_verts = []
        for idx, vert in enumerate(face.verts):
            vert_world_pos = context.object.matrix_world @ vert.co
            world_verts.append(vert_world_pos)
        return world_verts

    def flow_cursor(self, context, face_index, virtual_cursor):
        """Move the cursor along the given face, using virtual_cursor direction"""
        world_verts = self.face_to_world_verts(context, face_index)
        self.flow_cursor_verts(context, world_verts, virtual_cursor)

    def flow_cursor_verts(self, context, verts, virtual_cursor):

        cursor_len = len(self.virtual_cursor)
        if cursor_len <= 1:
            return None
        cursor_direction = self.get_virtual_cursor_vector()
        cursor_direction.normalize()

        max_dist = -1.0
        closest_pos = None

        for idx, vert in enumerate(verts):
            vert_vector = vert - virtual_cursor
            vert_dist = vert_vector.length
            vert_vector.normalize()
            vert_dot = vert_vector.dot(cursor_direction)
            if vert_dot > 0.5 and vert_dist > max_dist:
                closest_pos = vert
                max_dist = vert_dist

        return closest_pos

    def raycast_grid_coord(self, context, x, y, up_vector, right_vector, normal, work_layer_mask=0):
        """
        Raycast agains the object using grid coordinates around the cursor
        :param context:
        :param x:
        :param y:
        :param up_vector:
        :param right_vector:
        :param normal:
        :param work_layer_mask:
        :return:
        """
        obj = context.object

        ray_origin = Vector(context.scene.cursor.location.copy())
        ray_origin += (x + 0.5) * right_vector
        ray_origin += (y + 0.5) * up_vector

        ray_offset = 0.01
        ray_origin += normal * ray_offset

        ray_direction = -normal

        return VIEW3D_OP_SprytileModalTool.raycast_object(obj, ray_origin, ray_direction, ray_dist=ray_offset*2,
                                   work_layer_mask=work_layer_mask)

    @staticmethod
    def raycast_object(obj, ray_origin, ray_direction, ray_dist=1000.0,
                       world_normal=False, work_layer_mask=0, pass_dist=0.001):
        matrix = obj.matrix_world.copy()
        # get the ray relative to the object
        matrix_inv = matrix.inverted()
        ray_origin_obj = matrix_inv @ ray_origin
        ray_target_obj = matrix_inv @ (ray_origin + ray_direction)
        ray_direction_obj = ray_target_obj - ray_origin_obj
        mesh = bmesh.from_edit_mesh(obj.data)
        tree = BVHTree.FromBMesh(mesh)

        location, normal, face_index, distance = tree.ray_cast(ray_origin_obj, ray_direction_obj, ray_dist)
        if face_index is None:
            return None, None, None, None

        face = mesh.faces[face_index]

        work_layer_id = mesh.faces.layers.int.get(UvDataLayers.WORK_LAYER)
        if work_layer_id is None:
            return None, None, None, None
        work_layer_value = face[work_layer_id]

        # Pass through faces under certain conditions
        do_pass_through = False
        # Layer mask not matching
        if work_layer_value != work_layer_mask:
            do_pass_through = True
        # Hit face is backface
        if face.normal.dot(ray_direction) > 0:
            do_pass_through = not bpy.context.scene.sprytile_data.allow_backface
        # Hit face is hidden
        if face.hide:
            do_pass_through = True

        # Translate location back to world space
        location = matrix @ location

        if do_pass_through:
            # add shift offset if passing through
            shift_vec = ray_direction.normalized() * pass_dist
            new_ray_origin = location + shift_vec
            return VIEW3D_OP_SprytileModalTool.raycast_object(obj, new_ray_origin, ray_direction, work_layer_mask=work_layer_mask)

        if world_normal:
            normal = matrix @ normal
        return location, normal, face_index, distance

    def update_bmesh_tree(self, context, update_index=False):
        self.bmesh = bmesh.from_edit_mesh(context.object.data)
        if update_index:
            # Verify layers are created
            VIEW3D_OP_SprytileModalTool.verify_bmesh_layers(self.bmesh)
            self.bmesh = bmesh.from_edit_mesh(context.object.data)
        self.tree = BVHTree.FromBMesh(self.bmesh)


    @staticmethod
    def verify_bmesh_layers(bmesh):
        # Verify layers are created
        for layer_name in UvDataLayers.LAYER_NAMES:
            layer_data = bmesh.faces.layers.int.get(layer_name)
            if layer_data is None:
                print('Creating face layer:', layer_name)
                bmesh.faces.layers.int.new(layer_name)

            for el in [bmesh.faces, bmesh.verts, bmesh.edges]:
                el.index_update()
                el.ensure_lookup_table()

            bmesh.loops.layers.uv.verify()


    def construct_face(self, context, grid_coord, grid_size,
                       tile_xy, tile_origin,
                       grid_up, grid_right,
                       up_vector, right_vector, plane_normal,
                       require_base_layer=False,
                       work_layer_mask=0,
                       threshold=None):
        """
        Create a new face at grid_coord or remap the existing face
        :type work_layer_mask: bitmask integer
        :param context:
        :param grid_coord: Grid coordinate to create at
        :param grid_size: Tile unit size of face
        :param tile_xy: Tilegrid coordinate to map
        :param tile_origin: Origin of tilegrid coordinate, for mapping data
        :param grid_up:
        :param grid_right:
        :param up_vector:
        :param right_vector:
        :param plane_normal:
        :param require_base_layer:
        :param threshold:
        :return:
        """
        scene = context.scene
        data = scene.sprytile_data

        # Run a raycast on target work layer mask
        hit_loc, hit_normal, face_index, hit_dist = self.raycast_grid_coord(
            context, grid_coord[0], grid_coord[1],
            grid_up, grid_right, plane_normal,
            work_layer_mask=work_layer_mask
        )

        # Didn't hit target layer, and require base layer
        if face_index is None and require_base_layer:
            # Check if there is a base layer underneath
            base_hit_loc, hit_normal, base_face_index, base_hit_dist = self.raycast_grid_coord(
                    context, grid_coord[0], grid_coord[1],
                    grid_up, grid_right, plane_normal
                )
            # Didn't hit required base layer, do nothing
            if base_face_index is None:
                return None

        # Calculate where the origin of the grid is
        grid_origin = scene.cursor.location.copy()
        # If doing mesh decal, offset the grid origin
        if data.work_layer == 'DECAL_1':
            grid_origin += plane_normal * data.mesh_decal_offset

        did_build = False
        # No face index, assume build face
        if face_index is None or face_index < 0:
            face_position = grid_origin + grid_coord[0] * grid_right + grid_coord[1] * grid_up

            face_verts = sprytile_utils.get_build_vertices(face_position,
                                                 grid_right * grid_size[0], grid_up * grid_size[1],
                                                 up_vector, right_vector)
            face_index = self.create_face(context, face_verts)
            did_build = True

        if face_index is None or face_index < 0:
            return None

        # Didn't create face, only want to remap face. Check for coplanarity and dot
        if did_build is False:
            check_dot = abs(plane_normal.dot(hit_normal))
            check_dot -= 1
            check_coplanar = distance_point_to_plane(hit_loc, grid_origin, plane_normal)

            check_coplanar = abs(check_coplanar) < 0.05
            check_dot = abs(check_dot) < 0.05
            # Can't remap face
            if not check_coplanar or not check_dot:
                return None

        sprytile_uv.uv_map_face(context, up_vector, right_vector,
                                tile_xy, tile_origin, face_index,
                                self.bmesh, grid_size)

        if did_build and data.auto_merge:
            if threshold is None:
                threshold = (1 / data.world_pixels) * 1.25

            face = self.bmesh.faces[face_index]

            face_position += grid_right * 0.5 + grid_up * 0.5
            face_position += plane_normal * 0.01
            face_index = self.merge_doubles(context, face, face_position, -plane_normal, threshold)

        # Auto merge refreshes the mesh automatically
        self.refresh_mesh = not data.auto_merge

        return face_index

    def merge_doubles(self, context, face, ray_origin, ray_direction, threshold):
        face.select = True
        work_layer_id = self.bmesh.faces.layers.int.get(UvDataLayers.WORK_LAYER)
        work_layer_value = face[work_layer_id]
        for check_face in self.bmesh.faces:
            check_face.select = check_face[work_layer_id] == work_layer_value

        merge_threshold = 0.00
        if context.scene.sprytile_data.work_layer != 'BASE':
            merge_threshold = 0.01
        bpy.ops.mesh.remove_doubles(threshold=merge_threshold, use_unselected=False)

        for el in [self.bmesh.faces, self.bmesh.verts, self.bmesh.edges]:
            el.index_update()
            el.ensure_lookup_table()

        self.bmesh.select_flush_mode()

        for iter_face in self.bmesh.faces:
            iter_face.select = False

        # Modified the mesh, refresh and raycast to find the new face index
        self.update_bmesh_tree(context)
        hit_loc, norm, new_face_idx, hit_dist = self.raycast_object(
            context.object,
            ray_origin,
            ray_direction,
            0.02
        )
        if new_face_idx is not None:
            self.bmesh.faces[new_face_idx].select = False
        return new_face_idx

    def create_face(self, context, world_vertices):
        """
        Create a face in the bmesh using the given world space vertices
        :param context:
        :param world_vertices: Vector array of world space positions
        :return:
        """
        face_vertices = []
        # Convert world space position to object space
        world_inv = context.object.matrix_world.copy().inverted()
        for face_vtx in world_vertices:
            vtx = self.bmesh.verts.new(face_vtx)
            vtx.co = world_inv @ vtx.co
            face_vertices.append(vtx)

        face = self.bmesh.faces.new(face_vertices)
        face.normal_update()

        for el in [self.bmesh.faces, self.bmesh.verts, self.bmesh.edges]:
            el.index_update()
            el.ensure_lookup_table()

        bmesh.update_edit_mesh(context.object.data, True, True)

        # Update the collision BVHTree with new data
        self.refresh_mesh = True
        return face.index

    @staticmethod
    def get_face_up_vector(obj, context, face_index, sensitivity=0.1, bias_right=False):
        """
        Find the edge of the given face that most closely matches view up vector
        :param context:
        :param face_index:
        :param sensitivity:
        :param bias_right:
        :return:
        """
        # Get the view up vector. The default scene view camera is pointed
        # downward, with up on Y axis. Apply view rotation to get current up

        rv3d = context.region_data
        view_up_vector = rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))
        view_right_vector = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
        data = context.scene.sprytile_data
        mesh = bmesh.from_edit_mesh(obj.data)

        #if mesh is None or mesh.faces is None:
        #    self.refresh_mesh = True
        #    return None, None

        world_matrix = context.object.matrix_world
        face = mesh.faces[face_index]

        # Convert the face normal to world space
        normal_inv = context.object.matrix_world.copy().inverted().transposed()
        face_normal = normal_inv @ face.normal.copy()

        def calc_up_sel_vectors(vtx1, vtx2):
            edge_center = (vtx1 + vtx2) / 2
            face_center = world_matrix @ face.calc_center_bounds()
            # Get the rough heading of the up vector
            estimated_up = face_center - edge_center
            estimated_up.normalize()

            sel_vector = vtx2 - vtx1
            sel_vector.normalize()

            # Cross the face normal and hint vector to get the up vector
            view_up_vector = face_normal.cross(sel_vector)
            view_up_vector.normalize()

            # If the calculated up faces away from rough up, reverse it
            if view_up_vector.dot(estimated_up) < 0:
                view_up_vector *= -1
                sel_vector *= -1
            return view_up_vector, sel_vector

        do_hint = data.paint_mode in {'PAINT', 'SET_NORMAL'} and data.paint_hinting
        if do_hint:
            for edge in face.edges:
                if not edge.select:
                    continue
                vtx1 = world_matrix @ edge.verts[0].co
                vtx2 = world_matrix @ edge.verts[1].co
                view_up_vector, sel_vector = calc_up_sel_vectors(vtx1, vtx2)
                return view_up_vector, sel_vector
            # if face didn't have any selected edges, use the active edge selection
            selection = mesh.select_history.active
            if isinstance(selection, bmesh.types.BMEdge):
                vtx1 = world_matrix @ selection.verts[0].co.copy()
                vtx2 = world_matrix @ selection.verts[1].co.copy()
                view_up_vector, sel_vector = calc_up_sel_vectors(vtx1, vtx2)
                return view_up_vector, sel_vector
            # No edges or edge selection, use normal face up vector finding

        # Find the edge of the hit face that most closely matches
        # the view up / view right vectors
        closest_up = None
        closest_up_dot = 2.0
        closest_right = None
        closest_right_dot = 2.0
        idx = -1
        for edge in face.edges:
            idx += 1
            # Move vertices to world space
            vtx1 = world_matrix @ edge.verts[0].co
            vtx2 = world_matrix @ edge.verts[1].co
            edge_vec = vtx2 - vtx1
            edge_vec.normalize()
            edge_up_dot = 1 - abs(edge_vec.dot(view_up_vector))
            edge_right_dot = 1 - abs(edge_vec.dot(view_right_vector))
            # print(idx, edge_vec, "up dot", edge_up_dot, "right dot", edge_right_dot)
            if edge_up_dot < sensitivity and edge_up_dot < closest_up_dot:
                closest_up_dot = edge_up_dot
                closest_up = edge_vec
                # print("Setting", idx, "as closest up")
            if edge_right_dot < sensitivity and edge_right_dot < closest_right_dot:
                closest_right_dot = edge_right_dot
                closest_right = edge_vec
                # print("Setting", idx, "as closest right")

        # print("Closest indices: up", closest_up, "right", closest_right)
        chosen_up = None

        if closest_up is not None and not bias_right:
            if closest_up.dot(view_up_vector) < 0:
                closest_up *= -1
            chosen_up = closest_up
        elif closest_right is not None:
            if closest_right.dot(view_right_vector) < 0:
                closest_right *= -1
            chosen_up = face_normal.cross(closest_right)

        if do_hint and closest_right is not None:
            if closest_right.dot(view_right_vector) < 0:
                closest_right *= -1
            chosen_up = face_normal.cross(closest_right)

        # print("Chosen up", chosen_up)
        return chosen_up, closest_right

    @staticmethod
    def cursor_move_layer(context, direction):
        scene = context.scene
        target_grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
        grid_x = target_grid.grid[0]
        grid_y = target_grid.grid[1]
        layer_move = min(grid_x, grid_y)
        layer_move = math.ceil(layer_move/2)
        layer_move *= (1 / context.scene.sprytile_data.world_pixels)
        plane_normal = scene.sprytile_data.paint_normal_vector.copy()
        plane_normal *= layer_move * direction
        grid_position = scene.cursor.location + plane_normal
        scene.cursor.location = grid_position


    def modal(self, context, event):
        do_exit = False
        sprytile_data = context.scene.sprytile_data

        # Check that the mouse is inside the region
        region = context.region
        coord = Vector((event.mouse_region_x, event.mouse_region_y))
        out_of_region = coord.x < 0 or coord.y < 0 or coord.x > region.width or coord.y > region.height

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            do_exit = True
        if context.object.mode != 'EDIT':
            do_exit = True
        if do_exit:
            self.exit_modal(event, context)
            return {'CANCELLED'}

        if VIEW3D_OP_SprytileModalTool.no_undo and sprytile_data.is_grid_translate is False:
            VIEW3D_OP_SprytileModalTool.no_undo = False

        # Mouse in Sprytile UI, eat this event without doing anything
        if context.scene.sprytile_ui.use_mouse:
            sprytile_preview.clear_preview_data()
            return {'RUNNING_MODAL'}

        # Mouse move triggers preview drawing
        draw_preview = sprytile_data.paint_mode in {'MAKE_FACE', 'FILL', 'PAINT'}
        if draw_preview:
            if (event.alt or context.scene.sprytile_ui.use_mouse) or sprytile_data.is_snapping:
                draw_preview = False

        # Refreshing the mesh, preview needs constantly refreshed
        # mesh or bad things seem to happen. This can potentially get expensive
        #if self.refresh_mesh or self.bmesh.is_valid is False or draw_preview:
        # @Blender 2.8 note: this now happens inside the GUI operator so no need to do it here
        if self.refresh_mesh or self.bmesh.is_valid is False:
            self.update_bmesh_tree(context, True)
            self.refresh_mesh = False

        # Potentially expensive, test if there is a selected mesh element
        if event.type == 'MOUSEMOVE':
            sprytile_data.has_selection = False
            for v in self.bmesh.verts:
                if v.select:
                    sprytile_data.has_selection = True
                    break

        context.area.tag_redraw()

        # If outside the region, pass through
        if out_of_region:
            # If preview data exists, clear it
            if sprytile_preview.preview_verts is not None:
                sprytile_preview.clear_preview_data()
            return {'PASS_THROUGH'}

        modal_return = {'PASS_THROUGH'}

        # Process keyboard events, if returned something end here
        key_return = self.handle_keys(context, event)
        if key_return is not None:
            sprytile_preview.clear_preview_data()
            modal_return = key_return
        # Didn't process keyboard, process mouse now
        else:
            mouse_return = self.handle_mouse(context, event, draw_preview)
            if mouse_return is not None:
                modal_return = mouse_return

        # Signals tools to draw preview
        self.draw_preview = draw_preview and self.refresh_mesh is False
        # Clear preview data if not drawing preview
        if not self.draw_preview:
            sprytile_preview.preview_verts = None
            sprytile_preview.preview_uvs = None

        # Build the data that will be used by tool observers
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y
        no_data = self.tree is None or rv3d is None

        if no_data is False:
            # get the ray from the viewport and mouse
            ray_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            self.rx_data = DataObjectDict(
                context=context,
                ray_vector=ray_vector,
                ray_origin=ray_origin
            )
        else:
            self.rx_data = None

        self.call_tool(event, True, context)

        return modal_return


    def call_tool(self, event, left_down, context):
        # Push the event data out through rx_observer for tool observers
        sprytile_data = bpy.context.scene.sprytile_data

        # If the selected object does not own the painting material, add a slot for it here
        if left_down:
            grid = sprytile_utils.get_grid(context, context.object.sprytile_gridid)
            if grid is not None:
                grid_mat = sprytile_utils.get_grid_material(grid)
                if not sprytile_utils.has_material(context.object, grid_mat):
                    bpy.ops.object.material_slot_add()
                    context.object.active_material = grid_mat

        if self.rx_observer is not None:
            self.rx_observer.on_next(
                DataObjectDict(
                    paint_mode=sprytile_data.paint_mode,
                    event=event,
                    left_down=left_down,
                    build_preview=self.draw_preview,
                )
            )


    def handle_mouse(self, context, event, draw_preview):
        """"""
        # Eat any tweak mouse events, default blender keymap has a translate command on tweak
        if event.type in {'EVT_TWEAK_L', 'EVT_TWEAK_M', 'EVT_TWEAK_R'}:
            return {'RUNNING_MODAL'}
        if 'MOUSE' not in event.type:
            return None
        
        #if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
        #    if context.scene.sprytile_data.is_snapping:
        #        direction = -1 if event.type == 'WHEELUPMOUSE' else 1
        #        self.cursor_move_layer(context, direction)
        #        return {'RUNNING_MODAL'}
        # no_undo flag is up, process no other mouse events until it is cleared
        if VIEW3D_OP_SprytileModalTool.no_undo:
            # print("No undo flag is on", event.type, event.value)
            clear_types = {'LEFTMOUSE', 'RIGHTMOUSE'}
            if event.type in clear_types and event.value == 'RELEASE':
                print("Clearing no undo")
                self.refresh_mesh = True
                VIEW3D_OP_SprytileModalTool.no_undo = False
            return {'PASS_THROUGH'} if VIEW3D_OP_SprytileModalTool.no_undo else {'RUNNING_MODAL'}
        elif event.type == 'LEFTMOUSE':
        #    check_modifier = False
            # TODO: Support preferences
            #addon_prefs = context.preferences.addons[__package__].preferences
            #if addon_prefs.tile_picker_key == 'Alt':
            #    check_modifier = event.alt
            #if addon_prefs.tile_picker_key == 'Ctrl':
            #    check_modifier = event.ctrl
            #if addon_prefs.tile_picker_key == 'Shift':
            #    check_modifier = event.shift

        #    if event.value == 'PRESS' and check_modifier is True:
        #        self.find_face_tile(context, event)
            return {'RUNNING_MODAL'}
        elif event.type == 'MOUSEMOVE':
            if draw_preview and not VIEW3D_OP_SprytileModalTool.no_undo and event.type not in self.is_keyboard_list:
                self.draw_preview = True
            #if context.scene.sprytile_data.is_snapping:
            #    self.cursor_snap(context, event)

        return None

    def handle_keys(self, context, event):
        """Process keyboard presses"""
        if event.type not in self.is_keyboard_list:
            return None

        def keymap_is_evt(kmi, evt):
            is_mapped_key = kmi.type == event.type and \
                            kmi.value in {event.value, 'ANY'} and \
                            kmi.ctrl is event.ctrl and \
                            kmi.alt is event.alt and \
                            kmi.shift is event.shift
            return is_mapped_key

        # Process intercepts for special keymaps
        for key_intercept in self.intercept_keys:
            key = key_intercept[0]
            arg = key_intercept[1]
            if not keymap_is_evt(key, event):
                continue
            # print("Special key is", arg)
            if arg == 'move_sel':
                sprytile_preview.preview_uvs = None
                sprytile_preview.preview_verts = None
                VIEW3D_OP_SprytileModalTool.no_undo = True
                bpy.ops.sprytile.translate_grid('INVOKE_REGION_WIN')
                return {'RUNNING_MODAL'}
            if arg == 'sel_mesh':
                return {'PASS_THROUGH'}
        #sprytile_data = context.scene.sprytile_data
        #if event.shift and context.scene.sprytile_data.is_snapping:
        #    self.cursor_snap(context, event)
        #    return {'RUNNING_MODAL'}
        # Pass through every key event we don't handle ourselves
        return {'PASS_THROUGH'}

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        if context.space_data.type != 'VIEW_3D':
            self.report({'WARNING'}, "Active space must be a View3d: {0}".format(context.space_data.type))
            return {'CANCELLED'}

        obj = context.object
        if not obj.visible_get() or obj.type != 'MESH':
            self.report({'WARNING'}, "Active object must be a visible mesh")
            return {'CANCELLED'}
        if len(context.scene.sprytile_mats) < 1:
            bpy.ops.sprytile.validate_grids()
        if len(context.scene.sprytile_mats) < 1:
            self.report({'WARNING'}, "No valid materials")
            return {'CANCELLED'}

        use_default_grid_id = obj.sprytile_gridid == -1
        if sprytile_utils.get_grid(context, obj.sprytile_gridid) is None:
            use_default_grid_id = True

        if use_default_grid_id:
            obj.sprytile_gridid = context.scene.sprytile_mats[0].grids[0].id


        addon_prefs = context.preferences.addons[__package__].preferences
        auto_adjust = addon_prefs.auto_adjust_viewport_shading
        if auto_adjust:
            cur_space = context.area.spaces.active
            if cur_space.shading.type != 'MATERIAL':
                cur_space.shading.type = 'MATERIAL'

        self.virtual_cursor = deque([], 3)
        VIEW3D_OP_SprytileModalTool.no_undo = False
        self.update_bmesh_tree(context)
        self.refresh_mesh = False

        # Setup Rx Observer and Observables
        self.rx_observer = None
        observable_source = Observable.create(self.setup_rx_observer)
        # Setup multi casting Observable
        self.rx_source = observable_source.publish().auto_connect(1)

        # Tools receive events from the Observable
        self.tools = {
            "build": ToolBuild(self, self.rx_source),
            "paint": ToolPaint(self, self.rx_source),
            "fill": ToolFill(self, self.rx_source)
        }

        win_mgr = context.window_manager

        self.setup_user_keys(context)
        win_mgr.modal_handler_add(self)

        sprytile_data = context.scene.sprytile_data
        sprytile_data.is_snapping = False

        context.scene.sprytile_ui.is_dirty = True
        #bpy.ops.sprytile.gui_win('INVOKE_REGION_WIN') #TODO: Renable once ui works

        #Update view axis
        view_axis = self.find_view_axis(context)
        if view_axis is not None:
            if view_axis != sprytile_data.normal_mode:
                sprytile_data.normal_mode = view_axis
                sprytile_data.lock_normal = False

        self.update_bmesh_tree(context, True)
        self.modal(context, event)

        return {'RUNNING_MODAL'}

    def setup_rx_observer(self, observer):
        self.rx_observer = observer

    def setup_user_keys(self, context):
        """Find the keymaps to pass through to Blender"""
        self.is_keyboard_list = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q',
                                 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
                                 'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE',
                                 'LEFT_CTRL', 'LEFT_ALT', 'LEFT_SHIFT', 'RIGHT_ALT',
                                 'RIGHT_CTRL', 'RIGHT_SHIFT', 'OSKEY', 'GRLESS', 'ESC', 'TAB', 'RET', 'SPACE',
                                 'LINE_FEED', 'BACK_SPACE', 'DEL', 'SEMI_COLON', 'PERIOD', 'COMMA', 'QUOTE',
                                 'ACCENT_GRAVE', 'MINUS', 'SLASH', 'BACK_SLASH', 'EQUAL', 'LEFT_BRACKET',
                                 'RIGHT_BRACKET', 'LEFT_ARROW', 'DOWN_ARROW', 'RIGHT_ARROW', 'UP_ARROW',
                                 'NUMPAD_2', 'NUMPAD_4', 'NUMPAD_6', 'NUMPAD_8', 'NUMPAD_1', 'NUMPAD_3', 'NUMPAD_5',
                                 'NUMPAD_7', 'NUMPAD_9', 'NUMPAD_PERIOD', 'NUMPAD_SLASH', 'NUMPAD_ASTERIX', 'NUMPAD_0',
                                 'NUMPAD_MINUS', 'NUMPAD_ENTER', 'NUMPAD_PLUS',
                                 'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'F13',
                                 'F14', 'F15', 'F16', 'F17', 'F18', 'F19', 'PAUSE', 'INSERT', 'HOME', 'PAGE_UP',
                                 'PAGE_DOWN', 'END', 'MEDIA_PLAY', 'MEDIA_STOP', 'MEDIA_FIRST', 'MEDIA_LAST']

        self.intercept_keys = []

        user_keymaps = context.window_manager.keyconfigs.user.keymaps

        def get_keymap_entry(keymap_name, command):
            keymap = user_keymaps[keymap_name]
            if keymap is None:
                return False, None
            key_list = keymap.keymap_items
            cmd_idx = key_list.find(command)
            if cmd_idx < 0:
                return True, None
            return True, key_list[cmd_idx]

        # These keymaps intercept existing shortcuts and repurpose them
        keymap_intercept = {
            '3D View': [
                ('view3d.select_circle', 'sel_mesh'),
                ('transform.translate', 'move_sel')
            ]
        }
        for keymap_id in keymap_intercept:
            cmd_list = keymap_intercept[keymap_id]
            for cmd_data in cmd_list:
                cmd = cmd_data[0]
                arg = cmd_data[1]
                has_map, cmd_entry = get_keymap_entry(keymap_id, cmd)
                if not has_map:
                    break
                if cmd_entry is None:
                    continue
                self.intercept_keys.append((cmd_entry, arg))

    def exit_modal(self, event, context):
        self.call_tool(event, False, context)
        if self.rx_observer is not None:
            self.rx_observer.on_completed()
        self.tree = None
        self.tools = None
        if context.object.mode == 'EDIT':
            bmesh.update_edit_mesh(context.object.data, True, True)


# module classes
classes = (
    VIEW3D_OP_SprytileModalTool,
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)


def unregister():
    for cl in classes:
        bpy.utils.unregister_class(cl)


if __name__ == '__main__':
    register()
