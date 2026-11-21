# SimToBones - Blender extension. Metadata lives in blender_manifest.toml.

import bpy

BONE_TAG = "Bone_"
TARGET_TAG = "Target_"
CONSTRAINT_NAME = "Copy Transforms"
PHYSICS_MODIFIERS = {'CLOTH', 'SOFT_BODY'}
SKIN_MOD_NAME = "SimToBones Skin"
DISABLED_MODS_KEY = "simtobones_disabled_modifiers"


class StepError(Exception):
    """A step can't run; the message is shown to the user."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_prefix(scene):
    prefix = scene.ftb_object_prefix_name.strip()
    if not prefix:
        raise StepError("Object prefix is empty")
    return prefix


def get_mesh(scene):
    obj = scene.ftb_mesh_object
    if obj is None or obj.type != 'MESH':
        raise StepError("Pick a Mesh Object first")
    return obj


def get_armature(scene):
    arm = scene.ftb_armature_object
    if arm is None or arm.type != 'ARMATURE':
        raise StepError("Pick an Armature Object first")
    return arm


def get_or_create_collection(context, col_name):
    """Get or create a collection linked to the current scene."""
    col_name = (col_name or "").strip()
    if not col_name:
        raise StepError("Collection name is empty")
    col = bpy.data.collections.get(col_name)
    if col is None:
        col = bpy.data.collections.new(col_name)
    if col.name not in context.scene.collection.children:
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


def ensure_object_mode(context):
    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def collect_faces(obj, vgroup=None, threshold=0.0):
    """Snapshot face data as {index: (world center, world normal, first 3 verts)}.

    Everything is copied into plain Python values up front: mesh.polygons must
    not be read while switching modes (Blender reallocates the mesh arrays,
    which crashes Blender 5.x).
    """
    mesh = obj.data
    mw = obj.matrix_world
    nm = mw.to_3x3().inverted_safe().transposed()  # correct normal transform
    faces = {}

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
        faces[poly.index] = ((mw @ poly.center).copy(), (nm @ poly.normal).normalized(), vids[:3])
    return faces


def face_index(name, prefix, tag):
    """'VXBone_12' -> 12, or None if the name isn't one of ours."""
    head = prefix + tag
    if name.startswith(head) and name[len(head):].isdigit():
        return int(name[len(head):])
    return None


def generated_bones(arm, prefix):
    """{face index: pose bone} for the bones created with this prefix."""
    out = {}
    for pb in arm.pose.bones:
        idx = face_index(pb.name, prefix, BONE_TAG)
        if idx is not None:
            out[idx] = pb
    return out


def generated_empties(prefix):
    out = {}
    for o in bpy.data.objects:
        if o.type == 'EMPTY':
            idx = face_index(o.name, prefix, TARGET_TAG)
            if idx is not None:
                out[idx] = o
    return out


def iter_generated_constraints(arm, prefix):
    for pb in generated_bones(arm, prefix).values():
        for con in pb.constraints:
            if con.type == 'COPY_TRANSFORMS':
                yield con


def physics_modifiers(obj):
    return [m for m in obj.modifiers if m.type in PHYSICS_MODIFIERS] if obj else []


def action_fcurves(id_data):
    """F-curves of the ID's action (layered actions on 4.4+/5.x, legacy before)."""
    ad = id_data.animation_data
    if ad is None or ad.action is None:
        return None
    action = ad.action
    try:
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
    except ImportError:
        return action.fcurves
    channelbag = action_get_channelbag_for_slot(action, ad.action_slot)
    return channelbag.fcurves if channelbag else None


def baked_fcurves(arm, prefix):
    fcurves = action_fcurves(arm)
    if not fcurves:
        return fcurves, []
    head = f'pose.bones["{prefix}{BONE_TAG}'
    return fcurves, [fc for fc in fcurves if fc.data_path.startswith(head)]


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


