# SimToBones - Blender extension. Metadata lives in blender_manifest.toml.

import bpy

BONE_TAG = "Bone_"
TARGET_TAG = "Target_"
CONSTRAINT_NAME = "Copy Transforms"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_or_create_collection(context, col_name, report=None):
    """Get or create a collection linked to the current scene."""
    col_name = (col_name or "").strip()
    if not col_name:
        if report:
            report({'ERROR'}, "Collection name is empty")
        return None

    col = bpy.data.collections.get(col_name)
    if col is None:
        col = bpy.data.collections.new(col_name)
    if col.name not in context.scene.collection.children and col != context.scene.collection:
        try:
            context.scene.collection.children.link(col)
        except RuntimeError:
            pass  # already linked deeper in the hierarchy
    return col


def set_active(context, obj, mode='OBJECT'):
    """Make obj the only selected + active object and switch it to mode."""
    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in context.view_layer.objects.selected:
        o.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=mode)


def collect_faces(obj, vgroup=None, threshold=0.0):
    """Snapshot face data (index, world center, world normal, first 3 verts).

    Everything is copied into plain Python values up front: mesh.polygons must
    not be read while switching modes (Blender reallocates the mesh arrays,
    which crashes Blender 5.x).
    """
    mesh = obj.data
    mw = obj.matrix_world
    nm = mw.to_3x3().inverted_safe().transposed()  # correct normal transform
    faces = []

    for poly in mesh.polygons:
        vids = tuple(poly.vertices)
        if len(vids) < 3:
            continue

        if vgroup is not None:
            total = 0.0
            for vid in vids:
                try:
                    total += vgroup.weight(vid)
                except RuntimeError:  # vertex not in group -> weight 0
                    pass
            if total / len(vids) < threshold:
                continue

        center = mw @ poly.center
        normal = (nm @ poly.normal).normalized()
        faces.append((poly.index, center.copy(), normal, vids[:3]))
    return faces


def vertex_group_items(self, context):
    """Dynamic EnumProperty items for vertex groups of the selected mesh."""
    obj = context.scene.ftb_mesh_object if context and context.scene else None
    items = []
    if obj and obj.type == 'MESH':
        items = [(vg.name, vg.name, "") for vg in obj.vertex_groups]
    if not items:
        items = [('NONE', "(no vertex groups)", "")]
    # Blender requires the item strings to stay referenced from Python.
    vertex_group_items.cache = items
    return items


