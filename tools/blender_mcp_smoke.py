"""Smoke-test the Blender control channel end to end, headless.

    python tools/blender_mcp_smoke.py <out_dir> [query] [game_id]

Launches a background Blender with the add-on (blender/gcrip_server_boot.py), lists the
library, spawns the first mocap-ready rig matching the query, aims a camera, renders a
still, saves the .blend and shuts the worker down.  Uses port 8790 so it
never collides with a Blender you have open on the default 8788.
"""

import json
import os
import sys
import time

os.environ.setdefault("GCRIP_BLENDER_PORT", "8790")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_mcp as bm  # noqa: E402

out_dir = sys.argv[1]
query = sys.argv[2] if len(sys.argv) > 2 else "homer"
gid = sys.argv[3] if len(sys.argv) > 3 else ""
os.makedirs(out_dir, exist_ok=True)


def step(label, fn, *a, **kw):
    t0 = time.time()
    try:
        res = fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        print(f"[{label}] FAILED after {time.time() - t0:.1f}s: {e}")
        raise
    txt = json.dumps(res, default=str)
    print(f"[{label}] {time.time() - t0:.1f}s {txt[:600]}")
    return res


launch = step("launch", bm.blender_launch, background=True, wait=180)
if not (launch.get("launched") or launch.get("already_running")):
    sys.exit("Blender did not come up - see " + launch.get("log", ""))
try:
    games = step("games", bm.call, "games")
    print(f"   {len(games)} games, {sum(g['rigs'] for g in games)} mocap-ready rigs")
    rows = step("library", bm.call, "library", gid=gid, query=query, humanoid=True, limit=5)
    if not rows:
        sys.exit(f"no mocap-ready rig matching {query!r}")
    sp = step("spawn", bm.call, "spawn", gltf=rows[0]["gltf"], at=[0, 0, 0])
    step("characters", bm.call, "characters")
    step(
        "python", bm.call, "python", code="import bpy\nresult = [o.name for o in bpy.data.objects]"
    )
    step("camera", bm.call, "camera")
    step(
        "light",
        bm.call,
        "python",
        code=(
            "import bpy\n"
            "sun = bpy.data.objects.new('GCRipSun', bpy.data.lights.new('GCRipSun', 'SUN'))\n"
            "bpy.context.scene.collection.objects.link(sun)\n"
            "sun.rotation_euler = (0.9, 0.2, 0.8); sun.data.energy = 3\n"
            "result = 'sun added'"
        ),
    )
    sc = step("scene", bm.call, "scene")
    lo, hi = sc["range"]
    step("frame", bm.call, "frame", frame=min(lo + 40, hi))
    step(
        "render", bm.call, "render", path=os.path.join(out_dir, "still.png"), width=640, height=480
    )
    step(
        "render2",
        bm.call,
        "render",
        path=os.path.join(out_dir, "still2.png"),
        frame=min(lo + 90, hi),
    )
    step("save", bm.call, "save", path=os.path.join(out_dir, "smoke.blend"))
finally:
    step("shutdown", bm.call, "shutdown")
print("OK ->", out_dir)
