# ruff: noqa: E501
"""Bake Wind Waker's JStudio cutscenes (``.stb``) into per-frame tracks an engine can play.

``gcrip/formats/stb.py`` gives the raw timeline: every object (actor / camera / message /
sound / particle) with a list of keys per feature, where a key is either an immediate value,
an id, or a reference to an FVB curve.  Playing that faithfully at runtime means
re-implementing JStudio's sampler in the engine; baking it here to one value per frame keeps
the engine side to "read row f" and costs a few hundred kB of JSON per scene.

What is baked (the features a scene needs to read on screen):

* camera: eye, target, field of view, roll
* actors: position, Y rotation, uniform scale, animation id + frame + mode, shape id
* message: the BMG message id shown on each frame

Sound and particle objects are recorded by name only - the engine has no emitter for them yet.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gcrip.formats import rarc, stb, yay0, yaz0

DEMO_ANIMS = Path(__file__).with_name("data") / "ww_demo_anims.json"
FPS = 30.0
POS_ROUND = 0  # game units are ~100 per metre: whole units are far below what shows
ANGLE_ROUND = 2


def _rle(values: list) -> Any:
    """[v, v, v, w, ...] -> [[first_frame, value], ...]; a constant track collapses to the
    bare value and an empty one to None.  The engine reads it with a small cursor."""
    if not values or all(v is None for v in values):
        return None
    out: list[list[Any]] = []
    last = object()
    for i, v in enumerate(values):
        if v != last:
            out.append([i, v])
            last = v
    if len(out) == 1:
        return out[0][1]
    return out


def _round(v, nd: int):
    if v is None:
        return None
    if isinstance(v, list):
        return [_round(x, nd) for x in v]
    return int(round(v)) if nd <= 0 else round(v, nd)


@dataclass
class _TrackView:
    """One feature of one object, ready to sample at any frame."""

    keys: list[stb.Key]
    functions: list[stb.Function]

    def value_at(self, frame: int) -> Any:
        key = None
        for k in self.keys:
            if k.frame <= frame:
                key = k
            else:
                break
        if key is None:
            return None
        if key.op_name == "fvr_index":
            t = (frame - key.frame) / FPS
            idx = key.value
            if isinstance(idx, (list, tuple)):
                return [self._curve(i, t) for i in idx]
            return self._curve(idx, t)
        return key.value

    def _curve(self, index: Any, t: float) -> float | None:
        try:
            i = int(index)
        except (TypeError, ValueError):
            return None
        if 0 <= i < len(self.functions):
            v = float(self.functions[i].value_at(t))
            # stb._sample returns nan for the curve kinds it cannot evaluate (composite):
            # that means "unknown", and baking it would write invalid JSON (Godot rejects NaN)
            return v if math.isfinite(v) else None
        return None


def _views(obj: stb.Object, functions: list[stb.Function]) -> dict[str, _TrackView]:
    return {t.name: _TrackView(t.keys, functions) for t in obj.tracks}


def _vec(
    views: dict[str, _TrackView],
    frame: int,
    triple: str,
    axes: tuple[str, str, str],
    last: list[float] | None,
) -> list[float] | None:
    """Sample a vector feature: the XYZ track sets all three, the per-axis tracks override
    one component each (the game writes both, e.g. TRANSLATION_XYZ plus TRANSLATION_Y)."""
    out = list(last) if last else None
    v = views[triple].value_at(frame) if triple in views else None
    if (
        isinstance(v, (list, tuple))
        and len(v) >= 3
        and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v[:3])
    ):
        out = [float(x) for x in v[:3]]
    for i, axis in enumerate(axes):
        if axis not in views:
            continue
        a = views[axis].value_at(frame)
        if isinstance(a, (int, float)) and math.isfinite(a):
            if out is None:
                out = [0.0, 0.0, 0.0]
            out[i] = float(a)
    return out


def _scalar(views: dict[str, _TrackView], frame: int, name: str) -> float | None:
    if name not in views:
        return None
    v = views[name].value_at(frame)
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None


def _ident(views: dict[str, _TrackView], frame: int, name: str) -> int | None:
    if name not in views:
        return None
    v = views[name].value_at(frame)
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _demo_anim_table() -> dict:
    """data/ww_demo_anims.json: per scene / actor, how an ANIMATION value (or, for Link, the
    actor's own data records) resolves to a .bck in the Demo or object archive."""
    if DEMO_ANIMS.exists():
        try:
            return json.loads(DEMO_ANIMS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def _clip_stem(bck: str) -> str:
    return Path(str(bck)).stem


def _clip_track(scene_name: str, actor: str, anim_values: list, table: dict) -> Any:
    """-> a per-frame list of clip names for this actor (None where the scene sets none).

    Two different mechanisms, per the decomp: most actors carry the resource id in the
    ANIMATION value itself, while Link's ANIMATION value is a demo *mode* enum and the real
    animation comes from his data records, which the table already resolved to a frame-keyed
    timeline."""
    info = (table.get("scenes", {}).get(scene_name, {}).get("actors", {}) or {}).get(actor)
    if not info:
        return None
    out: list[str | None] = [None] * len(anim_values)
    timeline = info.get("timeline")
    if timeline:
        keyed = sorted((int(f), v) for f, v in timeline.items())
        cur = None
        ki = 0
        for f in range(len(out)):
            while ki < len(keyed) and keyed[ki][0] <= f:
                cur = _clip_stem(keyed[ki][1].get("bck", ""))
                ki += 1
            out[f] = cur
        return out
    values = info.get("values") or {}
    for f, v in enumerate(anim_values):
        if v is None:
            continue
        hit = values.get(str(int(v)))
        if hit:
            out[f] = _clip_stem(hit.get("bck", ""))
    # an ANIMATION value holds until the next one
    cur = None
    for f in range(len(out)):
        if out[f] is not None:
            cur = out[f]
        else:
            out[f] = cur
    return out


def bake(scene: stb.Stb, *, name: str = "") -> dict:
    """-> {name, frames, seconds, camera, actors[], messages[], sounds[]} with one entry per
    frame in each track (null where the scene never sets that feature)."""
    frames = scene.frames
    out: dict[str, Any] = {
        "name": name,
        "frames": frames,
        "seconds": round(frames / FPS, 2),
        "camera": None,
        "actors": [],
        "messages": [],
        "sounds": [],
    }
    for obj in scene.objects:
        views = _views(obj, scene.functions)
        if obj.kind == "camera":
            eye: list[float] | None = None
            tgt: list[float] | None = None
            cam: dict[str, Any] = {"id": obj.id, "eye": [], "target": [], "fov": [], "roll": []}
            for f in range(frames):
                eye = _vec(
                    views, f, "POSITION_XYZ", ("POSITION_X", "POSITION_Y", "POSITION_Z"), eye
                )
                tgt = _vec(
                    views,
                    f,
                    "TARGET_POSITION_XYZ",
                    ("TARGET_POSITION_X", "TARGET_POSITION_Y", "TARGET_POSITION_Z"),
                    tgt,
                )
                cam["eye"].append([round(v, POS_ROUND) for v in eye] if eye else None)
                cam["target"].append([round(v, POS_ROUND) for v in tgt] if tgt else None)
                fov = _scalar(views, f, "PROJECTION_FOVY")
                roll = _scalar(views, f, "VIEW_ROLL")
                cam["fov"].append(round(fov, ANGLE_ROUND) if fov is not None else None)
                cam["roll"].append(round(roll, ANGLE_ROUND) if roll is not None else None)
            for k in ("eye", "target"):
                cam[k] = _rle([_round(v, POS_ROUND) for v in cam[k]])
            for k in ("fov", "roll"):
                cam[k] = _rle([_round(v, ANGLE_ROUND) for v in cam[k]])
            out["camera"] = cam
        elif obj.kind == "actor":
            pos: list[float] | None = None
            rot: list[float] | None = None
            scl: list[float] | None = None
            a: dict[str, Any] = {
                "id": obj.id,
                "pos": [],
                "rot_y": [],
                "scale": [],
                "anim": [],
                "anim_frame": [],
                "anim_mode": [],
                "shape": [],
            }
            for f in range(frames):
                pos = _vec(
                    views,
                    f,
                    "TRANSLATION_XYZ",
                    ("TRANSLATION_X", "TRANSLATION_Y", "TRANSLATION_Z"),
                    pos,
                )
                rot = _vec(
                    views, f, "ROTATION_XYZ", ("ROTATION_X", "ROTATION_Y", "ROTATION_Z"), rot
                )
                scl = _vec(views, f, "SCALING_XYZ", ("SCALING_X", "SCALING_Y", "SCALING_Z"), scl)
                a["pos"].append([round(v, POS_ROUND) for v in pos] if pos else None)
                a["rot_y"].append(round(rot[1], ANGLE_ROUND) if rot else None)
                a["scale"].append(round(scl[0], ANGLE_ROUND) if scl else None)
                a["anim"].append(_ident(views, f, "ANIMATION"))
                af = _scalar(views, f, "ANIMATION_FRAME")
                a["anim_frame"].append(round(af, 2) if af is not None else None)
                a["anim_mode"].append(_ident(views, f, "ANIMATION_MODE"))
                a["shape"].append(_ident(views, f, "SHAPE"))
            a["clip"] = _rle(_clip_track(name, str(a["id"]), a["anim"], _DEMO_TABLE) or [])
            a["pos"] = _rle([_round(v, POS_ROUND) for v in a["pos"]])
            a["rot_y"] = _rle([_round(v, ANGLE_ROUND) for v in a["rot_y"]])
            a["scale"] = _rle([_round(v, ANGLE_ROUND) for v in a["scale"]])
            for k in ("anim", "anim_frame", "anim_mode", "shape"):
                a[k] = _rle(a[k])
            if all(a[k] is None for k in ("pos", "rot_y", "scale", "anim", "shape", "clip")):
                continue  # a demo-only prop the file never actually drives
            out["actors"].append(a)
        elif obj.kind == "message":
            msgs = _rle([_ident(views, f, "MESSAGE") for f in range(frames)])
            if msgs is not None:
                out["messages"].append({"id": obj.id, "msg": msgs})
        elif obj.kind == "sound":
            out["sounds"].append({"id": obj.id})
    return out


_DEMO_TABLE = _demo_anim_table()


def clips_by_actor() -> dict[str, set[str]]:
    """{actor name: every cutscene clip it plays} - the rigs must export these."""
    out: dict[str, set[str]] = {}
    for scene in _DEMO_TABLE.get("scenes", {}).values():
        for actor, info in (scene.get("actors") or {}).items():
            names = out.setdefault(actor, set())
            for v in (info.get("values") or {}).values():
                if v.get("bck"):
                    names.add(_clip_stem(v["bck"]))
            for v in (info.get("timeline") or {}).values():
                if v.get("bck"):
                    names.add(_clip_stem(v["bck"]))
    return out


def _read_arc(disc, path: str):
    e = disc.entries[path]
    blob = disc.img.read(e.offset, e.size)
    if blob[:4] == b"Yaz0":
        blob = yaz0.decompress(blob)
    elif blob[:4] == b"Yay0":
        blob = yay0.decompress(blob)
    return blob, rarc.parse(blob)


def find_cutscenes(disc) -> dict[str, tuple[str, bytes]]:
    """{cutscene name: (archive path, raw .stb bytes)} across every archive on the disc."""
    out: dict[str, tuple[str, bytes]] = {}
    for path in sorted(disc.entries):
        if not path.endswith(".arc") or ("Demo" not in path and "/Stage/" not in path):
            continue
        try:
            blob, arc = _read_arc(disc, path)
        except (ValueError, KeyError, IndexError):
            continue
        for f in arc.files:
            if not f.path.lower().endswith(".stb"):
                continue
            name = Path(f.path).stem
            if name not in out:
                out[name] = (path, arc.read(blob, f))
    return out


def dump_cutscenes(rip_dir, out_dir=None, *, iso=None, quiet: bool = False) -> dict:
    """Every .stb on the disc -> <out_dir>/<name>.json (baked) + index.json."""
    from gcrip.stage import _Disc, _find_iso

    rip_dir = Path(rip_dir)
    out_dir = Path(out_dir) if out_dir else rip_dir / "cutscenes"
    out_dir.mkdir(parents=True, exist_ok=True)
    disc = _Disc(_find_iso(rip_dir, iso))
    found = find_cutscenes(disc)
    index: dict[str, dict] = {}
    for i, (name, (arc_path, data)) in enumerate(sorted(found.items()), 1):
        try:
            scene = stb.parse(data)
            baked = bake(scene, name=name)
        except (ValueError, IndexError, KeyError, struct.error) as ex:
            if not quiet:
                print(f"[{i}/{len(found)}] {name}: FAILED {ex}")
            continue
        # allow_nan=False: NaN/Infinity are not JSON and Godot's parser rejects the file
        (out_dir / f"{name}.json").write_text(json.dumps(baked, allow_nan=False), encoding="utf-8")
        index[name] = {
            "arc": arc_path,
            "frames": baked["frames"],
            "seconds": baked["seconds"],
            "actors": [a["id"] for a in baked["actors"]],
            "camera": baked["camera"] is not None,
            "messages": sum(1 for m in baked["messages"] if any(x for x in m["msg"])),
        }
        if not quiet:
            print(
                f"[{i}/{len(found)}] {name:22s} {baked['frames']:5d}f "
                f"{baked['seconds']:6.1f}s  {len(baked['actors'])} actors"
            )
    (out_dir / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    if not quiet:
        print(f"{len(index)} cutscenes -> {out_dir}")
    return index
