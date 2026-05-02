bl_info = {
    "name": "Face to Bones & Empties (with Weight Filter)",
    "author": "Vercingetorix",
    "version": (1, 3),  # Updated version
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > FaceTools",
    "description": "Generate bones aligned to mesh faces, create empties and copy transforms constraints, with optional vertex-group weight filtering and constraint cleanup",
    "category": "Rigging",
}
import bpy
import bmesh
from mathutils import Vector, Matrix

def vertex_group_items(self, context):
    """Dynamic EnumProperty items for vertex groups of the selected mesh."""
    items = []
    scene = context.scene
    obj = scene.ftb_mesh_object
    if obj and obj.type == 'MESH':
        for vg in obj.vertex_groups:
            items.append((vg.name, vg.name, ""))
    return items

#Can bug if bones have multiple copytransform or the default name was changed
class FTB_OT_generate_face_bones(bpy.types.Operator):
    bl_idname = "ftb.generate_face_bones"
    bl_label = "Generate Face Bones & Empties"
    bl_description = "Generate bones for each face of a mesh, create empties and copy transforms constraints"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        obj = scene.ftb_mesh_object
        arma_obj = scene.ftb_armature_object
        obj_prefix = scene.ftb_object_prefix_name
        col_name = scene.ftb_collection_name
        bone_len = scene.ftb_bone_length
        empty_type = scene.ftb_empty_type
        use_filter = scene.ftb_use_weight_filter
        vgroup_name = scene.ftb_weight_vgroup
        threshold = scene.ftb_weight_threshold
        
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Valid mesh object not specified")
            return {'CANCELLED'}
        
        if arma_obj is None or arma_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Valid armature object not specified")
            return {'CANCELLED'}
        
        if obj_prefix.count('_') > 1:
            self.report({'ERROR'}, "Prefix can't contain underscore")
            return {'CANCELLED'}
        
        if any(o.name.startswith(obj_prefix) for o in bpy.data.objects):
            self.report({'ERROR'}, "Prefix already exist in the scene")
            return {'CANCELLED'}
        
        if use_filter:
            if vgroup_name == "" or vgroup_name not in [vg.name for vg in obj.vertex_groups]:
                self.report({'ERROR'}, "Filtering enabled but no valid vertex group selected")
                return {'CANCELLED'}
        if col_name in bpy.data.collections:
            col = bpy.data.collections[col_name]
        else:
            col = bpy.data.collections.new(col_name)
            context.scene.collection.children.link(col)
        mesh = obj.data
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        arma_obj.select_set(True)
        context.view_layer.objects.active = arma_obj
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = arma_obj.data.edit_bones
        count = 0
        if use_filter:
            try:
                vg = obj.vertex_groups[vgroup_name]
            except Exception:
                vg = None
        else:
            vg = None
        for i, poly in enumerate(mesh.polygons):
            if use_filter and vg is not None:
                total_w = 0.0
                for vid in poly.vertices:
                    try:
                        w = vg.weight(vid)
                    except RuntimeError:
                        w = 0.0
                    total_w += w
                avg_w = total_w / len(poly.vertices)
                if avg_w < threshold:
                    continue
            verts_world = [obj.matrix_world @ mesh.vertices[v].co for v in poly.vertices]
            center = sum(verts_world, Vector()) / len(verts_world)
            normal = obj.matrix_world.to_3x3() @ poly.normal
            normal.normalize()
            center_local = arma_obj.matrix_world.inverted() @ center
            normal_local = arma_obj.matrix_world.to_3x3().inverted() @ normal
            bone_name = f"{obj_prefix}Bone_{i}"
            bone = edit_bones.new(bone_name)
            bone.head = center_local
            bone.tail = center_local + normal_local.normalized() * bone_len
            count += 1
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Second pass: create empties and parent to mesh via vertex parent
        for i, poly in enumerate(mesh.polygons):
            if use_filter and vg is not None:
                total_w = 0.0
                for vid in poly.vertices:
                    try:
                        w = vg.weight(vid)
                    except RuntimeError:
                        w = 0.0
                    total_w += w
                if len(poly.vertices) <= 0:
                    continue
                avg_w = total_w / len(poly.vertices)
                if avg_w < threshold:
                    continue
            # Ensure in OBJECT mode to access vertices
            bpy.ops.object.mode_set(mode='OBJECT')
            verts_world = [obj.matrix_world @ mesh.vertices[v].co for v in poly.vertices]
            center = sum(verts_world, Vector()) / len(verts_world) if verts_world else Vector()
            normal = obj.matrix_world.to_3x3() @ poly.normal
            normal.normalize()
            up = Vector((0, 1, 0))
            if normal != up and normal != -up:
                axis = up.cross(normal)
                angle = up.angle(normal)
                rot_matrix = Matrix.Rotation(angle, 4, axis)
            else:
                rot_matrix = Matrix.Identity(4)
                if normal == -up:
                    rot_matrix = Matrix.Rotation(3.14159, 4, Vector((1, 0, 0)))
                    
            empty = bpy.data.objects.new(f"{obj_prefix}Target_{i}", None)
            empty.empty_display_type = empty_type
            empty.matrix_world = Matrix.Translation(center) @ rot_matrix
            # Link to main collection and custom collection
            context.scene.collection.objects.link(empty)
            for coll in empty.users_collection:
                if coll.name != col_name:
                    coll.objects.unlink(empty)
            if empty.name not in col.objects:
                col.objects.link(empty)
            # Parent empty to mesh via vertex parent without entering edit mode
            v_idxs = poly.vertices[:3]
            bpy.ops.object.select_all(action='DESELECT')
            empty.select_set(True)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            bpy.ops.mesh.select_all(action='DESELECT')
            for vid in v_idxs:
                bm.verts[vid].select = True
            bmesh.update_edit_mesh(obj.data, destructive=False)
            try:
                bpy.ops.object.vertex_parent_set()
            except RuntimeError as e:
                self.report({'WARNING'}, f"Vertex parent failed for empty {empty.name}: {e}")
                
        # Now add constraints in pose mode
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        arma_obj.select_set(True)
        context.view_layer.objects.active = arma_obj
        bpy.ops.object.mode_set(mode='POSE')
        for pbone in arma_obj.pose.bones:
            if not pbone.name.startswith(f"{obj_prefix}Bone_"):
                continue
            idx = pbone.name.split('_')[-1]
            empty_name = f"{obj_prefix}Target_{idx}"
            empty_obj = bpy.data.objects.get(empty_name)
            if empty_obj:
                con = pbone.constraints.new(type='COPY_TRANSFORMS')
                con.name = "Copy Transforms"
                con.target = empty_obj
            else:
                self.report({'WARNING'}, f"Empty {empty_name} not found for constraint")
        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Generated {count} bones, empties, and constraints.")
        return {'FINISHED'}