def iter_generated_constraints(arma_obj, prefix):
    for pbone in arma_obj.pose.bones:
        if pbone.name.startswith(prefix + BONE_TAG):
            for con in pbone.constraints:
                if con.type == 'COPY_TRANSFORMS':
                    yield con


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class FTB_OT_generate_face_bones(bpy.types.Operator):
    bl_idname = "ftb.generate_face_bones"
    bl_label = "Generate Face Bones & Empties"
    bl_description = "Generate bones for each face of a mesh, create empties and copy transforms constraints"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        obj = scene.ftb_mesh_object
        arma_obj = scene.ftb_armature_object
        prefix = scene.ftb_object_prefix_name.strip()
        bone_len = scene.ftb_bone_length

        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Valid mesh object not specified")
            return {'CANCELLED'}
        if arma_obj is None or arma_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Valid armature object not specified")
            return {'CANCELLED'}
        if not prefix:
            self.report({'ERROR'}, "Object prefix is empty")
            return {'CANCELLED'}
        if any(o.name.startswith(prefix + TARGET_TAG) for o in bpy.data.objects) or \
                any(b.name.startswith(prefix + BONE_TAG) for b in arma_obj.data.bones):
            self.report({'ERROR'}, f'Prefix "{prefix}" is already used, run Cleanup or pick another prefix')
            return {'CANCELLED'}

        vgroup = None
        if scene.ftb_use_weight_filter:
            vgroup = obj.vertex_groups.get(scene.ftb_weight_vgroup)
            if vgroup is None:
                self.report({'ERROR'}, "Filtering enabled but no valid vertex group selected")
                return {'CANCELLED'}

        col = get_or_create_collection(context, scene.ftb_collection_name, self.report)
        if col is None:
            return {'CANCELLED'}

        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        faces = collect_faces(obj, vgroup, scene.ftb_weight_threshold)
        if not faces:
            self.report({'WARNING'}, "No faces matched, nothing generated")
            return {'CANCELLED'}

        # 1) Bones, one per face, pointing along the face normal.
        set_active(context, arma_obj, 'EDIT')
        arm_inv = arma_obj.matrix_world.inverted_safe()
        arm_rot_inv = arma_obj.matrix_world.to_3x3().inverted_safe()
        edit_bones = arma_obj.data.edit_bones
        bone_names = {}
        for idx, center, normal, _vids in faces:
            head = arm_inv @ center
            direction = (arm_rot_inv @ normal).normalized()
            eb = edit_bones.new(f"{prefix}{BONE_TAG}{idx}")
            eb.head = head
            eb.tail = head + direction * bone_len
            bone_names[idx] = eb.name
        bpy.ops.object.mode_set(mode='OBJECT')

        # 2) Empties, placed exactly on the bone rest pose (no jump when the
        #    constraint is added) and vertex-parented to the face's 3 vertices.
        empties = {}
        for idx, _center, _normal, vids in faces:
            bone = arma_obj.data.bones[bone_names[idx]]
            empty = bpy.data.objects.new(f"{prefix}{TARGET_TAG}{idx}", None)
            empty.empty_display_type = scene.ftb_empty_type
            empty.empty_display_size = bone_len
            col.objects.link(empty)
            empty.parent = obj
            empty.parent_type = 'VERTEX_3'
            empty.parent_vertices = vids
            empty.matrix_basis = arma_obj.matrix_world @ bone.matrix_local
            empties[idx] = empty

        # Compute parent inverses so empties keep their placement
        # (same result as Ctrl+P > Make Vertex Parent, without edit mode).
        context.view_layer.update()
        for empty in empties.values():
            parent_mat = empty.matrix_world @ empty.matrix_basis.inverted_safe()
            empty.matrix_parent_inverse = parent_mat.inverted_safe()
        context.view_layer.update()

        # 3) Copy Transforms constraints.
        for idx, empty in empties.items():
            pbone = arma_obj.pose.bones[bone_names[idx]]
            con = pbone.constraints.new(type='COPY_TRANSFORMS')
            con.name = CONSTRAINT_NAME
            con.target = empty

        set_active(context, arma_obj, 'OBJECT')
        self.report({'INFO'}, f"Generated {len(faces)} bones, empties, and constraints.")
        return {'FINISHED'}


class FTB_OT_cleanup_face_bones(bpy.types.Operator):
    bl_idname = "ftb.cleanup_face_bones"
    bl_label = "Cleanup Face Bones & Empties"
    bl_description = "Remove all generated bones, empties and their constraints"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        arma_obj = scene.ftb_armature_object
        prefix = scene.ftb_object_prefix_name.strip()
        if not prefix:
            self.report({'ERROR'}, "Object prefix is empty")
            return {'CANCELLED'}

        removed_bones = 0
        if arma_obj and arma_obj.type == 'ARMATURE':
            set_active(context, arma_obj, 'EDIT')
            for eb in list(arma_obj.data.edit_bones):
                if eb.name.startswith(prefix + BONE_TAG):
                    arma_obj.data.edit_bones.remove(eb)
                    removed_bones += 1
            bpy.ops.object.mode_set(mode='OBJECT')

        removed_empties = 0
        for o in list(bpy.data.objects):
            if o.type == 'EMPTY' and o.name.startswith(prefix + TARGET_TAG):
                bpy.data.objects.remove(o, do_unlink=True)
                removed_empties += 1

        self.report({'INFO'}, f"Removed {removed_bones} bones and {removed_empties} empties.")
        return {'FINISHED'}


class FTB_OT_toggle_constraints(bpy.types.Operator):
    bl_idname = "ftb.toggle_constraints"
    bl_label = "Toggle Copy Transforms Constraints"
    bl_description = "Enable or disable the Copy Transforms constraints on the generated bones"
    bl_options = {'REGISTER', 'UNDO'}

    enable: bpy.props.BoolProperty(name="Enable Constraints", default=False)

    def execute(self, context):
        scene = context.scene
        arma_obj = scene.ftb_armature_object
        if arma_obj is None or arma_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Valid armature object not specified")
            return {'CANCELLED'}

        count = 0
        for con in iter_generated_constraints(arma_obj, scene.ftb_object_prefix_name.strip()):
            con.enabled = self.enable
            count += 1
        arma_obj.update_tag()
        state = "enabled" if self.enable else "disabled"
        self.report({'INFO'}, f"{count} Copy Transforms constraints {state}.")
        return {'FINISHED'}


