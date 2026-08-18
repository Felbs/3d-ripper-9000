"""Runs INSIDE Blender (headless): turn ripped glTF models into .blend asset files.

    blender -b --python gcrip/blender_batch.py -- jobs.json

jobs.json: {"addon": ".../gcrip_blender.py" | null, "game": "GZLE01",
            "jobs": [{"gltf": abs path, "blend": abs path, "thumb": abs path | null,
                      "name": "cl", "catalog": "GZLE01/res/Object/Link.arc",
                      "catalog_id": uuid, "description": "...", "tags": [...]}, ...]}

For each job: fresh empty file -> import glTF (through the gcrip add-on when available so
expression/alternate meshes are hidden and bones can carry Mixamo names) -> put everything
in a collection named after the model -> mark that collection as an asset with the rip
thumbnail as its preview -> save. Progress lines "BLEND_OK <i>" / "BLEND_ERR <i> <msg>" go
to stdout for the caller.
"""

import importlib.util
import json
import sys
import traceback

import bpy

argv = sys.argv[sys.argv.index("--") + 1 :]
with open(argv[0], encoding="utf-8") as fh:
    cfg = json.load(fh)

addon = None
if cfg.get("addon"):
    try:
        spec = importlib.util.spec_from_file_location("gcrip_blender", cfg["addon"])
        addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(addon)
        addon.register()
    except Exception as e:  # noqa: BLE001
        print("ADDON_FAIL", e)
        addon = None


def import_model(path):
    if addon is not None:
        bpy.ops.gcrip.import_gltf(filepath=path, mixamo=False)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
        for o in bpy.data.objects:
            if o.type == "MESH" and "gcrip_variant_of" in o:
                o.hide_render = True
                o.hide_set(True)


def one(job):
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    import_model(job["gltf"])
    objs = list(bpy.data.objects)
    col = bpy.data.collections.new(job["name"])
    scene.collection.children.link(col)
    for o in objs:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        col.objects.link(o)
    # asset metadata
    col.asset_mark()
    ad = col.asset_data
    ad.description = job.get("description", "")
    ad.author = "gcrip"
    if job.get("catalog_id"):
        ad.catalog_id = job["catalog_id"]
    for t in job.get("tags", []):
        ad.tags.new(t, skip_if_exists=True)
    if job.get("thumb"):
        try:
            with bpy.context.temp_override(id=col):
                bpy.ops.ed.lib_id_load_custom_preview(filepath=job["thumb"])
        except Exception as e:  # noqa: BLE001
            print("PREVIEW_FAIL", e)
    # keep textures external but relative to the .blend
    bpy.ops.wm.save_as_mainfile(filepath=job["blend"], compress=True, relative_remap=True)


for i, job in enumerate(cfg["jobs"]):
    try:
        one(job)
        print(f"BLEND_OK {i}", flush=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"BLEND_ERR {i} {e}", flush=True)
print("BATCH_DONE", flush=True)
