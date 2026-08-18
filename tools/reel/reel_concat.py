"""Concatenate shot mp4s with short crossfades into one reel via Blender's VSE."""

import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1 :]
out = argv[0]
clips = argv[1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 30
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = "VIDEO"
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.filepath = out
scene.view_settings.view_transform = "Standard"  # strips are already display-referred
se = scene.sequence_editor_create()
FADE = 12
start = 1
strips = []
for i, path in enumerate(clips):
    ch = 1 + (i % 2)
    new_movie = se.strips.new_movie if hasattr(se, "strips") else se.sequences.new_movie
    s = new_movie(f"c{i}", path, ch, start)
    strips.append(s)
    if i > 0:
        prev = strips[i - 1]
        # crossfade: overlap by FADE frames
        s.frame_start = start - FADE
        # add cross effect on channel 3
        eff_new = se.strips.new_effect if hasattr(se, "strips") else se.sequences.new_effect
        try:
            eff_new(
                name=f"x{i}",
                type="CROSS",
                channel=3,
                frame_start=int(s.frame_start),
                length=FADE,
                input1=prev,
                input2=s,
            )
        except TypeError:
            eff_new(
                name=f"x{i}",
                type="CROSS",
                channel=3,
                frame_start=int(s.frame_start),
                frame_end=int(s.frame_start + FADE),
                seq1=prev,
                seq2=s,
            )
        start = int(s.frame_start)
    start = int(start + s.frame_final_duration)
scene.frame_start = 1
scene.frame_end = int(start - 1)
print("REEL FRAMES", scene.frame_end)
bpy.ops.render.render(animation=True)
print("CONCAT_DONE")