class FTB_OT_cleanup_face_bones(bpy.types.Operator):
    bl_idname = "ftb.cleanup_face_bones"
    bl_label = "Cleanup Face Bones & Empties"
    bl_description = "Remove all generated FaceBones, FaceEmpties and constraints"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        arma_obj = scene.ftb_armature_object
        col_name = scene.ftb_collection_name
        obj_prefix = scene.ftb_object_prefix_name
        
        if arma_obj and arma_obj.type == 'ARMATURE':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            arma_obj.select_set(True)
            context.view_layer.objects.active = arma_obj
            bpy.ops.object.mode_set(mode='EDIT')
            edit_bones = arma_obj.data.edit_bones
            for bone in list(edit_bones):
                if bone.name.startswith(f"{obj_prefix}Bone_"):
                    edit_bones.remove(bone)
            bpy.ops.object.mode_set(mode='OBJECT')
        col = bpy.data.collections.get(col_name)
        if col:
            for obj in list(col.objects):
                if obj.name.startswith(f"{obj_prefix}"):
                    bpy.data.objects.remove(obj, do_unlink=True)
        # Also remove any leftover constraints on other bones if needed
        if arma_obj and arma_obj.type == 'ARMATURE':
            bpy.ops.object.select_all(action='DESELECT')
            arma_obj.select_set(True)
            context.view_layer.objects.active = arma_obj
            bpy.ops.object.mode_set(mode='POSE')
            for pbone in arma_obj.pose.bones:
                for con in [c for c in pbone.constraints if c.name == "Copy Transforms" or c.type == 'COPY_TRANSFORMS']:
                    pbone.constraints.remove(con)
            bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, "Cleaned up generated FaceBones, Empties, and constraints.")
        return {'FINISHED'}

class FTB_OT_toggle_constraints(bpy.types.Operator):
    bl_idname = "ftb.toggle_constraints"
    bl_label = "Toggle Copy Transforms Constraints"
    bl_description = "Enable or disable all Copy Transforms constraints on FaceBones"
    bl_options = {'REGISTER', 'UNDO'}

    enable: bpy.props.BoolProperty(
        name="Enable Constraints",
        description="Enable (True) or Disable (False) Copy Transforms constraints",
        default=False
    )

    def execute(self, context):
        scene = context.scene
        arma_obj = scene.ftb_armature_object
        obj_prefix = scene.ftb_object_prefix_name

        if arma_obj is None or arma_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Valid armature object not specified")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        arma_obj.select_set(True)
        context.view_layer.objects.active = arma_obj
        bpy.ops.object.mode_set(mode='POSE')

        toggled = 0
        for pbone in arma_obj.pose.bones:
            if pbone.name.startswith(f"{obj_prefix}Bone_"):
                for con in pbone.constraints:
                    if con.type == 'COPY_TRANSFORMS' or con.name == "Copy Transforms":
                        con.mute = not self.enable
                        toggled += 1

        bpy.ops.object.mode_set(mode='OBJECT')
        state = "enabled" if self.enable else "disabled"
        self.report({'INFO'}, f"{toggled} Copy Transforms constraints {state}.")
        return {'FINISHED'}
    