# ---------------------------------------------------------------------------
# Steps (plain functions, so they can run one by one or all at once)
# ---------------------------------------------------------------------------

def step_add_bones(context):
    """Step 2: one bone per face, at the face center, pointing along its normal."""
    scene = context.scene
    obj, arm, prefix = get_mesh(scene), get_armature(scene), get_prefix(scene)

    if generated_bones(arm, prefix) or generated_empties(prefix):
        raise StepError(f'Prefix "{prefix}" is already used, run Cleanup or pick another prefix')

    vgroup = None
    if scene.ftb_use_weight_filter:
        vgroup = obj.vertex_groups.get(scene.ftb_weight_vgroup)
        if vgroup is None:
            raise StepError("Filtering enabled but no valid vertex group selected")

    ensure_object_mode(context)
    faces = collect_faces(obj, vgroup, scene.ftb_weight_threshold)
    if not faces:
        raise StepError("No faces matched, nothing generated")

    set_active(context, arm, 'EDIT')
    arm_inv = arm.matrix_world.inverted_safe()
    arm_rot_inv = arm.matrix_world.to_3x3().inverted_safe()
    for idx, (center, normal, _vids) in faces.items():
        head = arm_inv @ center
        eb = arm.data.edit_bones.new(f"{prefix}{BONE_TAG}{idx}")
        eb.head = head
        eb.tail = head + (arm_rot_inv @ normal).normalized() * scene.ftb_bone_length
    bpy.ops.object.mode_set(mode='OBJECT')
    return f"Added {len(faces)} bones."


def step_add_empties(context):
    """Step 3: an empty per bone, glued to 3 vertices of its face."""
    scene = context.scene
    obj, arm, prefix = get_mesh(scene), get_armature(scene), get_prefix(scene)

    bones = generated_bones(arm, prefix)
    if not bones:
        raise StepError("No generated bones yet, run Add Bones first")
    if generated_empties(prefix):
        raise StepError("Empties already exist, run Cleanup to start over")

    ensure_object_mode(context)
    col = get_or_create_collection(context, scene.ftb_collection_name)
    faces = collect_faces(obj)

    empties = []
    for idx, pb in bones.items():
        if idx not in faces:
            continue
        empty = bpy.data.objects.new(f"{prefix}{TARGET_TAG}{idx}", None)
        empty.empty_display_type = scene.ftb_empty_type
        empty.empty_display_size = scene.ftb_bone_length
        col.objects.link(empty)
        # Vertex parent: the empty rides along with the (simulated) face.
        empty.parent = obj
        empty.parent_type = 'VERTEX_3'
        empty.parent_vertices = faces[idx][2]
        # Same placement as the bone's rest pose, so nothing jumps later.
        empty.matrix_basis = arm.matrix_world @ pb.bone.matrix_local
        empties.append(empty)

    # Parent inverse keeps the placement (same as Ctrl+P > Make Vertex Parent).
    context.view_layer.update()
    for empty in empties:
        parent_mat = empty.matrix_world @ empty.matrix_basis.inverted_safe()
        empty.matrix_parent_inverse = parent_mat.inverted_safe()
    context.view_layer.update()
    return f"Added {len(empties)} empties."


def step_add_constraints(context):
    """Step 4: each bone copies the transforms of its empty."""
    scene = context.scene
    arm, prefix = get_armature(scene), get_prefix(scene)

    bones, empties = generated_bones(arm, prefix), generated_empties(prefix)
    if not empties:
        raise StepError("No empties yet, run Add Empties first")

    added = 0
    for idx, pb in bones.items():
        empty = empties.get(idx)
        if empty is None or any(c.type == 'COPY_TRANSFORMS' for c in pb.constraints):
            continue
        con = pb.constraints.new(type='COPY_TRANSFORMS')
        con.name = CONSTRAINT_NAME
        con.target = empty
        added += 1
    if not added:
        raise StepError("Constraints are already there")
    context.view_layer.update()
    return f"Added {added} Copy Transforms constraints."


