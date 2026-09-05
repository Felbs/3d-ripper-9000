"""MCP server for the ComfyUI side of the mocap pipeline (footage -> BVH per person).

Talks to a running ComfyUI (http://127.0.0.1:8188 by default) over its HTTP API, using the
node graph from comfyui/make_workflow.py: Load Video -> GCRip Person Masks (our node in
comfyui/gcrip_mocap) -> GVHMR Inference x N -> SMPL to BVH x N.  Nothing here needs the
browser UI; `comfy_launch` can start ComfyUI itself.  `mocap_take` goes all the way: video
in, characters dancing in a saved .blend out, via the gcrip-blender control channel.

    COMFY_URL=http://127.0.0.1:8188 COMFY_ROOT=Z:/ComfyUI_windows_portable \
        python tools/comfy_mcp.py
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
ROOT = Path(os.environ.get("COMFY_ROOT", r"Z:\ComfyUI_windows_portable"))
COMFY = ROOT / "ComfyUI"
BVH_LIB = Path(os.environ.get("GCRIP_BVH_LIB", r"Z:\Motion capture rips\phase0\bvh_library"))

mcp = FastMCP("gcrip-comfy")


def _wf():
    spec = importlib.util.spec_from_file_location(
        "gcrip_make_workflow", HERE.parent / "comfyui" / "make_workflow.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get(path: str, timeout: float = 10) -> Any:
    with urllib.request.urlopen(URL + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, body: dict, timeout: float = 30) -> Any:
    req = urllib.request.Request(
        URL + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"ComfyUI {e.code}: {e.read().decode('utf-8', 'replace')[:2000]}"
        ) from None


def submit(prompt: dict) -> str:
    res = _post("/prompt", {"prompt": prompt, "client_id": "gcrip-comfy"})
    if res.get("node_errors"):
        raise RuntimeError("ComfyUI rejected the graph: " + json.dumps(res["node_errors"])[:2000])
    return res["prompt_id"]


def wait(prompt_id: str, timeout: float = 1800, poll: float = 3.0) -> dict:
    """Block until the prompt finished; returns its history entry (raises on error)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = _get(f"/history/{prompt_id}")
        entry = hist.get(prompt_id)
        if entry:
            st = entry.get("status", {})
            if st.get("status_str") == "error":
                msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                detail = msgs[-1][1] if msgs else st
                raise RuntimeError(
                    f"node {detail.get('node_type')} #{detail.get('node_id')}: "
                    f"{detail.get('exception_message')}\n"
                    f"{''.join(detail.get('traceback', []))[-1500:]}"
                    if isinstance(detail, dict)
                    else str(detail)
                )
            if st.get("completed") or entry.get("outputs"):
                return entry
        time.sleep(poll)
    raise TimeoutError(f"prompt {prompt_id} still running after {timeout:.0f}s (see comfy_queue)")


def _output_dir() -> Path:
    return COMFY / "output"


@mcp.tool()
def comfy_status() -> dict:
    """Is ComfyUI up?  Version, GPU, queue length, and whether the GCRip Person Masks node
    and the MotionCapture nodes are loaded."""
    try:
        stats = _get("/system_stats")
    except (OSError, ValueError) as e:
        return {"running": False, "url": URL, "error": str(e), "hint": "call comfy_launch"}
    out = {"running": True, "url": URL, "comfyui": stats.get("system", {}).get("comfyui_version")}
    devs = stats.get("devices") or []
    if devs:
        d = devs[0]
        out["gpu"] = d.get("name")
        out["vram_free_gb"] = round((d.get("vram_free") or 0) / 1e9, 1)
    try:
        q = _get("/queue")
        out["queue_running"] = len(q.get("queue_running", []))
        out["queue_pending"] = len(q.get("queue_pending", []))
    except (OSError, ValueError):
        pass
    for node in ("GCRipPersonMasks", "GVHMRInference", "SMPLtoBVH"):
        try:
            out[node] = bool(_get(f"/object_info/{node}"))
        except (OSError, ValueError):
            out[node] = False
    return out


