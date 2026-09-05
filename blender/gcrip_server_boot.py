"""Start Blender with the GCRip add-on and its control server.

    blender --python blender/gcrip_server_boot.py -- [--addon <gcrip_blender.py>] [--port 8788]
    blender -b --python blender/gcrip_server_boot.py -- ...      (headless worker)

GUI: the add-on is loaded from disk (or the installed copy is enabled) and the server
starts; you keep using Blender normally while tools/blender_mcp.py drives it.
Headless: the script blocks pumping commands until a `shutdown` command arrives, then
Blender exits.
"""

import importlib.util
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
opts = {"--addon": "", "--port": ""}
for i, a in enumerate(args):
    if a in opts and i + 1 < len(args):
        opts[a] = args[i + 1]
port = int(opts["--port"] or os.environ.get("GCRIP_BLENDER_PORT") or 8788)

mod = sys.modules.get("gcrip_blender")
if mod is None:
    try:  # an installed copy of the add-on
        bpy.ops.preferences.addon_enable(module="gcrip_blender")
        mod = sys.modules.get("gcrip_blender")
    except Exception:  # noqa: BLE001
        mod = None
if mod is None:
    path = opts["--addon"] or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "gcrip_blender.py"
    )
    spec = importlib.util.spec_from_file_location("gcrip_blender", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gcrip_blender"] = mod
    spec.loader.exec_module(mod)
    mod.register()

# a fresh scene without the startup cube/light/camera in headless mode
if bpy.app.background and not bpy.data.filepath:
    bpy.ops.wm.read_homefile(use_empty=True)
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

mod.server_start(port)
if bpy.app.background:
    mod.server_loop()