def step_bake(context):
    """Step 6: record the constraint-driven motion as keyframes on each bone."""
    scene = context.scene
    arm, prefix = get_armature(scene), get_prefix(scene)

    bones = generated_bones(arm, prefix)
    if not any(pb.constraints for pb in bones.values()):
        raise StepError("Nothing to bake, add the constraints first")
    if any(not c.enabled for c in iter_generated_constraints(arm, prefix)):
        raise StepError("Constraints are disabled, enable them before baking")
    obj = scene.ftb_mesh_object
    if obj and any(not (m.show_viewport and m.show_render) for m in physics_modifiers(obj)):
        raise StepError("The simulation is disabled, enable it before baking")

    ensure_object_mode(context)
    frame_start, frame_end = scene.frame_start, scene.frame_end
    current = scene.frame_current

    # Remove a previous bake of these bones first.
    fcurves, old = baked_fcurves(arm, prefix)
    for fc in old:
        fcurves.remove(fc)

    # Play through the range from the start so the simulation runs in order,
    # and store each bone's visual pose converted to its own local space.
    samples = {name: [] for name in (pb.name for pb in bones.values())}
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        for pb in bones.values():
            m = arm.convert_space(pose_bone=pb, matrix=pb.matrix, from_space='POSE', to_space='LOCAL')
            samples[pb.name].append((frame, m))

    for name, frames in samples.items():
        pb = arm.pose.bones[name]
        pb.rotation_mode = 'QUATERNION'
        prev = None
        for frame, m in frames:
            loc, rot, scale = m.decompose()
            if prev is not None:
                rot.make_compatible(prev)  # avoid 360° flips between keys
            prev = rot
            pb.location, pb.rotation_quaternion, pb.scale = loc, rot, scale
            pb.keyframe_insert("location", frame=frame, group=name)
            pb.keyframe_insert("rotation_quaternion", frame=frame, group=name)
            pb.keyframe_insert("scale", frame=frame, group=name)

    scene.frame_set(current)
    return f"Baked {len(bones)} bones over frames {frame_start}-{frame_end}."


def set_constraints(arm, prefix, enabled):
    count = 0
    for con in iter_generated_constraints(arm, prefix):
        con.enabled = enabled
        count += 1
    arm.update_tag()
    return count


def skin_modifier(obj):
    m = obj.modifiers.get(SKIN_MOD_NAME) if obj else None
    return m if m and m.type == 'ARMATURE' else None


def remove_skin(obj, prefix):
    """Delete the skin modifier + generated vertex groups, restore the
    armature modifiers the skin step had switched off."""
    if obj is None or obj.type != 'MESH':
        return False
    removed = False
    mod = skin_modifier(obj)
    if mod:
        obj.modifiers.remove(mod)
        removed = True
    for vg in list(obj.vertex_groups):
        if face_index(vg.name, prefix, BONE_TAG) is not None:
            obj.vertex_groups.remove(vg)
            removed = True
    for name in obj.get(DISABLED_MODS_KEY, []):
        m = obj.modifiers.get(name)
        if m:
            m.show_viewport = m.show_render = True
    if DISABLED_MODS_KEY in obj:
        del obj[DISABLED_MODS_KEY]
    obj.update_tag()
    return removed


def retarget_constraints(arm, prefix):
    """Point each generated bone's constraint back at its empty (by name)."""
    if arm is None or arm.type != 'ARMATURE':
        return
    empties = generated_empties(prefix)
    for idx, pb in generated_bones(arm, prefix).items():
        for con in pb.constraints:
            if con.type == 'COPY_TRANSFORMS' and con.target is None and idx in empties:
                con.target = empties[idx]