@mcp.tool()
def comfy_launch(wait_s: int = 240) -> dict:
    """Start ComfyUI (the portable build's own Python, GPU) in the background and wait for it
    to answer.  Log: out/comfy_server.log in the gcrip repo."""
    st = comfy_status()
    if st.get("running"):
        return {"already_running": True, **st}
    py = ROOT / "python_embeded" / "python.exe"
    if not py.exists():
        return {"launched": False, "error": f"{py} not found - set COMFY_ROOT"}
    log = HERE.parent / "out" / "comfy_server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    port = URL.rsplit(":", 1)[-1]
    cmd = [
        str(py),
        "-s",
        str(COMFY / "main.py"),
        "--windows-standalone-build",
        "--listen",
        "127.0.0.1",
        "--port",
        port,
    ]
    flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
        if sys.platform == "win32"
        else 0
    )
    with log.open("ab") as fh:
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, creationflags=flags
        )
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(3)
        st = comfy_status()
        if st.get("running"):
            return {"launched": True, "pid": proc.pid, "log": str(log), **st}
        if proc.poll() is not None:
            break
    return {"launched": False, "pid": proc.pid, "exit": proc.poll(), "log": str(log)}


@mcp.tool()
def comfy_upload(path: str, name: str = "") -> dict:
    """Copy a video into ComfyUI's input folder (what Load Video lists).  Returns the input
    name to pass to comfy_mocap."""
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(path)
    dest = COMFY / "input" / (name or src.name)
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    return {"input_name": dest.name, "path": str(dest), "bytes": dest.stat().st_size}


@mcp.tool()
def comfy_mocap(
    video: str,
    people: int = 2,
    name: str = "take",
    moving_camera: bool = False,
    order: str = "left_to_right",
    confidence: float = 0.4,
    track_throw: bool = True,
    throw_colour: str = "bright",
    wait_s: int = 1800,
) -> dict:
    """Footage -> one BVH per person.  ``video`` = a file name in ComfyUI/input (see
    comfy_upload) or an absolute path (uploaded for you).  Runs Load Video -> GCRip Person
    Masks (tracks each person, person 1 = leftmost at the start unless order=largest_first)
    -> GVHMR Inference per person -> SMPL to BVH per person, and waits.  With
    ``track_throw`` the GCRip Throw Tracker also looks for an object leaving someone's hand
    (``throw_colour``: bright for cans/cups/balls, dark, any) and the result carries
    ``throw`` = {release_frame, person, flight_frames, ...} for mocap_take's ``props``.
    Returns the BVH paths (ComfyUI/output/<name>_p<k>.bvh), the mask videos, the tracking
    report and timing.  Tip: static phone, whole bodies in frame, people apart at the start."""
    if os.path.isabs(video) or os.sep in video:
        video = comfy_upload(video)["input_name"]
    wf = _wf()
    doc = wf.build(video, people, name, throw=track_throw)
    prompt = wf.to_api(doc)
    for node in prompt.values():
        if node["class_type"] == "GVHMRInference":
            node["inputs"]["moving_camera"] = bool(moving_camera)
        if node["class_type"] == "GCRipPersonMasks":
            node["inputs"]["order"] = order
            node["inputs"]["confidence"] = float(confidence)
        if node["class_type"] == "GCRipThrowTracker":
            node["inputs"]["colour"] = throw_colour
    t0 = time.time()
    pid = submit(prompt)
    entry = wait(pid, timeout=wait_s)
    out_dir = _output_dir()
    bvhs = [str(out_dir / f"{name}_p{k}.bvh") for k in range(1, people + 1)]
    bvhs = [b for b in bvhs if os.path.isfile(b)]
    masks = sorted(glob.glob(str(out_dir / "gcrip_masks" / f"{name}_p*.mp4")))
    info = ""
    for node_out in entry.get("outputs", {}).values():
        for k, v in node_out.items():
            if k in ("info", "text") and v:
                info += (v[0] if isinstance(v, list) else str(v)) + "\n"
    out = {
        "prompt_id": pid,
        "bvh": bvhs,
        "masks": masks,
        "seconds": round(time.time() - t0),
        "info": info.strip()[:4000],
        "next": "Blender: GCRip Mocap panel > pick a BVH > Retarget; or mocap_take",
    }
    pj = out_dir / "gcrip_masks" / f"{name}_people.json"
    if pj.is_file():
        people_doc = json.loads(pj.read_text(encoding="utf-8"))
        out["people"] = people_doc.get("people", [])
        # where each person's capture is real: pass as mocap_take(start_frames=...)
        out["start_frames"] = [p["first"] for p in out["people"]]
        # where each person stands when first seen, in metres along the capture's X axis
        # (screen-right is -X in GVHMR's camera-aligned world; depth from their pixel
        # height, ~1.75 m tall): pass as mocap_take(positions_m=...)
        w_px = (people_doc.get("size") or [1920, 1080])[0]
        pos = []
        for p in out["people"]:
            hp = p.get("height_px") or 0
            px_per_m = hp / 1.75 if hp else w_px / 4.5
            pos.append(round(-(p.get("first_x", 0.5) - 0.5) * w_px / px_per_m, 2))
        out["positions_m"] = pos
    tj = out_dir / "gcrip_masks" / f"{name}_throws.json"
    if track_throw and tj.is_file():
        doc = json.loads(tj.read_text(encoding="utf-8"))
        ev = doc.get("events") or []
        out["throw"] = {k: v for k, v in ev[0].items() if k != "path"} if ev else None
        out["throws_json"] = str(tj)
        out["throw_preview"] = str(tj.with_name(f"{name}_throw.png"))
    return out


