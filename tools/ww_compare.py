"""Compare the Wind Waker remake against the disc it came from, and against the real thing.

Three questions, three answers, one HTML report:

  coverage   The disc says a surface is walkable here. Do we draw anything there?  Every
             "invisible platform" the play-tester has fallen through is a place where the
             DZB has collision and the exported glTF has no geometry above it.  This runs
             entirely offline off the ISO and the export - no game, no screenshots.

  materials  What the ripper is known to drop between the disc's TEV setup and glTF:
             texture layers never exported, materials that end up plain white, materials
             where the toon ramp was mistaken for the base colour.  Read from the mined
             ww_rendering.json audit and re-counted against the shipped stage.

  shots      Reproducible screenshots of our build, driven over the debug control channel
             (fixed camera, fixed hour, so two runs are comparable), each paired with a
             reference frame from the original if one has been dropped in.

Usage:
    python tools/ww_compare.py coverage --stage sea --room 44
    python tools/ww_compare.py shots            # needs the game running with --control
    python tools/ww_compare.py report           # build docs/compare.html from what exists

Reference frames go in `docs/compare_reference/<shot>.png` - a Dolphin screenshot, a video
frame, anything of the same view. The report shows ours and theirs side by side with mean
colour per band; it never claims a match it did not measure.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gcrip.formats import dzb as dzb_mod  # noqa: E402
from gcrip.stage import _Disc  # noqa: E402

OUT = ROOT / "out" / "compare"
DOCS = ROOT / "docs"
REFDIR = DOCS / "compare_reference"
DEFAULT_ISO = ROOT / "roms" / "Legend of Zelda, The - The Wind Waker (USA).iso"
DEFAULT_BUILD = ROOT / "out" / "rip" / "GZLE01" / "godot"


# ---------------------------------------------------------------- glTF geometry


def _glb_json(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    n = struct.unpack_from("<I", raw, 12)[0]
    return json.loads(raw[20 : 20 + n]), raw


def _node_world(gltf: dict) -> dict[int, tuple[float, float, float]]:
    """Node index -> accumulated translation (these exports use translation only)."""
    parent: dict[int, int] = {}
    for i, n in enumerate(gltf.get("nodes", [])):
        for c in n.get("children", []):
            parent[c] = i
    out: dict[int, tuple[float, float, float]] = {}
    for i, _n in enumerate(gltf.get("nodes", [])):
        x = y = z = 0.0
        j: int | None = i
        while j is not None:
            t = gltf["nodes"][j].get("translation") or (0.0, 0.0, 0.0)
            x, y, z = x + t[0], y + t[1], z + t[2]
            j = parent.get(j)
        out[i] = (x, y, z)
    return out


_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
         5125: np.uint32, 5126: np.float32}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _accessor(gltf: dict, blob: bytes, bin_off: int, idx: int) -> np.ndarray:
    acc = gltf["accessors"][idx]
    bv = gltf["bufferViews"][acc["bufferView"]]
    n = _NCOMP[acc["type"]]
    dt = _COMP[acc["componentType"]]
    start = bin_off + bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or (np.dtype(dt).itemsize * n)
    if stride == np.dtype(dt).itemsize * n:
        arr = np.frombuffer(blob, dt, acc["count"] * n, start).reshape(-1, n)
    else:  # interleaved
        raw = np.frombuffer(blob, np.uint8, acc["count"] * stride, start).reshape(-1, stride)
        arr = raw[:, : np.dtype(dt).itemsize * n].copy().view(dt).reshape(-1, n)
    return arr


def _bin_offset(raw: bytes) -> int:
    """Byte offset of the GLB's BIN chunk payload."""
    n = struct.unpack_from("<I", raw, 12)[0]
    pos = 12 + 8 + n
    while pos < len(raw):
        ln, kind = struct.unpack_from("<II", raw, pos)
        if kind == 0x004E4942:      # the BIN fourcc
            return pos + 8
        pos += 8 + ln
    raise ValueError("no BIN chunk")