def go_live(scene):
    """Back to 'bones follow the simulation': remove the skin and reconnect the
    constraints. Skin and live constraints can't coexist: the mesh would follow
    the bones while the bones follow the mesh (dependency cycle)."""
    prefix = scene.ftb_object_prefix_name.strip()
    if not prefix:
        return
    remove_skin(scene.ftb_mesh_object, prefix)
    retarget_constraints(scene.ftb_armature_object, prefix)


def set_simulation(obj, enabled):
    mods = physics_modifiers(obj)
    for m in mods:
        m.show_viewport = enabled
        m.show_render = enabled
    if obj:
        obj.update_tag()
    return len(mods)


def step_finish(context):
    """Step 6: switch off constraints + simulation, the keyframes take over."""
    scene = context.scene
    arm, prefix = get_armature(scene), get_prefix(scene)
    if not baked_fcurves(arm, prefix)[1]:
        raise StepError("Bake to Keyframes first, or the bones would stop moving")
    n_con = set_constraints(arm, prefix, False)
    n_sim = set_simulation(scene.ftb_mesh_object, False)
    return (f"Disabled {n_con} constraints and {n_sim} simulation modifier(s). "
            "The bones play their keyframes; next, skin the mesh to them.")


def step_skin(context):
    """Step 7: weight every vertex to the bones of its faces + Armature modifier."""
    scene = context.scene
    obj, arm, prefix = get_mesh(scene), get_armature(scene), get_prefix(scene)

    bones = generated_bones(arm, prefix)
    if not bones:
        raise StepError("No generated bones yet")
    if not baked_fcurves(arm, prefix)[1]:
        raise StepError("Bake to Keyframes first")
    if any(c.enabled for c in iter_generated_constraints(arm, prefix)) or \
            any(m.show_viewport for m in physics_modifiers(obj)):
        raise StepError("Disable the constraints and the simulation first "
                        "(the bones still follow the mesh, skinning now would make a loop)")

    ensure_object_mode(context)
    remove_skin(obj, prefix)

    # Snapshot topology: which generated faces touch each vertex.
    mesh = obj.data
    vert_faces = {}
    face_centers = {}
    for poly in mesh.polygons:
        if poly.index in bones:
            face_centers[poly.index] = poly.center.copy()
            for vid in poly.vertices:
                vert_faces.setdefault(vid, []).append(poly.index)
    if not face_centers:
        raise StepError("The generated bones don't match this mesh's faces")
    vert_cos = [v.co.copy() for v in mesh.vertices]

    groups = {}

    def group_for(idx):
        if idx not in groups:
            groups[idx] = obj.vertex_groups.new(name=bones[idx].name)
        return groups[idx]

    for vid, co in enumerate(vert_cos):
        faces = vert_faces.get(vid)
        if faces:
            # Shared equally between the faces around the vertex.
            w = 1.0 / len(faces)
            for idx in faces:
                group_for(idx).add([vid], w, 'REPLACE')
        else:
            # Vertex with no bone of its own (weight filter): nearest face's bone.
            idx = min(face_centers, key=lambda i: (face_centers[i] - co).length_squared)
            group_for(idx).add([vid], 1.0, 'REPLACE')

    # Other Armature modifiers on the same rig would also read these groups
    # (they're named after bones) and deform the mesh twice: switch them off.
    disabled = []
    for m in obj.modifiers:
        if m.type == 'ARMATURE' and m.object == arm and m.show_viewport:
            m.show_viewport = m.show_render = False
            disabled.append(m.name)
    if disabled:
        obj[DISABLED_MODS_KEY] = disabled

    # Even disabled, a constraint keeps a dependency on its target; clear the
    # targets so mesh -> bones -> empties -> mesh isn't a cycle.
    # (Re-connected by Simulation On / Constraints On / Cleanup.)
    for con in iter_generated_constraints(arm, prefix):
        con.target = None

    mod = obj.modifiers.new(SKIN_MOD_NAME, 'ARMATURE')
    mod.object = arm
    mod.use_vertex_groups = True
    mod.use_bone_envelopes = False
    obj.update_tag()

    msg = f"Skinned {len(vert_cos)} vertices to {len(groups)} bones. Press Play: the mesh follows the bones."
    if disabled:
        msg += f" Switched off: {', '.join(disabled)}."
    return msg


