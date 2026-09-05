"""MCP server that drives a running Blender through the GCRip add-on's control channel.

The add-on (blender/gcrip_blender.py, "GCRip Server" panel) listens on 127.0.0.1:8788 for
one JSON request per line and answers one JSON reply per line; every tool here is one such
round trip.  Blender executes the command on its main thread, so this bridge never has to
know about bpy.  Start it from Claude Code via .mcp.json ("gcrip-blender"), or by hand:

    GCRIP_BLENDER_PORT=8788 python tools/blender_mcp.py

Getting a Blender up: press "Start control server" in the add-on's GCRip Server panel, tick
"Start the control server with Blender" in the add-on preferences, or call `blender_launch`
here (spawns Blender with blender/gcrip_server_boot.py; `background=True` for a headless
render worker that exits on `blender_shutdown`).
"""

from __future__ import annotations

import glob
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

HOST = "127.0.0.1"
PORT = int(os.environ.get("GCRIP_BLENDER_PORT", "8788"))
TIMEOUT = float(os.environ.get("GCRIP_BLENDER_TIMEOUT", "900"))  # renders take a while
HERE = Path(__file__).resolve().parent
ADDON = Path(os.environ.get("GCRIP_ADDON") or HERE.parent / "blender" / "gcrip_blender.py")
BOOT = HERE.parent / "blender" / "gcrip_server_boot.py"

mcp = FastMCP("gcrip-blender")
_seq = 0


def find_blender() -> str:
    """The Blender executable: env GCRIP_BLENDER_EXE, else the newest installed one."""
    exe = os.environ.get("GCRIP_BLENDER_EXE")
    if exe:
        return exe
    if sys.platform == "win32":
        hits = glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe")
        if hits:
            return sorted(hits, key=lambda p: p.split("Blender ")[-1])[-1]
    return "blender"


def call(cmd: str, **args: Any) -> Any:
    """One request to Blender; raises RuntimeError with Blender's message on failure."""
    global _seq
    _seq += 1
    try:
        sock = socket.create_connection((HOST, PORT), timeout=TIMEOUT)
    except OSError as e:
        raise RuntimeError(
            f"no Blender listening on {HOST}:{PORT} ({e}). In Blender: N panel > GCRip > "
            "GCRip Server > Start control server, or call blender_launch here."
        ) from None
    try:
        with sock.makefile("rwb") as f:
            f.write(
                (
                    json.dumps({"id": _seq, "cmd": cmd, "args": args, "timeout": TIMEOUT}) + "\n"
                ).encode()
            )
            f.flush()
            line = f.readline()
    finally:
        sock.close()
    if not line:
        raise RuntimeError("Blender closed the connection without answering")
    resp = json.loads(line)
    if not resp.get("ok"):
        msg = resp.get("error", "unknown error")
        if resp.get("trace"):
            msg += "\n" + resp["trace"]
        raise RuntimeError(msg)
    return resp.get("result")


@mcp.tool()
def blender_status() -> dict:
    """Is a Blender with the GCRip control server up?  Version, open file, frame, counts."""
    try:
        return {"running": True, **call("ping")}
    except RuntimeError as e:
        return {"running": False, "error": str(e), "port": PORT}


@mcp.tool()
def blender_launch(background: bool = False, blend: str = "", wait: int = 90) -> dict:
    """Start Blender with the GCRip add-on and its control server (blender/gcrip_server_boot.py).
    ``background=True`` = headless worker (no window; exits on blender_shutdown).  ``blend``
    opens that file.  Waits up to ``wait`` seconds for the server to answer."""
    st = blender_status()
    if st.get("running"):
        return {"already_running": True, **st}
    exe = find_blender()
    cmd = [exe]
    if background:
        cmd.append("-b")
    if blend:
        cmd.append(blend)
    cmd += ["--python", str(BOOT), "--", "--addon", str(ADDON), "--port", str(PORT)]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
    log = HERE.parent / "out" / "blender_server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, creationflags=flags)
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(1.0)
        try:
            return {"launched": True, "pid": proc.pid, "log": str(log), **call("ping")}
        except RuntimeError:
            if proc.poll() is not None:
                break
    return {
        "launched": False,
        "pid": proc.pid,
        "exit": proc.poll(),
        "log": str(log),
        "hint": f"no answer on port {PORT} after {wait}s - read the log",
    }


@mcp.tool()
def blender_games(query: str = "") -> list[dict]:
    """Games in the add-on's library index (id, title, model count, mocap-ready rig count)."""
    return call("games", query=query)


