# SimToBones

**Turn a cloth simulation into bone animation in Blender.**

Cloth simulations (capes, skirts, flags…) look great in Blender, but game engines and many export formats only understand armatures and bones. SimToBones adds one bone per face of your simulated mesh, makes each bone follow its face, and lets you bake the result into regular keyframes you can export.

It automates the technique shown in [this video](https://youtu.be/1cXyIjaFxXY?si=8r_-1oLmTwKitgUG&t=750).

- Works with **Blender 4.2 to 5.3** (tested on 5.3)
- Packaged as a Blender **extension**
- Includes a one-click **test scene** to try it out safely

---

## How it works

For every face of the mesh (or only the faces you choose with a vertex group), SimToBones:

1. **Creates a bone** in your armature, placed at the center of the face and pointing along its normal.
2. **Creates an empty** at the same spot and parents it to three vertices of the face, so the empty rides along with the simulation.
3. **Adds a Copy Transforms constraint** to the bone, targeting the empty, so the bone follows the cloth.

You then bake the bones' motion into keyframes and switch off the simulation. The armature now plays the cloth motion on its own.

---

## Installation

1. Download `sim_to_bones-x.y.z.zip` from the [Releases](https://github.com/NicolasDCX/SimToBones/releases) page, or [build it yourself](#building-from-source).
2. In Blender, open **Edit > Preferences > Get Extensions**.
3. Click the **⌄** dropdown at the top right and choose **Install from Disk…**, then pick the zip.
   *(Or simply drag and drop the zip into the Blender window.)*

The tool then appears in the 3D Viewport sidebar (press **N**) under the **FaceTools** tab.

---

## Quick start: try it on the test scene

Not sure yet? Try it on a sample first, without touching your project.

1. Open the **FaceTools** tab in the sidebar.
2. Click **Create Test Scene**.
   A new scene named *SimToBones Test* is created with an animated armature and a cloth cape, and the panel is filled in for you.
3. Click **Generate Face Bones & Empties**.
4. Press **Play**. The bones swing along with the cape.

When you're done, switch back to your own scene with the scene selector at the top of the Blender window, and delete the test scene. Clicking **Create Test Scene** again rebuilds it from scratch.

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

Click **Generate Face Bones & Empties**, then play the animation. The new bones should follow the cloth.

### 4. Bake the animation

The bones only follow the cloth because of their constraints. To turn this into real keyframes:

1. Select the armature and enter **Pose Mode**.
2. Select the generated bones (their names start with your prefix, e.g. `VXBone_…`).
3. Bake the motion into keyframes, either:
   - with **Pose > Animation > Bake Action…**, ticking **Visual Keying** (recommended, it bakes the whole frame range in one go), or
   - by inserting **Visual** keyframes manually.
4. Back in the **FaceTools** panel, click **Disable Constraints**.
5. Disable the cloth simulation (or its modifier) on the mesh.
6. Play the animation to check the result. The bones should move exactly as before, now driven by keyframes only.

---

## Panel buttons

| Button | What it does |
|---|---|
| **Create Test Scene** | Builds a separate sample scene to try the tool. |
| **Generate Face Bones & Empties** | Creates the bones, empties and constraints. |
| **Cleanup Face Bones & Empties** | Deletes every bone and empty created with the current prefix. |
| **Enable / Disable Constraints** | Turns the Copy Transforms constraints of the generated bones on or off, which is useful after baking. |
| **Remove Copy Transforms Constraints** | Deletes those constraints entirely. |

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
- **Bones don't move**: make sure the cloth simulation actually plays (check its cache frame range), and that the constraints are enabled.

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
