"""Render one demo-reel shot from gcrip glTF output (see make_reel.py for the shot JSON).

blender -b --python reel_shot.py -- shot.json
"""

import importlib.util
import json
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
with open(argv[0], encoding="utf-8") as fh:
    cfg = json.load(fh)
ADDON = cfg["addon"]

bpy.ops.wm.read_factory_settings(use_empty=True)
spec = importlib.util.spec_from_file_location("gcrip_blender", ADDON)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.register()

scene = bpy.context.scene
scene.render.fps = 30
scene.render.resolution_x = cfg.get("width", 1280)
scene.render.resolution_y = cfg.get("height", 720)
scene.frame_start = 1
scene.frame_end = cfg["frames"]
scene.render.engine = cfg.get("engine", "BLENDER_EEVEE")
if hasattr(scene, "eevee"):
    scene.eevee.taa_render_samples = 16
    scene.eevee.use_shadows = True
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = "VIDEO"
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.filepath = cfg["out"]
scene.render.film_transparent = False

# world
world = bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (*cfg.get("bg", (0.08, 0.09, 0.11)), 1)
bg.inputs[1].default_value = 1.0

# lights
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 3.0
sun.data.angle = math.radians(20)
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(35))
scene.collection.objects.link(sun)
fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "SUN"))
fill.data.energy = 1.2
fill.rotation_euler = (math.radians(60), 0, math.radians(-120))
scene.collection.objects.link(fill)


def family_bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        if o.type != "MESH" or o.hide_get():
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def play(arm, clip, frames, start=1):
    """Loop `clip` on the armature via one NLA strip with repeat."""
    ad = arm.animation_data
    if ad is None:
        return
    act = bpy.data.actions.get(clip)
    if act is None:
        cands = [a for a in bpy.data.actions if a.name.startswith(clip)]
        if not cands:
            print("NO CLIP", clip)
            return
        act = cands[0]
    slot = None
    for t in ad.nla_tracks:
        for s in t.strips:
            if s.action == act:
                slot = getattr(s, "action_slot", None)
    for t in list(ad.nla_tracks):
        ad.nla_tracks.remove(t)
    ad.action = None
    tr = ad.nla_tracks.new()
    st = tr.strips.new(clip, start, act)
    if slot is not None:
        try:
            st.action_slot = slot
        except Exception as e:  # noqa: BLE001
            print("slot", e)
    length = max(1.0, act.frame_range[1] - act.frame_range[0])
    st.repeat = max(1, math.ceil(frames / length) + 1)
    st.blend_type = "REPLACE"


