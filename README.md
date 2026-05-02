This script automates the process shown in this video: (https://youtu.be/1cXyIjaFxXY?si=8r_-1oLmTwKitgUG&t=750)

How to use it in Blender:

Import the script into Blender and run it.
Open the Face to Bones panel in the sidebar.
In Mesh Object, select your cape mesh.
In Armature Object, select your character’s armature/skeleton.
Leave Object Prefix as the default value unless you have a specific reason to change it.
In Collection Name, enter the name of the collection that will store all generated empties.
If the collection does not exist, the updated script will create it automatically.
Click Generate Face Bones & Empties.

The generated bones should now follow the cape simulation.

To bake the animation:

Insert Visual Keyframes to save the motion.
Once the animation is complete, click Disable Constraints.
Disable the cape simulation/animation.
Play back the animation to verify the result.