class FTB_OT_remove_constraints(bpy.types.Operator):
    bl_idname = "ftb.remove_constraints"
    bl_label = "Remove Copy Transforms Constraints"
    bl_description = "Remove the Copy Transforms constraints from the generated bones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        arma_obj = scene.ftb_armature_object
        if arma_obj is None or arma_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Valid armature object not specified")
            return {'CANCELLED'}

        prefix = scene.ftb_object_prefix_name.strip()
        removed = 0
        for pbone in arma_obj.pose.bones:
            if pbone.name.startswith(prefix + BONE_TAG):
                for con in [c for c in pbone.constraints if c.type == 'COPY_TRANSFORMS']:
                    pbone.constraints.remove(con)
                    removed += 1
        self.report({'INFO'}, f"Removed {removed} Copy Transforms constraints.")
        return {'FINISHED'}


TEST_SCENE_NAME = "SimToBones Test"
TEST_PREFIX = "TST"  # separate from the user's prefix: object names are global
TEST_COLLECTION_NAME = "SimToBones Test Bones"


def build_cape_mesh(name, width=1.2, height=1.6, cols=6, rows=8):
    """Vertical grid in the XZ plane, top edge at z=0, hanging down -Z."""
    verts = []
    for r in range(rows + 1):
        for c in range(cols + 1):
            verts.append((-width / 2 + width * c / cols, 0.0, -height * r / rows))
    faces = []
    for r in range(rows):
        for c in range(cols):
            a = r * (cols + 1) + c
            faces.append((a, a + 1, a + cols + 2, a + cols + 1))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    top_row = list(range(cols + 1))
    return mesh, top_row


class FTB_OT_create_test_scene(bpy.types.Operator):
    bl_idname = "ftb.create_test_scene"
    bl_label = "Create Test Scene"
    bl_description = (
        "Create a separate scene with an animated armature and a cloth cape, "
        "ready to try Generate Face Bones without touching your project"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        old = bpy.data.scenes.get(TEST_SCENE_NAME)
        if old is not None:
            if context.window and context.window.scene == old:
                other = next((s for s in bpy.data.scenes if s != old), None)
                if other is None:
                    other = bpy.data.scenes.new("Scene")
                context.window.scene = other
            # Only delete objects that exist solely in the test scene.
            for o in list(old.objects):
                if all(s == old for s in o.users_scene):
                    bpy.data.objects.remove(o, do_unlink=True)
            test_col = bpy.data.collections.get(TEST_COLLECTION_NAME)
            if test_col is not None and not test_col.objects and not test_col.children:
                bpy.data.collections.remove(test_col)
            bpy.data.scenes.remove(old)

        scn = bpy.data.scenes.new(TEST_SCENE_NAME)
        scn.frame_start, scn.frame_end = 1, 100
        if context.window:
            context.window.scene = scn
        view_layer = scn.view_layers[0]

        # Armature: one bone standing upright, animated side to side.
        arm_data = bpy.data.armatures.new("TestRig")
        arm = bpy.data.objects.new("TestRig", arm_data)
        arm.show_in_front = True
        scn.collection.objects.link(arm)

        with context.temp_override(scene=scn, view_layer=view_layer,
                                   active_object=arm, object=arm):
            view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode='EDIT')
            eb = arm_data.edit_bones.new("Root")
            eb.head, eb.tail = (0, 0, 0), (0, 0, 1.8)
            bpy.ops.object.mode_set(mode='OBJECT')

        for frame, x, rz in ((1, 0.0, 0.0), (30, 1.5, 0.6), (60, -1.5, -0.6), (90, 0.0, 0.0)):
            arm.location.x = x
            arm.rotation_euler.z = rz
            arm.keyframe_insert("location", index=0, frame=frame)
            arm.keyframe_insert("rotation_euler", index=2, frame=frame)
        arm.location.x = 0.0
        arm.rotation_euler.z = 0.0

        # Cape: cloth grid pinned along its top edge, parented to the rig.
        mesh, top_row = build_cape_mesh("TestCape")
        cape = bpy.data.objects.new("TestCape", mesh)
        scn.collection.objects.link(cape)
        cape.parent = arm
        cape.location = (0.0, -0.25, 1.6)
        pin = cape.vertex_groups.new(name="Pin")
        pin.add(top_row, 1.0, 'REPLACE')

        cloth = cape.modifiers.new("Cloth", 'CLOTH')
        cloth.settings.vertex_group_mass = pin.name
        cloth.settings.quality = 5
        cloth.point_cache.frame_start = scn.frame_start
        cloth.point_cache.frame_end = scn.frame_end

        # Pre-fill the panel so the user can just click Generate.
        scn.ftb_mesh_object = cape
        scn.ftb_armature_object = arm
        scn.ftb_object_prefix_name = TEST_PREFIX
        scn.ftb_collection_name = TEST_COLLECTION_NAME
        scn.ftb_bone_length = 0.1
        scn.frame_set(1)

        for o in view_layer.objects.selected:
            o.select_set(False, view_layer=view_layer)
        cape.select_set(True, view_layer=view_layer)
        view_layer.objects.active = cape

        self.report({'INFO'}, f'Created scene "{TEST_SCENE_NAME}". Click Generate Face Bones & Empties, then play the animation.')
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class FTB_PT_panel(bpy.types.Panel):
    bl_label = "Face to Bones"
    bl_idname = "FTB_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FaceTools'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.use_property_split = True
        layout.use_property_decorate = False

        box = layout.box()
        box.use_property_split = False
        box.label(text="New here? Try it on a sample first:", icon='INFO')
        box.operator("ftb.create_test_scene", icon='SCENE_DATA')
        layout.separator()

        layout.prop(scene, "ftb_mesh_object")
        layout.prop(scene, "ftb_armature_object")
        layout.prop(scene, "ftb_object_prefix_name")
        layout.prop(scene, "ftb_collection_name")
        layout.prop(scene, "ftb_bone_length")
        layout.prop(scene, "ftb_empty_type")

        layout.separator()
        layout.prop(scene, "ftb_use_weight_filter", text="Filter by Vertex Group Weight")
        if scene.ftb_use_weight_filter:
            layout.prop(scene, "ftb_weight_vgroup", text="Vertex Group")
            layout.prop(scene, "ftb_weight_threshold", text="Weight Threshold")

        layout.separator()
        col = layout.column(align=True)
        col.use_property_split = False
        col.operator("ftb.generate_face_bones", icon='BONE_DATA')
        col.operator("ftb.cleanup_face_bones", icon='TRASH')

        layout.separator()
        row = layout.row(align=True)
        row.operator("ftb.toggle_constraints", text="Enable Constraints", icon='CHECKBOX_HLT').enable = True
        row.operator("ftb.toggle_constraints", text="Disable Constraints", icon='CHECKBOX_DEHLT').enable = False
        layout.operator("ftb.remove_constraints", icon='CONSTRAINT_BONE')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    FTB_OT_generate_face_bones,
    FTB_OT_cleanup_face_bones,
    FTB_OT_toggle_constraints,
    FTB_OT_remove_constraints,
    FTB_OT_create_test_scene,
    FTB_PT_panel,
)