def cleanup(context):
    scene = context.scene
    prefix = get_prefix(scene)
    arm = scene.ftb_armature_object

    removed_bones = removed_keys = 0
    if arm and arm.type == 'ARMATURE':
        fcurves, old = baked_fcurves(arm, prefix)
        for fc in old:
            fcurves.remove(fc)
        removed_keys = len(old)

        if generated_bones(arm, prefix):
            set_active(context, arm, 'EDIT')
            for eb in list(arm.data.edit_bones):
                if face_index(eb.name, prefix, BONE_TAG) is not None:
                    arm.data.edit_bones.remove(eb)
                    removed_bones += 1
            bpy.ops.object.mode_set(mode='OBJECT')

    empties = generated_empties(prefix)
    for o in empties.values():
        bpy.data.objects.remove(o, do_unlink=True)

    go_live(scene)
    set_simulation(scene.ftb_mesh_object, True)
    msg = f"Removed {removed_bones} bones and {len(empties)} empties"
    if removed_keys:
        msg += " and the baked keyframes"
    return msg + "."


def guide_state(scene):
    """Which steps are done, for the step-by-step panel."""
    state = dict(setup=False, bones=False, empties=False, constraints=False,
                 baked=False, finished=False, skinned=False)
    obj, arm = scene.ftb_mesh_object, scene.ftb_armature_object
    prefix = scene.ftb_object_prefix_name.strip()
    if not (obj and obj.type == 'MESH' and arm and arm.type == 'ARMATURE' and prefix):
        return state
    state["setup"] = True
    bones = generated_bones(arm, prefix)
    state["bones"] = bool(bones)
    state["empties"] = bool(generated_empties(prefix))
    cons = list(iter_generated_constraints(arm, prefix))
    state["constraints"] = bool(cons)
    state["baked"] = bool(baked_fcurves(arm, prefix)[1])
    sim_off = all(not m.show_viewport for m in physics_modifiers(obj))
    state["finished"] = state["baked"] and bool(cons) and all(not c.enabled for c in cons) and sim_off
    state["skinned"] = state["finished"] and skin_modifier(obj) is not None
    return state


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class StepOperator(bpy.types.Operator):
    """Runs a step function and reports its result or error."""
    bl_options = {'REGISTER', 'UNDO'}
    step = None

    def execute(self, context):
        try:
            msg = type(self).step(context)
        except StepError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class FTB_OT_add_bones(StepOperator):
    bl_idname = "ftb.add_bones"
    bl_label = "Add Bones"
    bl_description = "Add one bone per face of the mesh, at the face center, pointing along its normal"
    step = step_add_bones


class FTB_OT_add_empties(StepOperator):
    bl_idname = "ftb.add_empties"
    bl_label = "Add Empties"
    bl_description = "Add an empty on each bone and vertex-parent it to its face, so it follows the simulation"
    step = step_add_empties


class FTB_OT_add_constraints(StepOperator):
    bl_idname = "ftb.add_constraints"
    bl_label = "Add Constraints"
    bl_description = "Make each bone copy the transforms of its empty, so the bones follow the cloth live"
    step = step_add_constraints


class FTB_OT_generate_face_bones(StepOperator):
    bl_idname = "ftb.generate_face_bones"
    bl_label = "Generate Face Bones & Empties"
    bl_description = "Add bones, empties and constraints in one go (steps 2 to 4)"

    @staticmethod
    def step(context):
        step_add_bones(context)
        step_add_empties(context)
        msg = step_add_constraints(context)
        return "Generated bones, empties and constraints. " + msg


class FTB_OT_bake(StepOperator):
    bl_idname = "ftb.bake"
    bl_label = "Bake to Keyframes"
    bl_description = "Play through the scene frame range and record the bones' motion as keyframes"
    step = step_bake