@mcp.tool()
def comfy_run(prompt_json: str, wait_s: int = 1800) -> dict:
    """Submit any API-format workflow (a path to a JSON file, or the JSON itself) and wait.
    Returns the history entry's outputs."""
    text = (
        Path(prompt_json).read_text(encoding="utf-8")
        if os.path.isfile(prompt_json)
        else prompt_json
    )
    pid = submit(json.loads(text))
    entry = wait(pid, timeout=wait_s)
    return {"prompt_id": pid, "outputs": entry.get("outputs", {})}


@mcp.tool()
def comfy_queue() -> dict:
    """What ComfyUI is running / has queued (prompt ids and node types)."""
    q = _get("/queue")

    def brief(items):
        return [
            {"prompt_id": it[1], "nodes": sorted({n["class_type"] for n in it[2].values()})}
            for it in items
        ]

    return {
        "running": brief(q.get("queue_running", [])),
        "pending": brief(q.get("queue_pending", [])),
    }


@mcp.tool()
def comfy_interrupt() -> dict:
    """Stop the running prompt."""
    _post("/interrupt", {})
    return {"interrupted": True}


@mcp.tool()
def comfy_history(prompt_id: str) -> dict:
    """Status, outputs and any error of one prompt."""
    h = _get(f"/history/{prompt_id}").get(prompt_id)
    if not h:
        return {"prompt_id": prompt_id, "known": False}
    return {"prompt_id": prompt_id, "status": h.get("status"), "outputs": h.get("outputs")}


@mcp.tool()
def comfy_outputs(pattern: str = "*.bvh") -> list[dict]:
    """Files in ComfyUI/output matching the glob (newest first) - BVHs, mask videos ..."""
    hits = glob.glob(str(_output_dir() / "**" / pattern), recursive=True)
    hits.sort(key=os.path.getmtime, reverse=True)
    return [
        {
            "path": p,
            "bytes": os.path.getsize(p),
            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
        }
        for p in hits[:200]
    ]


