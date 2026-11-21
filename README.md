# SimToBones

**Turn a cloth simulation into bone animation in Blender.**

Cloth simulations (capes, skirts, flags…) look great in Blender, but game engines and many export formats only understand armatures and bones. SimToBones adds one bone per face of your simulated mesh, makes each bone follow its face, bakes the result into regular keyframes, and skins the mesh to those bones, so you get a rigged, animated cape you can export.

It automates the technique shown in [this video](https://youtu.be/1cXyIjaFxXY?si=8r_-1oLmTwKitgUG&t=750).

- Works with **Blender 4.2 to 5.3** (tested on 5.3)
- Packaged as a Blender **extension**
- Includes a **step-by-step guide** and a **test scene** to learn it safely

---

## How it works

For every face of the mesh (or only the faces you choose with a vertex group), SimToBones:

1. **Creates a bone** in your armature, placed at the center of the face and pointing along its normal.
2. **Creates an empty** at the same spot and parents it to three vertices of the face, so the empty rides along with the simulation.
3. **Adds a Copy Transforms constraint** to the bone, targeting the empty, so the bone follows the cloth.

Then:

4. **Bake to Keyframes** records the bones' motion as keyframes.
5. The constraints and the simulation are switched off. The bones now play the motion on their own.
6. **Skin Mesh to Bones** weights every vertex to the bones of the faces around it and adds an Armature modifier, so the mesh follows the bones. The result is an ordinary skinned mesh, with no simulation left.

---

## Installation

1. Download `sim_to_bones-x.y.z.zip` from the [Releases](https://github.com/NicolasDCX/SimToBones/releases) page, or [build it yourself](#building-from-source).
2. In Blender, open **Edit > Preferences > Get Extensions**.
3. Click the **⌄** dropdown at the top right and choose **Install from Disk…**, then pick the zip.
   *(Or simply drag and drop the zip into the Blender window.)*

The tool then appears in the 3D Viewport sidebar (press **N**) under the **FaceTools** tab.

---

## Quick start: the Step by Step guide

The **Step by Step** panel at the top of the FaceTools tab walks you through the whole process, one button per step. Each step unlocks once the previous one is done, ✔ marks the finished steps, and the current step shows a short explanation of what it does.

| Step | What happens | What you'll see when you press Play |
|---|---|---|
| **1. Create Test Scene** | Builds a separate scene *SimToBones Test* with an animated rig and a cloth cape, and fills in the settings. Nothing is generated or baked yet. | The cape swings with the rig. |
| **2. Add Bones** | Adds one bone per face of the cape. | The bones stay still. |
| **3. Add Empties** | Adds an empty on each bone, glued to its face. | The empties follow the cloth, the bones don't. |
| **4. Add Constraints** | Makes each bone copy its empty. | The bones follow the cloth live, but nothing is recorded. |
| **5. Bake to Keyframes** | Plays the whole frame range and records every bone's motion as keyframes. | Same motion, now also saved as keys. |
| **6. Disable Constraints & Simulation** | Turns off the cloth and the constraints. | The bones still move, driven only by their keyframes, but the cape is frozen because it isn't weighted to the bones yet. |
| **7. Skin Mesh to Bones** | Weights each vertex to the bones of its faces and adds an Armature modifier. | The cape follows the bones, with no simulation at all. Done! |

Use **Play / Pause** under the steps to check each stage, and **Start Over** to remove everything and go back to step 2.

Your own scenes are not touched. When you're done, switch back with the scene selector at the top of the Blender window and delete the test scene. Clicking **Create Test Scene** again rebuilds it from scratch.

You can also follow the guide on your own project: skip step 1 by picking your mesh and armature in the **Face to Bones** panel.

---

## Using it on your own project

### 1. Prepare your scene

- A **mesh** with its cloth simulation set up and working (for example a cape).
- Your character's **armature**.

> **Tip:** each face becomes one bone. A low-poly simulation mesh (a few dozen faces) gives a much lighter rig than a high-poly one.

### 2. Fill in the panel

| Setting | What it does |
|---|---|
| **Mesh Object** | The simulated mesh (your cape). |
| **Armature Object** | The armature that will receive the new bones. |
| **Object Prefix** | Text added in front of every generated bone and empty name (default `VX`). Keep the default unless you run the tool several times in the same file. Each run needs its own prefix. |
| **Collection Name** | Collection that will hold the generated empties. It is created automatically if it doesn't exist. |
| **Bone Length** | Length of each generated bone. |
| **Empty Type** | How the empties are displayed in the viewport. This is purely visual. |
| **Filter by Vertex Group Weight** | Only generate bones for some faces. See [Weight filter](#weight-filter). |

### 3. Generate

Click **Generate Face Bones & Empties**, which runs steps 2 to 4 of the guide in one go, then play the animation. The new bones should follow the cloth.

### 4. Bake the animation

The bones only follow the cloth because of their constraints. To turn this into real keyframes:

1. Set the scene's frame range (**Start** / **End**) to the part of the animation you want.
2. Click **Bake to Keyframes**. The tool plays through the range from the first frame and keys every generated bone on every frame.
3. Click **Constraints Off** and **Simulation Off** (or **Disable Constraints & Simulation** in the guide).
4. Play the animation. The bones move exactly as before, now driven by keyframes only, but the mesh stays still.

### 5. Skin the mesh

Click **Skin Mesh to Bones**. Each vertex gets a weight for the bones of the faces around it (shared equally), and an Armature modifier named *SimToBones Skin* is added to the mesh. Play the animation: the mesh now follows the bones closely. On the test scene it is about 4 mm off on average from the real simulation, for a cape that moves 1.5 m.

Good to know:

- Vertices without a bone of their own (faces skipped by the weight filter) are given to the nearest bone.
- Other Armature modifiers on the mesh that use the **same** armature are switched off while the skin is active, because they would read the new weights too and deform the mesh twice. They are switched back on by **Simulation On** or **Cleanup**.
- Skin and live simulation can't run together, since the mesh would follow the bones while the bones follow the mesh. So **Simulation On** and **Constraints On** remove the skin. After re-baking, click **Skin Mesh to Bones** again.
- The mesh should keep the same position relative to the armature as when the bones were generated. Parenting the mesh to the armature is the easiest way.

Baking again replaces the previous bake. You can also bake with Blender's own **Pose > Animation > Bake Action…** (with **Visual Keying**) if you prefer.

---

## Panel buttons

**Face to Bones** panel:

| Button | What it does |
|---|---|
| **Generate Face Bones & Empties** | Adds the bones, empties and constraints in one go. |
| **Bake to Keyframes** | Records the bones' motion over the scene frame range as keyframes. |
| **Skin Mesh to Bones** | Weights the mesh to the generated bones and adds an Armature modifier, so the mesh follows them. |
| **Cleanup Face Bones & Empties** | Deletes everything created with the current prefix (bones, empties, constraints, baked keys, skin weights) and re-enables the simulation. |
| **Constraints On / Off** | Turns the Copy Transforms constraints of the generated bones on or off. **On** removes the skin. |
| **Simulation On / Off** | Turns the mesh's cloth / soft body modifiers on or off. **On** removes the skin. |
| **Remove Copy Transforms Constraints** | Deletes the constraints entirely. |

**Step by Step** panel: the seven guided steps above, plus **Play / Pause** and **Start Over**.

---

## Weight filter

Often you don't want bones on every face. The part of the cape sewn to the shoulders, for example, doesn't need any.

1. On your mesh, create a vertex group and paint the faces you **want** bones on with a high weight.
2. Enable **Filter by Vertex Group Weight**, pick the group and set a **Weight Threshold**.

A face gets a bone only if the average weight of its vertices is at least the threshold.

---

## Troubleshooting

- **"Prefix is already used"**: bones or empties with this prefix already exist. Click **Cleanup** first, or choose another prefix.
- **"Filtering enabled but no valid vertex group selected"**: pick a vertex group, or turn off the weight filter.
- **Bones don't move**: make sure the cloth simulation actually plays (check its cache frame range), and that the constraints and the simulation are enabled.
- **"Constraints are disabled" / "The simulation is disabled" when baking**: turn them back on first. The bake records what the constraints produce.
- **The mesh doesn't move after baking**: run **Skin Mesh to Bones** (step 7).
- **The skin disappeared**: **Simulation On** or **Constraints On** removes it on purpose. Bake again, then skin again.
- **A step button is greyed out** in the guide: finish the previous step first.

---

## Building from source

The extension lives in the `sim_to_bones/` folder. To build the installable zip:

```bash
blender --command extension build --source-dir sim_to_bones --output-dir dist
```

The zip is written to `dist/`.

---

## License

[MIT](LICENSE). Copyright © 2026 Nicolas D.