@mcp.tool()
def blender_library(
    gid: str = "", category: str = "", query: str = "", humanoid: bool = False, limit: int = 100
) -> list[dict]:
    """Browse the add-on's library index like the Library panel.  ``category``: CHARACTER |
    CREATURE | ITEM | VEHICLE | PROP | LEVEL | MISC | ALL.  ``humanoid=True`` keeps only
    mocap-ready rigs (``rig`` = 'mixamo' from the ripper's map, 'guess' from joint names).
    Rows carry the glTF path to pass to blender_spawn."""
    return call("library", gid=gid, category=category, query=query, humanoid=humanoid, limit=limit)


@mcp.tool()
def blender_spawn(
    gltf: str = "",
    gid: str = "",
    name: str = "",
    at: list[float] | None = None,
    mixamo: bool = True,
) -> dict:
    """Import a model into the scene: by ``gltf`` path, or ``gid`` + ``name`` as listed by
    blender_library.  ``at`` = [x, y, z] for the root (levels stay at the origin).  Characters
    get Mixamo bone names (guessed from the joint tree when the rip has no map), so the
    result says whether the rig is mocap_ready."""
    return call("spawn", gltf=gltf, gid=gid, name=name, at=at, mixamo=mixamo)


@mcp.tool()
def blender_characters() -> list[dict]:
    """Armatures in the scene: bones, Mixamo-mapped bones, missing core bones, NLA tracks."""
    return call("characters")


@mcp.tool()
def blender_map_bones(object: str = "", force: bool = False) -> dict:  # noqa: A002
    """Guess and apply Mixamo bone names on a rig (needed before retargeting a rig that was
    imported some other way).  ``force`` re-guesses even if a map exists."""
    return call("map_bones", object=object, force=force)


@mcp.tool()
def blender_retarget(
    bvh: str,
    object: str = "",
    start: int = 1,
    max_frames: int = 0,
    mute_game: bool = True,  # noqa: A002
) -> dict:
    """Retarget a BVH clip (Bandai Namco dataset, ComfyUI-MotionCapture output, Mixamo) onto a
    character as an NLA strip on track MOCAP, appended after earlier strips.  ``object`` =
    the armature or any object of the character; default = active / the only armature."""
    return call(
        "retarget", bvh=bvh, object=object, start=start, max_frames=max_frames, mute_game=mute_game
    )


@mcp.tool()
def blender_camera(
    target: str = "",
    distance: float | None = None,
    height: float | None = None,
    azimuth: float = -30.0,
    track: bool = True,
) -> dict:
    """Aim the scene camera at a character (default: the first armature); distance/height in
    scene units default to 2.6x / 0.55x the character's height; azimuth in degrees around Z
    from straight in front of the character (0 = front, 90 = its left, 180 = behind).  Adds a
    sun if the scene is unlit."""
    return call(
        "camera", target=target, distance=distance, height=height, azimuth=azimuth, track=track
    )


@mcp.tool()
def blender_render(
    path: str,
    frame: int | None = None,
    animation: bool = False,
    start: int | None = None,
    end: int | None = None,
    width: int | None = None,
    height: int | None = None,
    engine: str = "",
    samples: int | None = None,
) -> dict:
    """Render a PNG still (``frame``) or an H.264 MP4 (``animation=True``, ``start``..``end``)
    to ``path``.  Adds a camera if the scene has none.  Eevee unless ``engine`` says otherwise."""
    return call(
        "render",
        path=path,
        frame=frame,
        animation=animation,
        start=start,
        end=end,
        width=width,
        height=height,
        engine=engine or None,
        samples=samples,
    )


@mcp.tool()
def blender_frame(
    frame: int | None = None, start: int | None = None, end: int | None = None
) -> dict:
    """Set / read the current frame and the scene frame range."""
    return call("frame", frame=frame, start=start, end=end)


@mcp.tool()
def blender_scene() -> dict:
    """Everything in the scene: objects (type, parent, location, hidden), collections, camera,
    frame range, fps, render engine and resolution."""
    return call("scene")


@mcp.tool()
def blender_save(path: str = "") -> dict:
    """Save the .blend (``path`` = save-as)."""
    return call("save", path=path)


@mcp.tool()
def blender_open(path: str) -> dict:
    """Open a .blend file (the server survives the switch)."""
    return call("open_file", path=path)


@mcp.tool()
def blender_delete(objects: list[str] | None = None, family: bool = True) -> dict:
    """Delete objects by name (with the rest of their imported model unless family=False);
    no names = clear the whole scene."""
    return call("delete", objects=objects, family=family)


@mcp.tool()
def blender_python(code: str) -> dict:
    """Run Python inside Blender (bpy + the add-on's functions are in scope).  Returns the
    captured stdout and repr() of a variable named `result` if you set one."""
    return call("python", code=code)


@mcp.tool()
def blender_shutdown() -> dict:
    """Stop the control server; a headless Blender started with background=True exits."""
    return call("shutdown")


if __name__ == "__main__":
    mcp.run()
