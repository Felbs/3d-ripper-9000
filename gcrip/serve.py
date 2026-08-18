"""Serve a rip folder locally so report.html can open models in Blender.

    gcrip serve out/rip/GZLE01 [--port 8765] [--blender PATH]

Opens http://127.0.0.1:8765/report.html. Static files come from the rip folder; two
tiny endpoints let the page act on your machine:

    /open?path=<rel .blend or .gltf>   launch Blender on that file (imports the glTF
                                        through the add-on if no .blend exists yet)
    /reveal?path=<rel>                  show the file in Explorer / Finder
    /glb?path=<rel .gltf>               download the model as one self-contained .glb

Only paths inside the served folder are accepted; the server binds to localhost.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from gcrip.blend import addon_path, find_blender
from gcrip.export import glb as glbmod


def _open_blender(exe: str, path: Path) -> None:
    if path.suffix == ".blend":
        subprocess.Popen([exe, str(path)])
        return
    # no .blend yet: start Blender and import the glTF via the add-on's importer
    addon = addon_path()
    expr = (
        "import bpy,importlib.util,sys\n"
        f"p={str(addon)!r}\n"
        "if p and p!='None':\n"
        "    s=importlib.util.spec_from_file_location('gcrip_blender',p);m=importlib.util."
        "module_from_spec(s);s.loader.exec_module(m);m.register()\n"
        f"    bpy.ops.gcrip.import_gltf(filepath={str(path)!r})\n"
        "else:\n"
        f"    bpy.ops.import_scene.gltf(filepath={str(path)!r})\n"
        "bpy.context.scene.render.fps=30\n"
    )
    subprocess.Popen([exe, "--python-expr", expr])


def _reveal(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def make_handler(root: Path, blender: str | None):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def handle(self):
            # browser closed the connection early; not our problem
            with contextlib.suppress(ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                super().handle()

        def log_message(self, fmt, *args):  # quieter
            if "/open" in str(args[0]) or "/reveal" in str(args[0]):
                sys.stderr.write("%s\n" % (fmt % args))

        def _json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _target(self, query: dict) -> Path | None:
            rel = query.get("path", [""])[0]
            p = (root / rel).resolve()
            if not rel or root not in p.parents and p != root or not p.exists():
                return None
            return p

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path in ("/open", "/reveal"):
                q = urllib.parse.parse_qs(u.query)
                p = self._target(q)
                if p is None:
                    return self._json(404, {"error": "no such file inside the rip folder"})
                if u.path == "/open":
                    if not blender:
                        msg = "Blender not found; restart with --blender PATH"
                        return self._json(500, {"error": msg})
                    threading.Thread(target=_open_blender, args=(blender, p), daemon=True).start()
                    return self._json(200, {"opened": str(p)})
                _reveal(p)
                return self._json(200, {"revealed": str(p)})
            if u.path == "/glb":
                # self-contained download: pack .gltf + .bin + textures on the fly
                q = urllib.parse.parse_qs(u.query)
                p = self._target(q)
                if p is None or p.suffix != ".gltf":
                    return self._json(404, {"error": "no such .gltf inside the rip folder"})
                try:
                    data = glbmod.pack(p)
                except Exception as e:  # noqa: BLE001
                    return self._json(500, {"error": f"pack failed: {e}"})
                self.send_response(200)
                self.send_header("Content-Type", "model/gltf-binary")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'attachment; filename="{p.stem}.glb"')
                self.end_headers()
                self.wfile.write(data)
                return None
            if u.path == "/status":
                return self._json(200, {"blender": blender, "root": str(root)})
            return super().do_GET()

    return Handler


def serve(game_dir: Path, *, port: int = 8765, blender: str | None = None, open_browser=True):
    root = Path(game_dir).resolve()
    exe = find_blender(blender)
    handler = make_handler(root, exe)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/report.html"
    print(f"serving {root}\n  {url}\n  Blender: {exe or 'NOT FOUND (pass --blender)'}")
    print("Ctrl+C to stop")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    serve(Path(sys.argv[1]), port=int(os.environ.get("PORT", 8765)))
