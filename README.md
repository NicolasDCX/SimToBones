This script automates the process shown in this video: (https://youtu.be/1cXyIjaFxXY?si=8r_-1oLmTwKitgUG&t=750)

Works with Blender 4.2 – 5.3 (tested on 5.3). SimToBones is a Blender extension.

Install:

Download sim_to_bones-x.y.z.zip from the Releases page (or build it yourself, see below).

In Blender, go to Edit > Preferences > Get Extensions, open the dropdown at the top right, and choose Install from Disk. Pick the zip. (You can also drag and drop the zip into the Blender window.)

Build the zip from source:

blender --command extension build --source-dir sim_to_bones --output-dir dist

How to use it:

Open the Face to Bones panel in the sidebar.

First time? Click Create Test Scene. It creates a separate scene called "SimToBones Test" with an animated rig and a cloth cape, and fills in the panel for you. Click Generate Face Bones & Empties, then press play to watch the bones follow the cape. Your own scenes are not touched; switch back with the scene selector at the top of the window, and delete the test scene when you're done.

In Mesh Object, select your cape mesh.

In Armature Object, select your character’s armature/skeleton.

Leave Object Prefix as the default value unless you have a specific reason to change it.

In Collection Name, enter the name of the collection that will store all generated empties.

If the collection does not exist, the script will create it automatically.

Click Generate Face Bones & Empties.

The generated bones should now follow the cape simulation.

To bake the animation:

Insert Visual Keyframes to save the motion.

Once the animation is complete, click Disable Constraints.

Disable the cape simulation/animation.

Play back the animation to verify the result.