scene_props = {
    "ftb_mesh_object": lambda: bpy.props.PointerProperty(
        name="Mesh Object", type=bpy.types.Object,
        poll=lambda self, o: o.type == 'MESH'),
    "ftb_armature_object": lambda: bpy.props.PointerProperty(
        name="Armature Object", type=bpy.types.Object,
        poll=lambda self, o: o.type == 'ARMATURE'),
    "ftb_object_prefix_name": lambda: bpy.props.StringProperty(
        name="Object Prefix", default="VX"),
    "ftb_collection_name": lambda: bpy.props.StringProperty(
        name="Collection Name", default="VX AutoBones"),
    "ftb_bone_length": lambda: bpy.props.FloatProperty(
        name="Bone Length", default=0.1, min=0.001, unit='LENGTH'),
    "ftb_empty_type": lambda: bpy.props.EnumProperty(
        name="Empty Type",
        items=[('ARROWS', "Arrows", ""), ('PLAIN_AXES', "Plain Axes", ""), ('CUBE', "Cube", "")],
        default='ARROWS'),
    "ftb_use_weight_filter": lambda: bpy.props.BoolProperty(
        name="Use Weight Filter",
        description="Only use faces whose average vertex group weight is above the threshold",
        default=False),
    "ftb_weight_vgroup": lambda: bpy.props.EnumProperty(
        name="Vertex Group",
        description="Vertex group used to filter faces",
        items=vertex_group_items),
    "ftb_weight_threshold": lambda: bpy.props.FloatProperty(
        name="Weight Threshold",
        description="Minimum average weight for a face to be processed",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR'),
}


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for name, make in scene_props.items():
        setattr(bpy.types.Scene, name, make())


def unregister():
    for name in scene_props:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    # Allow re-running the script from the Text Editor.
    try:
        unregister()
    except Exception:
        pass
    register()