@mcp.tool()
def bvh_library() -> list[dict]:
    """Ready-made clips to test with (Bandai Namco dataset + earlier GVHMR takes)."""
    hits = sorted(glob.glob(str(BVH_LIB / "*.bvh")))
    return [{"path": p, "bytes": os.path.getsize(p)} for p in hits]


@mcp.tool()
def mocap_take(
    bvh: list[str],
    characters: list[str],
    out_blend: str,
    render_mp4: str = "",
    spacing: float = 220.0,
    max_frames: int = 0,
    background: bool = True,
    props: list[dict] | None = None,
    start_frames: list[int] | None = None,
    audio: str = "",
    positions_m: list[float] | None = None,
    heights: list[float] | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    """BVH files -> characters animated in a saved .blend (and optionally an MP4), through
    the gcrip-blender control channel.  ``characters`` = one "GAMEID:name" per BVH as
    listed by blender_library (e.g. "GZLE01:link/cl", "G6FE69:m200__"), or a glTF path.
    ``heights`` = scene units per character (100 = 1 m): each rig is scaled to that
    height (0 keeps its native size).  ``attachments`` hang separate rips on a bone, e.g.
    [{"person": 1, "gid": "GZ2E01", "name": "Kmdl/al_head", "bone": "mixamorig:Head"}].
    Characters stand ``spacing`` units apart along X; each gets its BVH on NLA track MOCAP;
    a camera looks at all of them.  ``start_frames`` (comfy_mocap's ``start_frames``) =
    the clip frame each person first appears: capture before that is skipped and the strip
    starts there, so scene frames stay equal to clip frames + 1.  ``props`` puts things in
    hands: each entry {"person": 1-based index into ``characters``, "gid": ..., "name": ...
    (or "gltf"), "hand": "auto"|"left"|"right", "release_frame": clip frame from
    comfy_mocap's ``throw`` (or null to keep holding), "flight_frames": 0, "size": 0.16}.
    ``audio`` = the source video (or any audio file): its sound goes in as a sequencer
    strip at frame 1, so the .blend plays it and the MP4 carries it.
    Launches a headless Blender if none is listening."""
    sys.path.insert(0, str(HERE))
    import blender_mcp as bm

    if len(bvh) != len(characters):
        raise ValueError("one character per BVH")
    for b in bvh:
        if not os.path.isfile(b):
            raise FileNotFoundError(b)
    st = bm.blender_status()
    launched = False
    if not st.get("running"):
        st = bm.blender_launch(background=background, wait=180)
        launched = True
        if not st.get("launched"):
            raise RuntimeError(f"Blender did not start: {st}")
    t0 = time.time()
    arms = []
    # GVHMR gives every person their own origin, and its world has screen-right = -X.
    # Place people where the footage shows them (positions_m, metres along that axis,
    # 100 units per metre); without that, line them up left-to-right = +X to -X.
    x0 = spacing * (len(bvh) - 1) / 2
    for k, (clip, ch) in enumerate(zip(bvh, characters, strict=True)):
        if positions_m and k < len(positions_m):
            at = [float(positions_m[k]) * 100.0, 0, 0]
        else:
            at = [x0 - k * spacing, 0, 0]
        if ch.lower().endswith((".gltf", ".glb")):
            sp = bm.call("spawn", gltf=ch, at=at)
        else:
            gid, _, name = ch.partition(":")
            sp = bm.call("spawn", gid=gid, name=name, at=at)
        if not sp.get("armature"):
            raise RuntimeError(f"{ch}: no armature")
        if not sp.get("mocap_ready", True):
            raise RuntimeError(f"{ch}: {sp.get('warning') or sp.get('missing_core')}")
        if heights and k < len(heights) and heights[k]:
            sp["height_scale"] = bm.call(
                "python",
                code=(
                    "import bpy, numpy as np\nfrom mathutils import Vector\n"
                    f"root=bpy.data.objects[{sp['root']!r}]\n"
                    "objs=[root]; st=list(root.children)\n"
                    "while st:\n    c=st.pop(); objs.append(c); st.extend(c.children)\n"
                    "zs=[(o.matrix_world @ Vector(c)).z for o in objs if o.type=='MESH'"
                    " and not o.hide_render for c in o.bound_box]\n"
                    f"f={float(heights[k])}/max(max(zs)-min(zs),1e-3)\n"
                    "root.scale=(f,f,f)\nbpy.context.view_layer.update()\nresult=round(f,4)"
                ),
            )["result"]
        skip = int(start_frames[k]) if start_frames and k < len(start_frames) else 0
        rt = bm.call(
            "retarget",
            bvh=clip,
            object=sp["armature"],
            max_frames=max_frames,
            skip=skip,
            start=skip + 1,
            # with real start positions, keep ground travel in scene metres for everyone
            # so the pair stay as far apart as in the footage (a giant will shuffle)
            motion_scale=100.0 if positions_m else 0.0,
        )
        arms.append(
            {
                "character": ch,
                "armature": sp["armature"],
                "frames": rt["frames"],
                "fps": rt["fps"],
                "start": rt["start"],
                "end": rt["end"],
            }
        )
    last = max(a["end"] for a in arms)
    bm.call("frame", start=1, end=last)
    held = []
    for p in props or []:
        k = int(p.get("person", 1)) - 1
        if not 0 <= k < len(arms):
            raise ValueError(f"prop person {k + 1} out of range")
        rel = p.get("release_frame")
        held.append(
            bm.call(
                "hold_prop",
                gid=p.get("gid", ""),
                name=p.get("name", ""),
                gltf=p.get("gltf", ""),
                object=arms[k]["armature"],
                hand=p.get("hand", "auto"),
                release_frame=(int(rel) + 1) if rel is not None else None,  # clip -> scene frame
                flight_frames=int(p.get("flight_frames", 0) or 0),
                size=float(p.get("size", 0.16)),
                toss=float(p.get("toss", 1.4)),
                grasp=bool(p.get("grasp", True)),
            )
        )
    cam = bm.call("camera", target=arms[0]["armature"], azimuth=-10)
    h = cam["target_height"]  # back off enough that raised arms and hats stay in frame
    bm.call("camera", target=arms[0]["armature"], azimuth=-10, distance=3.6 * h, height=0.5 * h)
    parts = []
    for a in attachments or []:
        k = int(a.get("person", 1)) - 1
        if not 0 <= k < len(arms):
            raise ValueError(f"attachment person {k + 1} out of range")
        parts.append(
            bm.call(
                "attach_model",
                gid=a.get("gid", ""),
                name=a.get("name", ""),
                gltf=a.get("gltf", ""),
                object=arms[k]["armature"],
                bone=a.get("bone", "mixamorig:Head"),
                orient=a.get("orient", "auto"),
            )
        )
    # frame everything the characters do over the whole take (they may walk metres apart)
    # from the +Y side, where the phone was (GVHMR's world: screen-right = -X)
    names = [a["armature"] for a in arms]
    bm.call(
        "python",
        code=(
            "import bpy, math, numpy as np\nfrom mathutils import Vector\n"
            "sc=bpy.context.scene\n"
            f"names={names!r}\n"
            "def fam(o):\n    out=[o]; st=list(o.children)\n"
            "    while st:\n        c=st.pop(); out.append(c); st.extend(c.children)\n"
            "    return out\n"
            "lo=np.array([1e30]*3); hi=-lo\n"
            "objs=[o for n in names for o in fam(bpy.data.objects[n])\n"
            "      if o.type=='MESH' and not o.hide_render]\n"
            "step=max(1,(sc.frame_end-sc.frame_start)//40)\n"
            "for f in range(sc.frame_start, sc.frame_end+1, step):\n"
            "    sc.frame_set(f)\n"
            "    for o in objs:\n        for c in o.bound_box:\n"
            "            w=np.array(o.matrix_world @ Vector(c))\n"
            "            lo=np.minimum(lo,w); hi=np.maximum(hi,w)\n"
            "cam=bpy.data.objects['GCRipCam']\n"
            "lens=cam.data.lens; hf=math.atan(18.0/lens); vf=math.atan(18.0*9/16/lens)\n"
            "w=hi[0]-lo[0]; h=hi[2]-lo[2]; dep=hi[1]-lo[1]\n"
            "d=max(w/(2*math.tan(hf)), h/(2*math.tan(vf)))*1.25 + dep/2\n"
            "mid=bpy.data.objects.get('LookAt') or bpy.data.objects.new('LookAt', None)\n"
            "if mid.name not in sc.collection.objects: sc.collection.objects.link(mid)\n"
            "mid.location=((lo[0]+hi[0])/2, (lo[1]+hi[1])/2, (lo[2]+hi[2])/2)\n"
            "for c in cam.constraints: c.target=mid; c.subtarget=''\n"
            "cam.location=((lo[0]+hi[0])/2, hi[1]+d, lo[2]+0.6*h)\n"
            "sc.frame_set(sc.frame_start)\n"
            "result=dict(extent=[lo.round(0).tolist(), hi.round(0).tolist()],\n"
            "            distance=round(float(d)))\n"
        ),
    )
    bm.call(
        "python",
        code=(
            "import bpy\nsc=bpy.context.scene\n"
            "sc.world = sc.world or bpy.data.worlds.new('World')\nsc.world.color=(0.30,0.33,0.38)\n"
            "cam=bpy.data.objects['GCRipCam']\nsun=bpy.data.objects.get('GCRipSun')\n"
            "if sun:\n    sun.parent=cam; sun.matrix_parent_inverse.identity()\n"
            "    sun.location=(0,0,0); sun.rotation_euler=(0.35,0.25,0); sun.data.energy=3\n"
        ),
    )
    bm.call(
        "python",
        code=(
            "import bpy\n"
            "for ob in bpy.context.scene.objects:\n    ad=ob.animation_data\n"
            "    if ad and ob.type=='ARMATURE':\n        for tr in list(ad.nla_tracks):\n"
            "            if tr.name!='MOCAP': ad.nla_tracks.remove(tr)\n"
            "n=len(bpy.data.actions)\nbpy.data.orphans_purge(do_recursive=True)\n"
            "result=n-len(bpy.data.actions)"
        ),
    )
    out = {"characters": arms, "frames": last, "props": held, "attachments": parts}
    if audio:
        if not os.path.isfile(audio):
            raise FileNotFoundError(audio)
        out["audio"] = bm.call(
            "python",
            code=(
                "import bpy\nsc=bpy.context.scene\n"
                "if not sc.sequence_editor: sc.sequence_editor_create()\n"
                "se=sc.sequence_editor\n"
                "seqs=se.sequences if hasattr(se,'sequences') else se.strips\n"
                "for s in list(seqs):\n    if s.type=='SOUND': seqs.remove(s)\n"
                f"snd=seqs.new_sound('original audio', {audio!r}, 1, 1)\n"
                "sc.render.ffmpeg.audio_codec='AAC'\nsc.render.ffmpeg.audio_bitrate=160\n"
                "result=dict(strip=snd.name, frames=snd.frame_final_duration)\n"
            ),
        )["result"]
    if render_mp4:
        out["mp4"] = bm.call(
            "render", path=render_mp4, animation=True, start=1, end=last, width=960, height=540
        )
    out["blend"] = bm.call("save", path=out_blend)["file"]
    out["seconds"] = round(time.time() - t0)
    if launched and background:
        bm.call("shutdown")
    return out


if __name__ == "__main__":
    mcp.run()
