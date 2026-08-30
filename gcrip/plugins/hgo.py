"""Traveller's Tales ``.hgo`` characters (Crash Bandicoot: The Wrath of Cortex, Finding Nemo)
through gcrip.formats.hgo: reversed-tag NU2 chunk tree, f32 vertices with per-vertex skin
weights, RGB5A3 / CMPR textures."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import hgo
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "hgo"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith((".hgo", ".nus")) and size >= 0x40 and hgo.is_hgo(head)


def _placed(m: hgo.Mesh, mat: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    """Apply an INST 4x4 (row-vector convention) to a mesh's positions and normals."""
    r = mat[:3, :3]
    pos = (m.positions.astype(np.float64) @ r + mat[3, :3]).astype(np.float32)
    if m.normals is None:
        return pos, None
    nrm = m.normals.astype(np.float64) @ r
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, ln, out=np.zeros_like(nrm), where=ln > 0)
    return pos, nrm.astype(np.float32)


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = hgo.parse(data)
    name = posixpath.basename(path).rsplit(".", 1)[0]
    fmt = "tt-hgo" if model.kind == "hgo" else "tt-gsc"
    rgba = {t.name: t.rgba for t in model.textures if t.rgba is not None}
    if not model.meshes:
        if not rgba:
            return []
        scene = Scene(name=name)
        scene.textures.update(rgba)
        scene.extras = {"format": fmt, "textures_only": True}
        return [scene]
    scene = Scene(name=name)
    skinned = model.kind == "hgo" and any(m.joints is not None for m in model.meshes)
    if skinned:
        for k in range(max(model.node_count, 1)):
            nm = model.names[k] if k < len(model.names) else f"node{k:03d}"
            scene.joints.append(
                Joint(
                    name=nm,
                    parent=None,
                    translation=(0.0, 0.0, 0.0),
                    rotation=(0.0, 0.0, 0.0, 1.0),
                    scale=(1.0, 1.0, 1.0),
                )
            )
    mats: dict[int, int] = {}
    for m in model.meshes:
        if m.material not in mats:
            md = model.materials[m.material] if m.material < len(model.materials) else None
            tex = None
            if md is not None and 0 <= md.texture < len(model.textures):
                tn = model.textures[md.texture].name
                if tn in rgba:
                    tex = tn
                    scene.textures.setdefault(tn, rgba[tn])
            blend = bool(tex) and bool(np.any(rgba[tex][..., 3] < 255))
            scene.materials.append(
                MaterialDef(
                    name=tex or f"mat{m.material:03d}",
                    texture=tex,
                    base_color=(*md.color, 1.0) if md is not None else (1.0, 1.0, 1.0, 1.0),
                    alpha_blend=blend,
                    double_sided=True,
                )
            )
            mats[m.material] = len(scene.materials) - 1
        joints = weights = None
        if skinned:
            n = len(m.positions)
            if m.joints is not None:
                joints = np.minimum(m.joints, max(len(scene.joints) - 1, 0)).astype(np.uint16)
                weights = m.weights.astype(np.float32)
            else:
                joints = np.zeros((n, 4), np.uint16)
                weights = np.tile(np.array([1.0, 0, 0, 0], np.float32), (n, 1))
        pos, nrm = m.positions, m.normals
        if model.kind == "gsc" and m.group < len(model.instances):
            pos, nrm = _placed(m, model.instances[m.group])
        scene.primitives.append(
            Primitive(
                material=mats[m.material],
                positions=pos,
                indices=m.indices.astype(np.uint32),
                normals=nrm,
                uvs=m.uvs,
                colors=m.colors,
                joints=joints,
                weights=weights,
            )
        )
    scene.extras = {
        "format": fmt,
        "meshes": len({m.group for m in model.meshes}),
        "blocks": len(model.meshes),
        "nodes": model.node_count,
        "instances": len(model.instances),
        "textures": len(model.textures),
        "skinned": skinned,
    }
    return [scene]