class FTB_OT_remove_constraints(bpy.types.Operator):
    bl_idname = "ftb.remove_constraints"
    bl_label = "Remove Copy Transforms Constraints"
    bl_description = "Remove all Copy Transforms constraints from FaceBones in the specified armature"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        arma_obj = scene.ftb_armature_object
        obj_prefix = scene.ftb_object_prefix_name
        if arma_obj is None or arma_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Valid armature object not specified")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        arma_obj.select_set(True)
        context.view_layer.objects.active = arma_obj
        bpy.ops.object.mode_set(mode='POSE')
        removed = 0
        for pbone in arma_obj.pose.bones:
            if pbone.name.startswith(f"{obj_prefix}Bone_"):
                for con in [c for c in pbone.constraints if c.type == 'COPY_TRANSFORMS' or c.name == "Copy Transforms"]:
                    pbone.constraints.remove(con)
                    removed += 1
        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Removed {removed} Copy Transforms constraints.")
        return {'FINISHED'}


class FTBB_PT_panel(bpy.types.Panel):
    bl_label = "Face to Bones"
    bl_idname = "FTBB_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FaceTools'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "ftb_mesh_object")
        layout.prop(scene, "ftb_armature_object")
        layout.prop(scene, "ftb_object_prefix_name")
        layout.prop(scene, "ftb_collection_name")
        layout.prop(scene, "ftb_bone_length")
        layout.prop(scene, "ftb_empty_type")
        layout.separator()
        row = layout.row()
        row.prop(scene, "ftb_use_weight_filter", text="Filter by Vertex Group Weight")
        if scene.ftb_use_weight_filter:
            layout.prop(scene, "ftb_weight_vgroup", text="Vertex Group")
            layout.prop(scene, "ftb_weight_threshold", text="Weight Threshold")
        layout.separator()
        layout.operator("ftb.generate_face_bones", text="Generate Face Bones & Empties")
        layout.operator("ftb.cleanup_face_bones", text="Cleanup Face Bones & Empties")
        layout.operator("ftb.remove_constraints", text="Remove Copy Transforms Constraints")
        layout.operator("ftb.toggle_constraints", text="Enable Constraints").enable = True
        layout.operator("ftb.toggle_constraints", text="Disable Constraints").enable = False

classes = (
    FTB_OT_generate_face_bones,
    FTB_OT_cleanup_face_bones,
    FTB_OT_toggle_constraints,
    FTB_OT_remove_constraints,
    FTBB_PT_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ftb_mesh_object = bpy.props.PointerProperty(
        name="Mesh Object",
        type=bpy.types.Object
    )
    bpy.types.Scene.ftb_armature_object = bpy.props.PointerProperty(
        name="Armature Object",
        type=bpy.types.Object
    )
    bpy.types.Scene.ftb_object_prefix_name = bpy.props.StringProperty(
        name="Object Prefix",
        default="VX"
    )
    bpy.types.Scene.ftb_collection_name = bpy.props.StringProperty(
        name="Collection Name",
        default="VX AutoBones"
    )
    bpy.types.Scene.ftb_bone_length = bpy.props.FloatProperty(
        name="Bone Length",
        default=0.1,
        min=0.001
    )
    bpy.types.Scene.ftb_empty_type = bpy.props.EnumProperty(
        name="Empty Type",
        items=[
            ('ARROWS', 'Arrows', ''),
            ('PLAIN_AXES', 'Plain Axes', ''),
            ('CUBE', 'Cube', '')
        ],
        default='ARROWS'
    )
    bpy.types.Scene.ftb_use_weight_filter = bpy.props.BoolProperty(
        name="Use Weight Filter",
        description="Enable filtering faces by a vertex group weight threshold",
        default=False
    )
    bpy.types.Scene.ftb_weight_vgroup = bpy.props.EnumProperty(
        name="Vertex Group",
        description="Vertex group to use for filtering faces by average weight",
        items=vertex_group_items
    )
    bpy.types.Scene.ftb_weight_threshold = bpy.props.FloatProperty(
        name="Weight Threshold",
        description="Minimum average weight for a face to be processed (0.0 to 1.0)",
        default=0.5,
        min=0.0,
        max=1.0
    )

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ftb_mesh_object
    del bpy.types.Scene.ftb_armature_object
    del bpy.types.Scene.ftb_object_prefix_name
    del bpy.types.Scene.ftb_collection_name
    del bpy.types.Scene.ftb_bone_length
    del bpy.types.Scene.ftb_empty_type
    del bpy.types.Scene.ftb_use_weight_filter
    del bpy.types.Scene.ftb_weight_vgroup
    del bpy.types.Scene.ftb_weight_threshold

if __name__ == "__main__":
    register()