class FTB_OT_finish(StepOperator):
    bl_idname = "ftb.finish"
    bl_label = "Disable Constraints & Simulation"
    bl_description = "Turn off the constraints and the cloth simulation: the baked keyframes now drive the bones"
    step = step_finish


class FTB_OT_skin(StepOperator):
    bl_idname = "ftb.skin"
    bl_label = "Skin Mesh to Bones"
    bl_description = ("Weight each vertex to the bones of its faces and add an Armature modifier, "
                      "so the mesh follows the baked bones")
    step = step_skin


class FTB_OT_cleanup_face_bones(StepOperator):
    bl_idname = "ftb.cleanup_face_bones"
    bl_label = "Cleanup Face Bones & Empties"
    bl_description = "Remove the generated bones, empties, constraints, baked keyframes and skin weights, and re-enable the simulation"
    step = cleanup


class FTB_OT_toggle_constraints(bpy.types.Operator):
    bl_idname = "ftb.toggle_constraints"
    bl_label = "Toggle Copy Transforms Constraints"
    bl_description = ("Enable or disable the Copy Transforms constraints on the generated bones. "
                      "Enabling them removes the skin (bones and mesh would follow each other in a loop)")
    bl_options = {'REGISTER', 'UNDO'}

    enable: bpy.props.BoolProperty(name="Enable Constraints", default=False)

    def execute(self, context):
        try:
            arm, prefix = get_armature(context.scene), get_prefix(context.scene)
        except StepError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if self.enable:
            go_live(context.scene)
        count = set_constraints(arm, prefix, self.enable)
        state = "enabled" if self.enable else "disabled"
        self.report({'INFO'}, f"{count} Copy Transforms constraints {state}.")
        return {'FINISHED'}


class FTB_OT_toggle_simulation(bpy.types.Operator):
    bl_idname = "ftb.toggle_simulation"
    bl_label = "Toggle Simulation"
    bl_description = ("Enable or disable the cloth / soft body modifiers of the mesh. "
                      "Enabling it removes the skin (bones and mesh would follow each other in a loop)")
    bl_options = {'REGISTER', 'UNDO'}

    enable: bpy.props.BoolProperty(name="Enable Simulation", default=False)

    def execute(self, context):
        if self.enable:
            go_live(context.scene)
        count = set_simulation(context.scene.ftb_mesh_object, self.enable)
        state = "enabled" if self.enable else "disabled"
        self.report({'INFO'}, f"{count} simulation modifier(s) {state}.")
        return {'FINISHED'}


class FTB_OT_remove_constraints(bpy.types.Operator):
    bl_idname = "ftb.remove_constraints"
    bl_label = "Remove Copy Transforms Constraints"
    bl_description = "Remove the Copy Transforms constraints from the generated bones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            arm, prefix = get_armature(context.scene), get_prefix(context.scene)
        except StepError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        removed = 0
        for pb in generated_bones(arm, prefix).values():
            for con in [c for c in pb.constraints if c.type == 'COPY_TRANSFORMS']:
                pb.constraints.remove(con)
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
        "Create a separate scene with an animated armature and a cloth cape "
        "(no bones generated yet), to try the tool without touching your project"
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

        # Pre-fill the panel so the user can go straight to the next step.
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

        self.report({'INFO'}, f'Created scene "{TEST_SCENE_NAME}". Press Play to watch the cloth, then continue with step 2.')
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