def visual_triangles(glb: Path, skip_water: bool = True) -> tuple[np.ndarray, list[str]]:
    """Every drawn triangle in world space, as (T, 3, 3).

    Skips the stage's own baked sea sheets by default, because the running game hides them
    (_hide_baked_sea) - counting them as "something is drawn here" would mask exactly the
    holes this audit exists to find. Their AABBs span the whole island, so an AABB test
    alone always reports full coverage; that is why this reads real triangles.
    """
    gltf, raw = _glb_json(glb)
    blob = raw
    bin_off = _bin_offset(raw)
    world = _node_world(gltf)
    mats = gltf.get("materials", [])
    chunks, names = [], []
    for i, node in enumerate(gltf.get("nodes", [])):
        mi = node.get("mesh")
        if mi is None:
            continue
        off = np.array(world[i], np.float32)
        for prim in gltf["meshes"][mi]["primitives"]:
            mname = mats[prim["material"]].get("name", "") if "material" in prim else ""
            low = mname.lower()
            if skip_water and ("mizu" in low or "nami" in low):
                continue
            pos = _accessor(gltf, blob, bin_off, prim["attributes"]["POSITION"]).astype(np.float32)
            pos = pos + off
            if "indices" in prim:
                ind = _accessor(gltf, blob, bin_off, prim["indices"]).reshape(-1).astype(np.int64)
            else:
                ind = np.arange(len(pos), dtype=np.int64)
            ind = ind[: (len(ind) // 3) * 3]
            tri = pos[ind].reshape(-1, 3, 3)
            if len(tri):
                chunks.append(tri)
                names.extend([mname] * len(tri))
    if not chunks:
        return np.zeros((0, 3, 3), np.float32), []
    return np.concatenate(chunks, 0), names


def visual_boxes(glb: Path) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """Every drawn primitive as a world-space AABB, with the material that shades it."""
    gltf, _ = _glb_json(glb)
    world = _node_world(gltf)
    mats = gltf.get("materials", [])
    boxes = []
    for i, node in enumerate(gltf.get("nodes", [])):
        mi = node.get("mesh")
        if mi is None:
            continue
        ox, oy, oz = world[i]
        for prim in gltf["meshes"][mi]["primitives"]:
            acc = gltf["accessors"][prim["attributes"]["POSITION"]]
            lo = np.array(acc["min"], float) + (ox, oy, oz)
            hi = np.array(acc["max"], float) + (ox, oy, oz)
            name = mats[prim["material"]].get("name", "") if "material" in prim else ""
            boxes.append((lo, hi, name))
    return boxes


# ---------------------------------------------------------------- coverage audit


def coverage(iso: Path, build: Path, stage: str, room: int | None, scene: str,
             min_y: float = -300.0, max_area: float = 4.0e6) -> dict:
    """Walkable collision with nothing drawn above it — the invisible-platform detector.

    A triangle counts as walkable when its normal points up (the game's own floor test is
    the same idea). For each such triangle we ask whether ANY drawn primitive's AABB
    covers its centre in x/z within a generous vertical band. No box, nothing to see.
    """
    disc = _Disc(iso)
    arc = "Stage.arc" if room is None else f"Room{room}.arc"
    inner = "stage.dzb" if room is None else "room.dzb"
    raw = disc.read_inner(f"res/Stage/{stage}/{arc}", inner)
    if raw is None:
        raise SystemExit(f"no {inner} in res/Stage/{stage}/{arc}")
    col = dzb_mod.parse(raw)

    glb = build / "stages" / f"{scene}.glb"
    if not glb.exists():
        raise SystemExit(f"no exported scene at {glb}")
    tri_v, tri_names = visual_triangles(glb)
    if not len(tri_v):
        raise SystemExit(f"{glb} has no drawable triangles")
    # a coarse x/z bucket grid so each collision point only tests nearby triangles
    tlo = tri_v.min(axis=1)
    thi = tri_v.max(axis=1)
    cell = 800.0
    grid: dict[tuple[int, int], list[int]] = {}
    for t in range(len(tri_v)):
        for gx in range(int(tlo[t, 0] // cell), int(thi[t, 0] // cell) + 1):
            for gz in range(int(tlo[t, 2] // cell), int(thi[t, 2] // cell) + 1):
                grid.setdefault((gx, gz), []).append(t)

    # the export recentres the scene; recover the offset from the stage report
    rep = json.loads((ROOT / "out" / "rip" / "GZLE01" / "stages" / scene /
                      f"{_report_stem(scene)}_report.json").read_text(encoding="utf-8"))
    off = rep.get("offset") or [0.0, 0.0, 0.0]

    v = col.vertices
    tris = col.triangles
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    normals = np.cross(b - a, c - a)
    ln = np.linalg.norm(normals, axis=1)
    ok = ln > 1e-6
    up = np.zeros(len(tris), bool)
    up[ok] = (normals[ok, 1] / ln[ok]) > 0.5          # floor-ish, not wall
    centres = (a + b + c) / 3.0
    area = ln * 0.5

    # collision is in disc coordinates; the export subtracted `offset`
    cx = centres[:, 0] - off[0]
    cy = centres[:, 1]
    cz = centres[:, 2] - off[2]

    # Two kinds of collision are legitimately invisible and would otherwise drown the
    # statistic: the sea bed / kill plane far below the waterline, and the enormous
    # backdrop quads (single triangles of billions of square units). Neither is a floor a
    # player can stand on and expect to see.
    misses = []
    reachable = up & (area > 500.0) & (area < max_area) & (centres[:, 1] > min_y)
    idx = np.nonzero(reachable)[0]
    for t in idx:
        x, y, z = float(cx[t]), float(cy[t]), float(cz[t])
        cand = grid.get((int(x // cell), int(z // cell)))
        if cand and _covered(tri_v, cand, x, y, z):
            continue
        misses.append((x, y, z, float(area[t])))

    return {
        "stage": stage,
        "room": room,
        "scene": scene,
        "offset": off,
        "drawn_triangles": int(len(tri_v)),
        "walkable_triangles": int(idx.size),
        "filters": {"min_y": min_y, "max_triangle_area": max_area},
        "uncovered": len(misses),
        "uncovered_area": round(sum(m[3] for m in misses), 1),
        "total_area": round(float(area[idx].sum()), 1),
        "clusters": _cluster(misses),
    }


def _covered(tri: np.ndarray, cand: list[int], x: float, y: float, z: float) -> bool:
    """Is (x, z) inside any candidate triangle, at a height that could be its surface?

    Barycentric in the x/z plane, then the triangle's own y at that point has to sit in a
    band around the collision height - so a roof 3000 units up does not count as covering
    the floor below it.
    """
    t = tri[cand]
    ax, az = t[:, 0, 0], t[:, 0, 2]
    bx, bz = t[:, 1, 0], t[:, 1, 2]
    cxx, czz = t[:, 2, 0], t[:, 2, 2]
    d = (bz - czz) * (ax - cxx) + (cxx - bx) * (az - czz)
    ok = np.abs(d) > 1e-9
    if not ok.any():
        return False
    u = np.zeros_like(d)
    v = np.zeros_like(d)
    u[ok] = ((bz[ok] - czz[ok]) * (x - cxx[ok]) + (cxx[ok] - bx[ok]) * (z - czz[ok])) / d[ok]
    v[ok] = ((czz[ok] - az[ok]) * (x - cxx[ok]) + (ax[ok] - cxx[ok]) * (z - czz[ok])) / d[ok]
    w = 1.0 - u - v
    inside = ok & (u >= -0.02) & (v >= -0.02) & (w >= -0.02)
    if not inside.any():
        return False
    ty = u * t[:, 0, 1] + v * t[:, 1, 1] + w * t[:, 2, 1]
    return bool((inside & (ty > y - 120.0) & (ty < y + 400.0)).any())


def _report_stem(scene: str) -> str:
    """sea_r44's report is written as sea_report.json; most stages match their folder."""
    d = ROOT / "out" / "rip" / "GZLE01" / "stages" / scene
    hits = sorted(d.glob("*_report.json"))
    return hits[0].stem[: -len("_report")] if hits else scene


def _cluster(misses: list[tuple[float, float, float, float]], radius: float = 900.0) -> list[dict]:
    """Group uncovered triangles so one missing model reads as one finding, not 400."""
    out: list[dict] = []
    for x, y, z, ar in sorted(misses, key=lambda m: -m[3]):
        for cl in out:
            if math.dist((x, z), (cl["at"][0], cl["at"][2])) < radius and abs(y - cl["at"][1]) < 400:
                cl["triangles"] += 1
                cl["area"] = round(cl["area"] + ar, 1)
                break
        else:
            out.append({"at": [round(x), round(y), round(z)], "triangles": 1, "area": round(ar, 1)})
    out.sort(key=lambda c: -c["area"])
    return out[:40]


# ---------------------------------------------------------------- waterline audit

# daSea_packet_c's four wave rows, the same table the game and the shader share.
SEA_WAVES = [
    (2.5, 13600.0, 0.0, 0.98, 0.20, 200.0),
    (2.5, 11200.0, 4000.0, 0.20, 0.98, 190.0),
    (2.5, 8800.0, 8000.0, -0.98, 0.20, 210.0),
    (2.5, 6400.0, 12000.0, 0.20, -0.98, 180.0),
]
SEA_BASE = 1.0


def sea_peak(wave_max: float) -> float:
    """Highest the sea can reach at a given wave_max: every cosine crests at once."""
    return SEA_BASE + sum(w[0] for w in SEA_WAVES) * wave_max


def waterline(scene: str) -> dict:
    """Anything the player stands on that the sea can climb over.

    Catches two reports at once: "the water is up to Link's feet when it opens" and "the
    dock is under the water". Both are the same arithmetic - a spawn at y = 173 against a
    sea whose peak is 1 + 10 * wave_max. At the open-sea 30 that peak is 301, so the dock
    is 128 units under water; at Outset's real wave_max of 0 it is 1, and the dock is dry.
    """
    rep = json.loads((ROOT / "out" / "rip" / "GZLE01" / "stages" / scene /
                      f"{_report_stem(scene)}_report.json").read_text(encoding="utf-8"))
    wm = {int(k): float(v) for k, v in (rep.get("wave_max") or {}).items()}
    rows = []
    for sp in rep.get("spawns", []):
        room = sp.get("room")
        w = wm.get(int(room) if room is not None else -1, -1.0)
        if w < 0:
            w = 30.0                       # no MULT entry: the game uses the open-sea swell
        peak = sea_peak(w)
        y = float(sp["pos"][1])
        rows.append({
            "spawn": sp.get("id"),
            "room": room,
            "pos": [round(float(v), 1) for v in sp["pos"]],
            "wave_max": w,
            "sea_peak": round(peak, 1),
            "clearance": round(y - peak, 1),
            "submerged": y < peak,
            # what this spawn looks like if the sea is left at the open-sea swell instead of
            # the room's own - the failure mode that put the dock under water on load
            "clearance_if_open_sea": round(y - sea_peak(30.0), 1),
        })
    bad = [r for r in rows if r["submerged"]]
    dry = [r for r in rows if not r["submerged"]]
    regress = [r for r in dry if r["clearance_if_open_sea"] < 0]
    return {
        "scene": scene,
        "spawns": rows,
        "submerged": len(bad),
        "worst": min((r["clearance"] for r in rows), default=None),
        "open_sea_peak": round(sea_peak(30.0), 1),
        "dry_spawns": len(dry),
        "would_flood_at_open_sea": [r["spawn"] for r in regress],
        "note": ("A spawn is only ever dry if the sea uses ITS room's wave_max from the "
                 "first frame. Easing down from the open-sea value floods it until the "
                 "ease finishes."),
    }


# ---------------------------------------------------------------- motion audits


def stability(port: int, shot_name: str, frames: int, gap: float) -> dict:
    """Hold the camera still and look for pixels that refuse to.

    A single screenshot cannot see something blinking - geometry that renders one moment
    and not the next averages out to "a screenshot". This holds a fixed camera, takes N
    frames a short time apart and diffs consecutive pairs. Wave motion and foam animate, so
    a small always-on churn is expected; whole buildings popping shows up as a spike.
    """
    shots = {s["name"]: s for s in json.loads(SHOTS.read_text(encoding="utf-8"))}
    shot = shots[shot_name]
    ctl = Control(port)
    OUT.mkdir(parents=True, exist_ok=True)
    imgs = []
    try:
        ctl(cmd="clock", hour=shot.get("hour", 12))
        eye, look = shot["eye"], shot["look"]
        ctl(cmd="eye", x=eye[0], y=eye[1], z=eye[2], lx=look[0], ly=look[1], lz=look[2])
        _settle(ctl, shot.get("settle", 120))
        import time

        for i in range(frames):
            r = ctl(cmd="screenshot", path=f"user://stab_{i}.png")
            if r.get("ok"):
                dest = OUT / f"stab_{shot_name}_{i}.png"
                dest.write_bytes(Path(r["path"]).read_bytes())
                imgs.append(dest)
            time.sleep(gap)
        ctl(cmd="eye", off=True)
    finally:
        ctl.close()
    return _diff_series(imgs, shot_name, "stability")


def settle(port: int, shot_name: str, marks: list[float]) -> dict:
    """Reload the stage and watch the frame stop changing - or fail to.

    "The water is too high when it opens" is invisible to a settled screenshot. This
    reloads, then samples the same view at increasing delays; if the last frames differ
    from the first, something is still moving into place after the player can see it.
    """
    shots = {s["name"]: s for s in json.loads(SHOTS.read_text(encoding="utf-8"))}
    shot = shots[shot_name]
    ctl = Control(port)
    imgs = []
    import time

    try:
        st = ctl(cmd="state").get("state", {})
        # reload the SCENE, not the stage key: sea_r44 is its own single-room export, and
        # warping to "sea" would load the whole 49-room Great Sea instead
        ctl(cmd="warp", stage=st.get("scene") or st.get("stage", "sea"), room=0, spawn=0)
        time.sleep(3.0)
        # pin the hour, or this measures the sky changing colour rather than the world
        # settling - the clock runs at 600 s/day, so 26 s of sampling spans a whole hour
        ctl(cmd="clock", hour=shot.get("hour", 12))
        eye, look = shot["eye"], shot["look"]
        prev = 0.0
        for t in marks:
            time.sleep(max(t - prev, 0.0))
            prev = t
            ctl(cmd="clock", hour=shot.get("hour", 12))
            ctl(cmd="eye", x=eye[0], y=eye[1], z=eye[2], lx=look[0], ly=look[1], lz=look[2])
            r = ctl(cmd="screenshot", path=f"user://settle_{t}.png")
            if r.get("ok"):
                dest = OUT / f"settle_{shot_name}_{t:g}s.png"
                dest.write_bytes(Path(r["path"]).read_bytes())
                imgs.append(dest)
        ctl(cmd="eye", off=True)
    finally:
        ctl.close()
    out = _diff_series(imgs, shot_name, "settle")
    out["marks_s"] = marks
    return out


def _diff_series(imgs: list[Path], shot_name: str, kind: str) -> dict:
    """Mean absolute difference between consecutive frames, and each frame vs the last."""
    decoded = [(p, _read_png(p)) for p in imgs]
    decoded = [(p, a) for p, a in decoded if a is not None]
    steps = []
    for (pa, a), (pb, b) in zip(decoded, decoded[1:]):
        if a.shape != b.shape:
            continue
        d = np.abs(a.astype(np.int16) - b.astype(np.int16)).mean(axis=2)
        steps.append({
            "from": pa.name,
            "to": pb.name,
            "mean_delta": round(float(d.mean()), 3),
            "changed_pixels_pct": round(float((d > 12).mean()) * 100.0, 2),
            "max_delta": int(d.max()),
        })
    vs_last = []
    if decoded:
        last = decoded[-1][1]
        for pth, a in decoded:
            if a.shape != last.shape:
                continue
            d = np.abs(a.astype(np.int16) - last.astype(np.int16)).mean(axis=2)
            vs_last.append({"frame": pth.name,
                            "mean_delta": round(float(d.mean()), 3),
                            "changed_pixels_pct": round(float((d > 12).mean()) * 100.0, 2)})
    res = {"kind": kind, "shot": shot_name, "frames": len(decoded),
           "steps": steps, "vs_last": vs_last,
           "worst_step_pct": round(max((s["changed_pixels_pct"] for s in steps), default=0.0), 2)}
    (OUT / f"{kind}_{shot_name}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


# ---------------------------------------------------------------- material fidelity


def materials(build: Path, scene: str) -> dict:
    """What the disc's shading has, that our glTF does not."""
    audit_path = ROOT / "gcrip" / "data" / "ww_rendering.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {}
    loss = (audit.get("_current", {}) or {}).get("measured_loss", {})

    gltf, _ = _glb_json(build / "stages" / f"{scene}.glb")
    mats = gltf.get("materials", [])
    untextured = [
        m.get("name", "?")
        for m in mats
        if "baseColorTexture" not in (m.get("pbrMetallicRoughness") or {})
    ]
    # how many drawn primitives each material shades, so the list is ranked by what is seen
    use: dict[int, int] = {}
    for mesh in gltf.get("meshes", []):
        for prim in mesh["primitives"]:
            if "material" in prim:
                use[prim["material"]] = use.get(prim["material"], 0) + 1
    ranked = sorted(
        ((mats[i].get("name", "?"), n) for i, n in use.items()),
        key=lambda p: -p[1],
    )
    return {
        "scene": scene,
        "materials": len(mats),
        "double_sided": sum(1 for m in mats if m.get("doubleSided")),
        "untextured": untextured,
        "most_used": ranked[:15],
        "disc_audit": {
            "texture_layers_dropped": loss.get("texture_layers_dropped_by_the_exporter"),
            "materials_with_no_texture": loss.get("materials_that_get_no_texture_at_all"),
            "toon_ramp_mistaken_for_base": loss.get(
                "materials_where_diffuse_picked_the_toon_ramp_as_base_colour"
            ),
            "sample": loss.get("sample"),
        },
    }


# ---------------------------------------------------------------- shots


class Control:
    """The running game's debug channel: one JSON object per line."""

    def __init__(self, port: int = 8787, timeout: float = 20.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.f = self.sock.makefile("rw", encoding="utf-8", newline="\n")

    def __call__(self, **msg):
        self.f.write(json.dumps(msg) + "\n")
        self.f.flush()
        return json.loads(self.f.readline())

    def close(self):
        self.sock.close()


SHOTS = ROOT / "tools" / "ww_compare_shots.json"


def take_shots(port: int, only: str | None) -> dict:
    shots = json.loads(SHOTS.read_text(encoding="utf-8"))
    ctl = Control(port)
    OUT.mkdir(parents=True, exist_ok=True)
    taken = []
    try:
        for shot in shots:
            if only and shot["name"] != only:
                continue
            if shot.get("stage"):
                ctl(cmd="warp", stage=shot["stage"], room=shot.get("room", 0),
                    spawn=shot.get("spawn", 0))
                _settle(ctl, 90)
            ctl(cmd="clock", hour=shot.get("hour", 12))
            eye, look = shot["eye"], shot["look"]
            ctl(cmd="eye", x=eye[0], y=eye[1], z=eye[2], lx=look[0], ly=look[1], lz=look[2])
            _settle(ctl, shot.get("settle", 120))
            dest = OUT / f"{shot['name']}.png"
            r = ctl(cmd="screenshot", path=f"user://cmp_{shot['name']}.png")
            if r.get("ok"):
                src = Path(r["path"])
                dest.write_bytes(src.read_bytes())
                taken.append({**shot, "file": dest.name})
                print(f"  {shot['name']:24} {dest}")
            else:
                print(f"  {shot['name']:24} FAILED: {r}")
        ctl(cmd="eye", off=True)
    finally:
        ctl.close()
    (OUT / "shots.json").write_text(json.dumps(taken, indent=1), encoding="utf-8")
    return {"taken": len(taken)}


def _settle(ctl: Control, frames: int) -> None:
    """Let the sea ease, the sky retint and the camera arrive - the shot must be stable."""
    import time

    time.sleep(max(frames, 1) / 30.0)
    ctl(cmd="state")


# ---------------------------------------------------------------- image measurement


def _read_png(path: Path) -> np.ndarray | None:
    """Minimal PNG reader (RGB/RGBA, 8-bit, non-interlaced) - no Pillow dependency."""
    import zlib

    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, w = 8, bytearray(), 0
    h = bits = ctype = 0
    while pos < len(raw):
        ln = struct.unpack_from(">I", raw, pos)[0]
        typ = raw[pos + 4 : pos + 8]
        body = raw[pos + 8 : pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bits, ctype = struct.unpack_from(">IIBB", body, 0)
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if bits != 8 or ctype not in (2, 6):
        return None
    ch = 3 if ctype == 2 else 4
    data = zlib.decompress(bytes(idat))
    stride = w * ch
    out = np.zeros((h, stride), np.uint8)
    prev = np.zeros(stride, np.int32)
    p = 0
    for y in range(h):
        ft = data[p]
        p += 1
        line = np.frombuffer(data, np.uint8, stride, p).astype(np.int32)
        p += stride
        cur = line.copy()
        if ft == 1:
            for i in range(ch, stride):
                cur[i] = (cur[i] + cur[i - ch]) & 0xFF
        elif ft == 2:
            cur = (cur + prev) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = cur[i - ch] if i >= ch else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a_ = cur[i - ch] if i >= ch else 0
                b_ = prev[i]
                c_ = prev[i - ch] if i >= ch else 0
                pp = a_ + b_ - c_
                pa, pb, pc = abs(pp - a_), abs(pp - b_), abs(pp - c_)
                pr = a_ if (pa <= pb and pa <= pc) else (b_ if pb <= pc else c_)
                cur[i] = (cur[i] + pr) & 0xFF
        out[y] = cur
        prev = cur
    return out.reshape(h, w, ch)[:, :, :3]


def bands(img: np.ndarray) -> dict:
    """Mean colour of three horizontal bands: sky, middle, foreground."""
    h = img.shape[0]
    cut = (0, h // 3, 2 * h // 3, h)
    names = ("sky", "middle", "foreground")
    out = {}
    for i, nm in enumerate(names):
        seg = img[cut[i] : cut[i + 1]].reshape(-1, 3).astype(float)
        out[nm] = [round(float(v), 1) for v in seg.mean(axis=0)]
    return out


# ---------------------------------------------------------------- report


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def build_report() -> Path:
    cov = _load(OUT / "coverage.json")
    mat = _load(OUT / "materials.json")
    shots = _load(OUT / "shots.json") or []
    REFDIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for shot in shots:
        ours = OUT / shot["file"]
        ref = REFDIR / f"{shot['name']}.png"
        a = _read_png(ours) if ours.exists() else None
        b = _read_png(ref) if ref.exists() else None
        rows.append({
            "shot": shot,
            "ours": ours,
            "ref": ref if ref.exists() else None,
            "ours_bands": bands(a) if a is not None else None,
            "ref_bands": bands(b) if b is not None else None,
        })

    html = [_HEAD]
    html.append("<header><h1>Remake vs. the disc</h1><p class='sub'>Wind Waker in Godot, "
                "measured against the game it was ripped from. Nothing here is a claim of "
                "similarity that was not measured.</p></header>")

    # coverage
    html.append("<section><h2>Coverage <span class='tag'>offline</span></h2>")
    if cov:
        pct = 100.0 * (1.0 - cov["uncovered_area"] / max(cov["total_area"], 1.0))
        html.append(
            f"<p class='lead'>{cov['scene']}: <b>{pct:.1f}%</b> of walkable collision area has "
            f"something drawn above it. {cov['uncovered']} of {cov['walkable_triangles']} "
            f"walkable triangles have nothing — those are the invisible platforms.</p>"
        )
        if cov["clusters"]:
            html.append("<table><thead><tr><th>where (x, y, z)</th><th class='n'>triangles</th>"
                        "<th class='n'>area</th></tr></thead><tbody>")
            for cl in cov["clusters"][:15]:
                at = cl["at"]
                html.append(f"<tr><td class='mono'>{at[0]}, {at[1]}, {at[2]}</td>"
                            f"<td class='n'>{cl['triangles']}</td>"
                            f"<td class='n'>{cl['area']:,.0f}</td></tr>")
            html.append("</tbody></table>")
    else:
        html.append("<p class='none'>not run</p>")
    html.append("</section>")

    # waterline
    wl = _load(OUT / "waterline.json")
    html.append("<section><h2>Waterline <span class='tag'>offline</span></h2>")
    if wl:
        html.append(
            f"<p class='lead'>{wl['dry_spawns']} of {len(wl['spawns'])} spawn points stand clear "
            f"of the sea. The rest sit at y = 0 - those are arrivals by boat, and are meant to "
            f"be in the water.</p>"
            f"<p>The sea's peak is <code>1 + 10 &times; wave_max</code>. If the sea is left at "
            f"the open-sea swell instead of the room's own, its peak is "
            f"<b>{wl['open_sea_peak']}</b> and "
            f"<b>{len(wl['would_flood_at_open_sea'])}</b> dry spawns go under water: "
            f"<span class='mono'>{wl['would_flood_at_open_sea']}</span>. Spawn 0 is the dock "
            f"the game starts you on.</p>"
        )
        html.append("<table><thead><tr><th>spawn</th><th class='n'>ground y</th>"
                    "<th class='n'>wave_max</th><th class='n'>sea peak</th>"
                    "<th class='n'>clearance</th></tr></thead><tbody>")
        for row in sorted(wl["spawns"], key=lambda r: r["clearance"])[:10]:
            html.append(f"<tr><td class='mono'>{row['spawn']}</td>"
                        f"<td class='n'>{row['pos'][1]}</td><td class='n'>{row['wave_max']:g}</td>"
                        f"<td class='n'>{row['sea_peak']}</td>"
                        f"<td class='n'>{row['clearance']}</td></tr>")
        html.append("</tbody></table>")
    else:
        html.append("<p class='none'>not run</p>")
    html.append("</section>")

    # motion
    stab = _load(OUT / "stability_outset_harbour.json")
    setl = _load(OUT / "settle_outset_harbour.json")
    html.append("<section><h2>Motion <span class='tag'>needs the game</span></h2>")
    if stab or setl:
        if stab:
            html.append(f"<p class='lead'>Held camera, {stab['frames']} frames: the worst "
                        f"consecutive pair differs by <b>{stab['worst_step_pct']}%</b> of pixels. "
                        "Waves, foam and birds animate, so a low steady churn is correct; a spike "
                        "is geometry blinking.</p>")
        if setl:
            html.append("<p>After a reload, each frame against the settled one:</p>"
                        "<table><thead><tr><th>after</th>"
                        "<th class='n'>differs from settled</th></tr></thead><tbody>")
            for row in setl["vs_last"]:
                html.append(f"<tr><td class='mono'>{row['frame']}</td>"
                            f"<td class='n'>{row['changed_pixels_pct']}%</td></tr>")
            html.append("</tbody></table>")
    else:
        html.append("<p class='none'>not run</p>")
    html.append("</section>")

    # materials
    html.append("<section><h2>Shading <span class='tag'>offline</span></h2>")
    if mat:
        d = mat["disc_audit"]
        html.append(
            f"<p class='lead'>{mat['scene']}: {mat['materials']} materials, "
            f"{mat['double_sided']} double-sided, {len(mat['untextured'])} with no texture.</p>"
            f"<p>Measured against the disc across {d.get('sample', 'a sample')}: "
            f"<b>{d.get('texture_layers_dropped')}</b> bound texture layers never reach glTF, "
            f"<b>{d.get('materials_with_no_texture')}</b> export plain white, and "
            f"<b>{d.get('toon_ramp_mistaken_for_base')}</b> picked the toon ramp as their base "
            f"colour. That is the shading gap, and it is not small.</p>"
        )
        if mat["untextured"]:
            html.append("<p class='mono small'>untextured here: "
                        + ", ".join(mat["untextured"][:24]) + "</p>")
    else:
        html.append("<p class='none'>not run</p>")
    html.append("</section>")

    # shots
    html.append("<section><h2>Frames <span class='tag'>needs the game</span></h2>")
    if not rows:
        html.append("<p class='none'>no shots captured yet</p>")
    for r in rows:
        s = r["shot"]
        html.append(f"<article><h3>{s['name']}</h3><p class='small'>{s.get('note','')}</p>")
        html.append("<div class='pair'>")
        html.append(f"<figure><img src='{_rel(r['ours'])}' alt='ours'><figcaption>ours</figcaption></figure>")
        if r["ref"]:
            html.append(f"<figure><img src='{_rel(r['ref'])}' alt='original'>"
                        "<figcaption>original</figcaption></figure>")
        else:
            html.append("<figure class='empty'><div class='drop'>drop a reference frame at<br>"
                        f"<code>docs/compare_reference/{s['name']}.png</code></div>"
                        "<figcaption>original</figcaption></figure>")
        html.append("</div>")
        if r["ours_bands"]:
            html.append("<table class='bands'><thead><tr><th>band</th><th>ours</th>"
                        + ("<th>original</th><th class='n'>delta</th>" if r["ref_bands"] else "")
                        + "</tr></thead><tbody>")
            for band in ("sky", "middle", "foreground"):
                o = r["ours_bands"][band]
                cells = f"<td><span class='sw' style='background:{_hex(o)}'></span>{_hex(o)}</td>"
                if r["ref_bands"]:
                    t = r["ref_bands"][band]
                    dlt = math.dist(o, t)
                    cells += (f"<td><span class='sw' style='background:{_hex(t)}'></span>"
                              f"{_hex(t)}</td><td class='n'>{dlt:.0f}</td>")
                html.append(f"<tr><td>{band}</td>{cells}</tr>")
            html.append("</tbody></table>")
        html.append("</article>")
    html.append("</section>")

    html.append("<footer><p>Coverage and shading read the ISO and the export directly and need "
                "no running game. Frames need the build running with <code>--control</code>. "
                "Colour deltas are plain RGB distance over a band — a coarse measure, honest "
                "about being coarse.</p></footer></div>")
    dest = DOCS / "compare.html"
    dest.write_text("\n".join(html), encoding="utf-8")
    return dest


def _rel(p: Path | None) -> str:
    """Inline the image as a data URI.

    The report is meant to be published and shared, and a published page cannot reach a
    file:// path on this machine - a linked screenshot would be a broken image to anyone
    but me. 2.8 MB of PNG inlines comfortably.
    """
    if p is None or not p.exists():
        return ""
    import base64

    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


_HEAD = """<title>Remake vs. the Disc</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bitter:wght@600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root{
  --ink:#16202b; --ink-soft:#5a6b7c; --line:#d9e0e7; --bg:#f7f8f6; --card:#ffffff;
  --accent:#0a6c74; --accent-soft:#e2f0f0; --warn:#a8492b;
}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --ink:#e8edf1; --ink-soft:#93a3b2; --line:#2b3745; --bg:#101820; --card:#17222c;
  --accent:#4ec8cf; --accent-soft:#12333a; --warn:#e08a68;
}}
:root[data-theme="dark"]{
  --ink:#e8edf1; --ink-soft:#93a3b2; --line:#2b3745; --bg:#101820; --card:#17222c;
  --accent:#4ec8cf; --accent-soft:#12333a; --warn:#e08a68;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.65 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;}
.wrap{max-width:1080px;margin:0 auto;padding:48px 24px 96px;display:flex;flex-direction:column;gap:40px}
header h1{font:700 40px/1.15 Bitter,Georgia,serif;margin:0 0 8px;letter-spacing:-.02em;text-wrap:balance}
.sub{color:var(--ink-soft);margin:0;max-width:62ch}
h2{font:700 22px/1.3 Bitter,Georgia,serif;margin:0 0 12px;display:flex;align-items:center;gap:10px}
h3{font:600 17px/1.3 Inter,sans-serif;margin:0 0 2px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:24px}
.tag{font:500 11px/1 Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;
  color:var(--accent);background:var(--accent-soft);padding:5px 8px;border-radius:4px}
.lead{margin:0 0 12px}
.none{color:var(--ink-soft);font-style:italic;margin:0}
.small{font-size:13px;color:var(--ink-soft)}
.mono,code{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:13px}
table{width:100%;border-collapse:collapse;margin-top:10px;font-size:14px;display:block;overflow-x:auto}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-weight:600;color:var(--ink-soft);font-size:12px;letter-spacing:.04em;text-transform:uppercase}
.n{text-align:right;font-variant-numeric:tabular-nums}
article{border-top:1px solid var(--line);padding-top:20px;margin-top:20px}
section article:first-of-type{border-top:0;padding-top:0;margin-top:0}
.pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin:12px 0}
figure{margin:0}
figure img{width:100%;height:auto;display:block;border-radius:6px;border:1px solid var(--line)}
figcaption{font-size:12px;color:var(--ink-soft);margin-top:5px;letter-spacing:.04em;text-transform:uppercase}
.empty .drop{border:1px dashed var(--line);border-radius:6px;padding:38px 16px;text-align:center;
  color:var(--ink-soft);font-size:13px;background:var(--bg)}
.sw{display:inline-block;width:13px;height:13px;border-radius:3px;border:1px solid var(--line);
  margin-right:7px;vertical-align:-2px}
.bands{max-width:560px}
footer p{color:var(--ink-soft);font-size:14px;margin:0;max-width:70ch}
</style>
<div class="wrap">"""


# ---------------------------------------------------------------- cli


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("coverage", help="walkable collision with nothing drawn above it")
    c.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    c.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    c.add_argument("--stage", default="sea")
    c.add_argument("--room", type=int, default=44)
    c.add_argument("--scene", default=None, help="exported scene name (default sea_r<room>)")
    c.add_argument("--min-y", type=float, default=-300.0,
                   help="ignore collision below this height (sea bed, kill planes)")
    c.add_argument("--max-area", type=float, default=4.0e6,
                   help="ignore triangles larger than this (backdrop quads)")

    m = sub.add_parser("materials", help="what the disc's shading has that our glTF does not")
    m.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    m.add_argument("--scene", default="sea_r44")

    s = sub.add_parser("shots", help="capture the shot list from a running build")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--only", default=None)

    w = sub.add_parser("waterline", help="spawns and docks the sea can climb over")
    w.add_argument("--scene", default="sea_r44")

    st = sub.add_parser("stability", help="fixed camera, N frames - find what blinks")
    st.add_argument("--port", type=int, default=8787)
    st.add_argument("--shot", default="outset_village")
    st.add_argument("--frames", type=int, default=10)
    st.add_argument("--gap", type=float, default=0.45)

    se = sub.add_parser("settle", help="reload, then watch the frame stop changing")
    se.add_argument("--port", type=int, default=8787)
    se.add_argument("--shot", default="outset_harbour")

    sub.add_parser("report", help="build docs/compare.html from whatever has been run")

    a = sub.add_parser("all", help="coverage + materials + report")
    a.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    a.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    a.add_argument("--stage", default="sea")
    a.add_argument("--room", type=int, default=44)
    a.add_argument("--scene", default=None)

    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.cmd in ("coverage", "all"):
        scene = args.scene or (f"{args.stage}_r{args.room}" if args.room is not None else args.stage)
        r = coverage(args.iso, args.build, args.stage, args.room, scene,
                     getattr(args, "min_y", -300.0), getattr(args, "max_area", 4.0e6))
        (OUT / "coverage.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        pct = 100.0 * (1.0 - r["uncovered_area"] / max(r["total_area"], 1.0))
        print(f"coverage {scene}: {pct:.1f}% of walkable area is drawn; "
              f"{r['uncovered']}/{r['walkable_triangles']} triangles bare")
        for cl in r["clusters"][:6]:
            print(f"    {cl['at']}  {cl['triangles']} tris  area {cl['area']:,.0f}")

    if args.cmd in ("materials", "all"):
        scene = getattr(args, "scene", None) or "sea_r44"
        if args.cmd == "all":
            scene = args.scene or f"{args.stage}_r{args.room}"
        r = materials(args.build, scene)
        (OUT / "materials.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        d = r["disc_audit"]
        print(f"materials {scene}: {r['materials']} materials, {len(r['untextured'])} untextured; "
              f"disc audit: {d['texture_layers_dropped']} texture layers dropped")

    if args.cmd == "shots":
        take_shots(args.port, args.only)

    if args.cmd in ("waterline", "all"):
        scene = getattr(args, "scene", None) or (
            f"{args.stage}_r{args.room}" if args.cmd == "all" else "sea_r44")
        r = waterline(scene)
        (OUT / "waterline.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(f"waterline {scene}: {r['submerged']} of {len(r['spawns'])} spawns under the "
              f"sea's peak (y=0 sea arrivals are meant to be); {r['dry_spawns']} dry.")
        print(f"    if the sea were left at the open-sea swell (peak {r['open_sea_peak']}), "
              f"{len(r['would_flood_at_open_sea'])} dry spawns would flood: "
              f"{r['would_flood_at_open_sea']}")
        for row in r["spawns"]:
            if row["submerged"] or row["clearance"] < 200:
                flag = "UNDER WATER" if row["submerged"] else "tight"
                print(f"    spawn {row['spawn']} room {row['room']} y={row['pos'][1]} "
                      f"peak={row['sea_peak']} clearance={row['clearance']}  {flag}")

    if args.cmd == "stability":
        r = stability(args.port, args.shot, args.frames, args.gap)
        print(f"stability {args.shot}: worst consecutive frame change "
              f"{r['worst_step_pct']}% of pixels over {r['frames']} frames")
        for stp in r["steps"]:
            print(f"    {stp['from']} -> {stp['to']}: {stp['changed_pixels_pct']}% "
                  f"(mean {stp['mean_delta']})")

    if args.cmd == "settle":
        r = settle(args.port, args.shot, [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 26.0])
        print(f"settle {args.shot}: {r['frames']} frames after load")
        for row in r["vs_last"]:
            print(f"    {row['frame']:34} differs from settled by "
                  f"{row['changed_pixels_pct']}% of pixels")

    if args.cmd in ("report", "all"):
        print("report ->", build_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
