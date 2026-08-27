"""Evaluate a parsed Ninja model into a Scene: walk the object tree in Ninja's order, feed
the vertex cache exactly the way the runtime does (plain chunks replace slots, weighted
chunks accumulate), and resolve every strip against the cache state at the moment its
object is drawn. Each object becomes a joint; vertices carry the joints that wrote them.
Motions become clips sampled per frame (Ninja interpolates position/scale linearly and
each Euler angle linearly, so that is what the sampler does)."""

from __future__ import annotations

import math

import numpy as np

from dcrip.formats import ninja
from dcrip.scene import Clip, Joint, MaterialDef, Primitive, Scene


def _quat(m: np.ndarray) -> tuple[float, float, float, float]:
    """Rotation matrix (3x3, orthonormal) -> quaternion x y z w."""
    t = np.trace(m)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    i = int(np.argmax([m[0, 0], m[1, 1], m[2, 2]]))
    if i == 0:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    if i == 1:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)


class _CacheEntry:
    __slots__ = ("pos", "nrm", "color", "influences")

    def __init__(self) -> None:
        self.pos = np.zeros(3)
        self.nrm = np.zeros(3)
        self.color: np.ndarray | None = None
        self.influences: list[tuple[int, float]] = []


def _material_def(mat: ninja.Material, texnames: list[str]) -> MaterialDef:
    tex = None
    if mat.texture is not None and mat.texture < len(texnames):
        tex = texnames[mat.texture]
    elif mat.texture is not None:
        tex = f"tex{mat.texture:03d}"
    rgb = "".join(f"{int(c * 255):02x}" for c in mat.diffuse[:3])
    name = tex or f"mat_{rgb}"
    return MaterialDef(
        name=name,
        texture=tex,
        base_color=mat.diffuse,
        alpha_blend=mat.use_alpha,
        double_sided=mat.double_sided,
        clamp_u=mat.clamp_u,
        clamp_v=mat.clamp_v,
        mirror_u=mat.flip_u,
        mirror_v=mat.flip_v,
        unlit=mat.ignore_light,
    )