# (state key, operator, button text, explanation lines)
GUIDE_STEPS = (
    ("setup", "ftb.create_test_scene", "Create Test Scene", (
        "Builds a sample scene: an animated rig",
        "and a cloth cape. Nothing is baked yet.",
        "Press Play to watch the cloth swing.",
        "(Or pick your own mesh + armature below.)",
    )),
    ("bones", "ftb.add_bones", "Add Bones", (
        "Adds one bone per face of the cape,",
        "pointing out of the face.",
        "The bones don't move yet.",
    )),
    ("empties", "ftb.add_empties", "Add Empties", (
        "Adds an empty on each bone, glued to",
        "3 vertices of its face. Press Play:",
        "the empties follow the cloth.",
    )),
    ("constraints", "ftb.add_constraints", "Add Constraints", (
        "Each bone now copies its empty.",
        "Press Play: the bones follow the cloth",
        "live, but nothing is recorded yet.",
    )),
    ("baked", "ftb.bake", "Bake to Keyframes", (
        "Plays the whole frame range and records",
        "every bone's motion as keyframes.",
    )),
    ("finished", "ftb.finish", "Disable Constraints & Simulation", (
        "Turns off the cloth and the constraints.",
        "Press Play: the bones still move, now",
        "driven only by their keyframes... but",
        "the cape is frozen: it isn't weighted",
        "to the bones yet.",
    )),
    ("skinned", "ftb.skin", "Skin Mesh to Bones", (
        "Weights each vertex to the bones of",
        "its faces and adds an Armature modifier.",
        "Press Play: the cape follows the bones,",
        "with no simulation at all. Done!",
    )),
)


class FTB_PT_guide(bpy.types.Panel):
    bl_label = "Step by Step"
    bl_idname = "FTB_PT_guide"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FaceTools'
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        state = guide_state(scene)
        current = next((key for key, *_ in GUIDE_STEPS if not state[key]), None)

        prev_done = True
        for number, (key, op, text, help_lines) in enumerate(GUIDE_STEPS, start=1):
            done = state[key]
            col = layout.column(align=True)
            row = col.row(align=True)
            row.enabled = prev_done or key == "setup"
            row.label(text="", icon='CHECKMARK' if done else ('PLAY' if key == current else 'RADIOBUT_OFF'))
            row.operator(op, text=f"{number}. {text}", depress=done)
            if key == current:
                box = col.box()
                for line in help_lines:
                    box.label(text=line)
            prev_done = done

        layout.separator()
        row = layout.row(align=True)
        row.operator("screen.animation_play", text="Play / Pause", icon='PLAY')
        row.operator("ftb.cleanup_face_bones", text="Start Over", icon='LOOP_BACK')
        if current is None:
            layout.label(text="All steps done!", icon='CHECKMARK')


class FTB_PT_panel(bpy.types.Panel):
    bl_label = "Face to Bones"
    bl_idname = "FTB_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FaceTools'
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.use_property_split = True
        layout.use_property_decorate = False

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
        col.operator("ftb.bake", icon='KEYINGSET')
        col.operator("ftb.skin", icon='MOD_ARMATURE')
        col.operator("ftb.cleanup_face_bones", icon='TRASH')

        layout.separator()
        row = layout.row(align=True)
        row.operator("ftb.toggle_constraints", text="Constraints On", icon='CHECKBOX_HLT').enable = True
        row.operator("ftb.toggle_constraints", text="Off", icon='CHECKBOX_DEHLT').enable = False
        row = layout.row(align=True)
        row.operator("ftb.toggle_simulation", text="Simulation On", icon='CHECKBOX_HLT').enable = True
        row.operator("ftb.toggle_simulation", text="Off", icon='CHECKBOX_DEHLT').enable = False
        layout.operator("ftb.remove_constraints", icon='CONSTRAINT_BONE')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    FTB_OT_add_bones,
    FTB_OT_add_empties,
    FTB_OT_add_constraints,
    FTB_OT_generate_face_bones,
    FTB_OT_bake,
    FTB_OT_finish,
    FTB_OT_skin,
    FTB_OT_cleanup_face_bones,
    FTB_OT_toggle_constraints,
    FTB_OT_toggle_simulation,
    FTB_OT_remove_constraints,
    FTB_OT_create_test_scene,
    FTB_PT_guide,
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
