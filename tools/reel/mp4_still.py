"""Grab PNG stills from an mp4 with Blender's sequencer (no ffmpeg needed).

blender -b --python mp4_still.py -- reel.mp4 out_frame_N.png 60 260 400
"""

import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1 :]
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y, sc.render.fps = 1280, 720, 30
se = sc.sequence_editor_create()
new_movie = se.strips.new_movie if hasattr(se, "strips") else se.sequences.new_movie
new_movie("m", argv[0], 1, 1)
sc.render.image_settings.file_format = "PNG"
sc.view_settings.view_transform = "Standard"  # the video is already display-referred
for f in argv[2:]:
    sc.frame_set(int(f))
    sc.render.filepath = argv[1].replace("N", f)
    bpy.ops.render.render(write_still=True)