def evaluate(nj: ninja.Ninja, name: str, *, fps: float = 30.0) -> Scene:
    scene = Scene(name=name)
    scene.warnings += nj.warnings
    objs = nj.objects
    world = [np.eye(4) for _ in objs]
    for o in objs:
        lm = ninja.local_matrix(o)
        world[o.index] = (world[o.parent] @ lm) if o.parent is not None else lm
        scene.joints.append(
            Joint(
                name=o.name,
                parent=o.parent,
                translation=tuple(float(x) for x in o.eval_pos),
                rotation=_quat(ninja.rotation_matrix(o.eval_rot, o.zxy)),
                scale=tuple(float(x) for x in o.eval_scale),
            )
        )
    texnames = nj.texlist.names if nj.texlist else []
    cache: dict[int, _CacheEntry] = {}
    mat_index: dict[tuple, int] = {}
    # per material: vertex dict + index list, merged across objects
    buckets: dict[int, dict] = {}
    cached_lists: dict[int, list] = {}  # NJD_CB_CP slot -> strips drawn on NJD_CB_DP

    def draw(strips, o, rot):
        for s in strips:
            if isinstance(s, ninja.DrawSlot):
                draw(cached_lists.pop(s.slot, []), o, rot)
                continue
            _draw_strip(s, o, rot)

    def _draw_strip(s, o, rot):
        key = s.material.key()
        mi = mat_index.get(key)
        if mi is None:
            mi = len(scene.materials)
            mat_index[key] = mi
            scene.materials.append(_material_def(s.material, texnames))
        b = buckets.setdefault(
            mi,
            {
                "vindex": {},
                "vdata": [],
                "idx": [],
                "uv": s.uvs is not None,
                "col": s.colors is not None,
                "nrm": False,
                "missing": 0,
            },
        )
        vindex, vdata, idx = b["vindex"], b["vdata"], b["idx"]
        for k, ci in enumerate(s.indices):
            e = cache.get(ci)
            if e is None:
                b["missing"] += 1
                e = _CacheEntry()
                e.influences = [(o.index, 1.0)]
            uv = s.uvs[k] if s.uvs else (0.0, 0.0)
            col = s.colors[k] if s.colors else None
            if e.color is not None and col is None:
                col = tuple(float(x) for x in e.color)
                b["col"] = True
            n = None
            if s.normals:
                n = tuple(float(x) for x in rot @ np.array(s.normals[k]))
            elif np.any(e.nrm):
                n = tuple(float(x) for x in e.nrm / (np.linalg.norm(e.nrm) or 1.0))
            if n is not None:
                b["nrm"] = True
            vkey = (ci, uv, col, n)
            vi = vindex.get(vkey)
            if vi is None:
                vi = len(vdata)
                vindex[vkey] = vi
                vdata.append((e, uv, col, n))
            idx.append(vi)

    for o in objs:
        if o.model is None:
            continue
        wm = world[o.index]
        rot = wm[:3, :3]
        for v in o.model.vertices:
            e = cache.get(v.cache_index)
            if v.status == 0 or e is None:
                e = _CacheEntry()
                cache[v.cache_index] = e
            p = wm @ np.array([*v.pos, 1.0])
            e.pos = e.pos + p[:3] * v.weight
            if v.normal is not None:
                e.nrm = e.nrm + (rot @ v.normal) * v.weight
            if v.color is not None:
                e.color = v.color
            e.influences.append((o.index, v.weight))
        if o.model.cache_slot is not None:
            cached_lists[o.model.cache_slot] = o.model.strips
            continue
        if o.hidden:
            continue
        draw(o.model.strips, o, rot)

    missing = 0
    for mi, b in buckets.items():
        vdata = b["vdata"]
        n = len(vdata)
        pos = np.zeros((n, 3), np.float32)
        nrm = np.zeros((n, 3), np.float32) if b["nrm"] else None
        uv = np.zeros((n, 2), np.float32) if b["uv"] else None
        col = np.ones((n, 4), np.float32) if b["col"] else None
        joints = np.zeros((n, 4), np.uint16)
        weights = np.zeros((n, 4), np.float32)
        for vi, (e, uvv, c, nn) in enumerate(vdata):
            pos[vi] = e.pos
            if nrm is not None and nn is not None:
                nrm[vi] = nn
            if uv is not None:
                uv[vi] = uvv
            if col is not None and c is not None:
                col[vi] = c
            infl = sorted(e.influences, key=lambda t: -t[1])[:4]
            total = sum(w for _, w in infl) or 1.0
            for k, (j, w) in enumerate(infl):
                joints[vi, k] = j
                weights[vi, k] = w / total
        missing += b["missing"]
        scene.primitives.append(
            Primitive(
                material=mi,
                positions=pos,
                indices=np.array(b["idx"], np.uint32),
                normals=nrm,
                uvs=uv,
                colors=col,
                joints=joints,
                weights=weights,
            )
        )
    if missing:
        scene.warnings.append(f"{missing} strip corners referenced empty vertex-cache slots")
    if cached_lists:
        scene.warnings.append(f"{len(cached_lists)} cached polygon lists were never drawn")
    for k, m in enumerate(nj.motions):
        scene.clips.append(sample_motion(m, nj, f"motion{k:02d}", fps))
    return scene


def _lerp_keys(keys: list[tuple[int, tuple]], frame: float) -> np.ndarray:
    if frame <= keys[0][0]:
        return np.array(keys[0][1], dtype=np.float64)
    if frame >= keys[-1][0]:
        return np.array(keys[-1][1], dtype=np.float64)
    for (f0, v0), (f1, v1) in zip(keys, keys[1:], strict=False):
        if f0 <= frame <= f1:
            t = 0.0 if f1 == f0 else (frame - f0) / (f1 - f0)
            return np.array(v0, dtype=np.float64) * (1 - t) + np.array(v1, dtype=np.float64) * t
    return np.array(keys[-1][1], dtype=np.float64)


def sample_motion(m: ninja.Motion, nj: ninja.Ninja, name: str, fps: float) -> Clip:
    clip = Clip(name=name, frames=max(1, m.frames), fps=fps)
    frames = clip.frames
    for oi, tr in enumerate(m.tracks):
        if oi >= len(nj.objects) or not tr:
            continue
        obj = nj.objects[oi]
        if "pos" in tr:
            clip.translation[oi] = np.array(
                [_lerp_keys(tr["pos"], f) for f in range(frames)], np.float32
            )
        if "rot" in tr:
            quats = []
            for f in range(frames):
                ang = _lerp_keys(tr["rot"], f)
                quats.append(_quat(ninja.rotation_matrix(tuple(ang), obj.zxy)))
            clip.rotation[oi] = np.array(quats, np.float32)
        if "scale" in tr:
            clip.scale[oi] = np.array(
                [_lerp_keys(tr["scale"], f) for f in range(frames)], np.float32
            )
    return clip
