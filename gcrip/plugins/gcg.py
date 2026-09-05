"""Runecraft ``gcg\\0`` geometry (gcrip.formats.gcg) - Mat Hoffman's Pro BMX 2 park chunks,
props, riders and bikes.  One Scene per file: submeshes baked into world space through the
node hierarchy (skinned riders bind each vertex rigidly to one node), materials bound to
the ``.gcm`` INI next to the model's ``textures/`` folder and their ``.gct`` pictures.

Claiming the files is also what keeps the ``gx`` fallback off them: unclaimed, it paired
the f32 position arrays with the wrong index words and 472 of GMHE52's 533 exports were
flagged by the quality audit.
"""

from __future__ import annotations

import contextlib
import posixpath

import numpy as np

from gcrip.formats import gcg
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "gcg"


def detect(path: str, head: bytes, size: int) -> bool:
    return gcg.is_gcg(head)


def _lower_index(src) -> dict[str, str]:
    """lowercase manifest path -> manifest path, cached on the source object."""
    idx = getattr(src, "_gcg_lower", None)
    if idx is None:
        idx = {p.lower(): p for p in getattr(src, "by_path", {})}
        with contextlib.suppress(AttributeError):
            src._gcg_lower = idx
    return idx


def _sibling(src, path: str, name: str) -> tuple[str, bytes] | None:
    """Find ``name`` in the model's folder, its ``textures/`` folder or the parent's."""
    if src is None:
        return None
    idx = _lower_index(src)
    folder = posixpath.dirname(path)
    parent = posixpath.dirname(folder)
    for d in (
        folder,
        posixpath.join(folder, "textures"),
        posixpath.join(parent, "textures"),
        parent,
    ):
        want = posixpath.join(d, name).lower() if d else name.lower()
        hit = idx.get(want)
        if hit is not None:
            try:
                return hit, src.get(hit)
            except Exception:  # noqa: BLE001 - a missing sibling must not lose the model
                return None
    return None


def _materials(model: gcg.Model, path: str, src, scene: Scene) -> None:
    for name in model.materials:
        mat = MaterialDef(name=name, texture=None)
        found = _sibling(src, path, f"{name}.gcm")
        if found is not None:
            gcm_path, gcm = found
            text = gcm.decode("latin1", errors="replace")
            stem = gcg.material_texture(text)
            if "GX_BM_BLEND" in text:
                mat.alpha_blend = True
            if stem:
                key = stem.lower()
                if key not in scene.textures:
                    tex = _sibling(src, gcm_path, f"{stem}.gct")
                    if tex is not None:
                        try:
                            scene.textures[key] = gcg.decode_gct(tex[1]).rgba
                        except gcg.GcgError as e:
                            scene.warnings.append(f"{stem}.gct: {e}")
                if key in scene.textures:
                    mat.texture = key
        scene.materials.append(mat)
    scene.materials.append(
        MaterialDef(name="(none)", texture=None, base_color=(0.6, 0.6, 0.6, 1.0))
    )


def _bake(sub: gcg.Submesh, world: list[np.ndarray]) -> Primitive | None:
    """De-index one submesh into a Primitive with world-space positions."""
    rows, tris, base = [], [], 0
    for (op, idx), bind in zip(sub.prims, sub.binds, strict=True):
        count = len(idx)
        corner = np.arange(count, dtype=np.uint32).reshape(-1, 1)
        t = gcg.triangulate([(op, corner)]) + base
        rows.append(np.concatenate([idx.astype(np.int64), bind.reshape(-1, 1)], axis=1))
        tris.append(t)
        base += count
    if not rows:
        return None
    corners = np.concatenate(rows)
    tri = np.concatenate(tris)
    if len(tri) == 0:
        return None
    uniq, inverse = np.unique(corners, axis=0, return_inverse=True)
    tri = inverse.reshape(-1)[tri]
    # strips are stitched with repeated vertices; those triangles have no area
    keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
    tri = tri[keep]
    if len(tri) == 0:
        return None
    col = 0
    positions = sub.positions[uniq[:, col]].astype(np.float64)
    col += 1
    normals = None
    if sub.normals is not None:
        normals = sub.normals[uniq[:, col]].astype(np.float64)
        col += 1
    colors = None
    if sub.colors is not None:
        colors = sub.colors[uniq[:, col]].astype(np.float32) / 255.0
        col += 1
    uvs = None
    if sub.uvs is not None:
        uvs = sub.uvs[uniq[:, col]].astype(np.float32)
        col += 1
    nodes = uniq[:, -1]
    out_pos = np.empty_like(positions)
    out_nrm = np.empty_like(normals) if normals is not None else None
    for node in np.unique(nodes):
        m = world[node] if 0 <= node < len(world) else world[0]
        sel = nodes == node
        p = positions[sel]
        out_pos[sel] = p @ m[:3, :3] + m[3, :3]
        if normals is not None:
            n = normals[sel] @ m[:3, :3]
            length = np.linalg.norm(n, axis=1, keepdims=True)
            out_nrm[sel] = np.where(length > 1e-8, n / np.maximum(length, 1e-8), n)
    a, b, c = out_pos[tri[:, 0]], out_pos[tri[:, 1]], out_pos[tri[:, 2]]
    flat = np.all(a == b, axis=1) | np.all(b == c, axis=1) | np.all(a == c, axis=1)
    tri = tri[~flat]
    if len(tri) == 0:
        return None
    return Primitive(
        material=0,
        positions=out_pos.astype(np.float32),
        indices=tri.astype(np.uint32).reshape(-1),
        normals=out_nrm.astype(np.float32) if out_nrm is not None else None,
        uvs=uvs,
        colors=colors,
    )


def build_scene(model: gcg.Model, path: str, src) -> Scene:
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "model"
    scene = Scene(name=stem)
    _materials(model, path, src, scene)
    none_material = len(scene.materials) - 1
    world = gcg.world_matrices(model.nodes)
    for sub in model.submeshes:
        prim = _bake(sub, world)
        if prim is None:
            continue
        prim.material = sub.material if sub.material < none_material else none_material
        scene.primitives.append(prim)
    scene.extras = {
        "format": "gcg",
        "nodes": [n.name for n in model.nodes],
        "skinned": any(s.skinned for s in model.submeshes),
    }
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = gcg.parse(data)
    if not model.submeshes:
        return []
    return [build_scene(model, path, src)]