roots = []
all_lo = Vector((1e9,) * 3)
all_hi = Vector((-1e9,) * 3)
for m in cfg["models"]:
    before = set(bpy.data.objects)
    bpy.ops.gcrip.import_gltf(filepath=m["path"], mixamo=False)
    new = [o for o in bpy.data.objects if o not in before]
    tops = [o for o in new if o.parent is None]
    arms = [o for o in new if o.type == "ARMATURE"]
    # group under one empty so we can place it
    empty = bpy.data.objects.new(m.get("name", "model"), None)
    scene.collection.objects.link(empty)
    for t in tops:
        t.parent = empty
    if arms and m.get("clip"):
        play(arms[0], m["clip"], cfg["frames"])
    for o in new:
        if o.type == "MESH" and any(o.name.startswith(h) for h in m.get("hide", [])):
            o.hide_render = True
            o.hide_set(True)
    scale = m.get("scale", 1.0)
    empty.scale = (scale,) * 3
    empty.location = Vector(m.get("pos", (0, 0, 0)))
    empty.rotation_euler = (0, 0, math.radians(m.get("yaw", 0)))
    bpy.context.view_layer.update()
    lo, hi = family_bounds(new)
    all_lo = Vector(map(min, all_lo, lo))
    all_hi = Vector(map(max, all_hi, hi))
    print("MODEL", m["path"], "bounds", [round(x, 1) for x in lo], [round(x, 1) for x in hi])
    # expression cycling: keyframe visibility of clones of listed base materials
    if m.get("expressions"):
        groups = mod.expression_groups(new)
        step = m.get("expr_step", 20)
        for base, (base_obj, clones) in groups.items():
            if base not in m["expressions"]:
                continue
            options = [("", base_obj)] + [(t, o) for t, o in clones]
            options = [o for o in options if o[1] is not None]
            for f in range(1, cfg["frames"] + 1, step):
                k = (f // step) % len(options)
                for i, (_t, o) in enumerate(options):
                    hidden = i != k
                    o.hide_render = hidden
                    o.keyframe_insert("hide_render", frame=f)
                    o.hide_viewport = hidden
                    o.keyframe_insert("hide_viewport", frame=f)

# ground
center = (all_lo + all_hi) / 2
size = max(all_hi.x - all_lo.x, all_hi.z - all_lo.z, all_hi.y - all_lo.y)
plane_mesh = bpy.data.meshes.new("ground")
s = size * 6
plane_mesh.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
ground = bpy.data.objects.new("ground", plane_mesh)
ground.location = (center.x, center.y, all_lo.z)
mat = bpy.data.materials.new("groundmat")
mat.diffuse_color = (*cfg.get("ground", (0.16, 0.17, 0.2)), 1)
mat.use_nodes = True
ground_rgb = cfg.get("ground", (0.16, 0.17, 0.2))
mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (*ground_rgb, 1)
mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
plane_mesh.materials.append(mat)
scene.collection.objects.link(ground)

# camera: 3/4 view framing all models, slow orbit/pan
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
cam.data.lens = cfg.get("lens", 45)
scene.collection.objects.link(cam)
scene.camera = cam
target = Vector((center.x, center.y, all_lo.z + (all_hi.z - all_lo.z) * cfg.get("look_h", 0.5)))
dist = size * cfg.get("dist", 2.7)
cam.data.clip_start = 0.05
cam.data.clip_end = dist * 6
orbit = cfg.get("orbit", (-35, 15))  # start yaw deg, sweep deg
elev = math.radians(cfg.get("elev", 12))
for f, ang in ((1, orbit[0]), (cfg["frames"], orbit[0] + orbit[1])):
    a = math.radians(ang)
    pos = target + Vector(
        (
            math.sin(a) * dist * math.cos(elev),
            -math.cos(a) * dist * math.cos(elev),
            dist * math.sin(elev),
        )
    )
    cam.location = pos
    d = target - pos
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_euler", frame=f)
_act = cam.animation_data.action
for fc in _act.fcurves if hasattr(_act, "fcurves") else []:
    for k in fc.keyframe_points:
        k.interpolation = "LINEAR"

# caption text parented to camera


def caption(text, size, y, name):
    fo = bpy.data.objects.new(name, bpy.data.curves.new(name, "FONT"))
    fo.data.body = text
    fo.data.size = size
    fo.data.align_x = "LEFT"
    m2 = bpy.data.materials.new(name + "m")
    m2.use_nodes = True
    bsdf = m2.node_tree.nodes["Principled BSDF"]
    bsdf.inputs[0].default_value = (1, 1, 1, 1)
    bsdf.inputs["Emission Color"].default_value = (1, 1, 1, 1)
    bsdf.inputs["Emission Strength"].default_value = 1.5
    fo.data.materials.append(m2)
    scene.collection.objects.link(fo)
    fo.parent = cam
    fo.location = (-0.62, y, -1.6)
    fo.rotation_euler = (0, 0, 0)
    fo.scale = (1, 1, 1)
    return fo


if cfg.get("title"):
    caption(cfg["title"], 0.06, -0.27, "title")
if cfg.get("subtitle"):
    caption(cfg["subtitle"], 0.03, -0.32, "subtitle")

bpy.ops.wm.save_as_mainfile(filepath=cfg["out"].replace(".mp4", ".blend"))
if cfg.get("still"):
    if hasattr(scene.render.image_settings, "media_type"):
        scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = cfg["still"]
    scene.frame_set(cfg.get("still_frame", 20))
    bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
print("SHOT_DONE")
