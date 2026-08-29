"""Traveller's Tales GameCube (LEGO Star Wars II, The Chronicles of Narnia): ``.csc`` scenes /
``.chg`` characters through their DISP display programs (gcrip.formats.ttdisp), plus the
``.fpk`` / ``.cpk`` packs (``0x12345678`` magic, 28-byte entries) as a container."""

from __future__ import annotations

import posixpath
import struct

import numpy as np

from gcrip.formats import ttdisp
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "ttdisp"


def _pack_order(head: bytes) -> str | None:
    if head[:4] == b"zV4\x12":
        return "<"
    if head[:4] == b"\x12\x34\x56\x7a":
        return ">"
    return None


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith((".fpk", ".cpk")) and _pack_order(head) is not None


def expand(data: bytes) -> list[tuple[str, bytes]]:
    order = _pack_order(data[:4])
    if order is None:
        return []
    count = struct.unpack_from(order + "I", data, 4)[0]
    out = []
    for i in range(min(count, 65536)):
        e = 0x18 + i * 28
        if e + 28 > len(data):
            break
        name_off, off, size = struct.unpack_from(order + "3I", data, e)
        if name_off >= len(data) or off + size > len(data) or size == 0:
            continue
        z = data.find(b"\0", name_off)
        name = data[name_off : z if z >= 0 else len(data)].decode("latin-1", "replace")
        name = name.replace("\\", "/").rsplit("/", 1)[-1] or f"member{i:04d}"
        out.append((name, data[off : off + size]))
    return out


def _flat_normals(m: ttdisp.Mesh) -> np.ndarray:
    """Per-vertex normals averaged from the faces (meshes without a normal array)."""
    pos, tri = m.positions, m.indices.reshape(-1, 3)
    fn = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
    out = np.zeros_like(pos)
    for k in range(3):
        np.add.at(out, tri[:, k], fn)
    ln = np.linalg.norm(out, axis=1, keepdims=True)
    return (out / np.where(ln > 0, ln, 1)).astype(np.float32)


def _quat(m: np.ndarray) -> tuple[float, float, float, float]:
    """(x, y, z, w) of a column-vector rotation matrix."""
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        return (
            float((m[2, 1] - m[1, 2]) / s),
            float((m[0, 2] - m[2, 0]) / s),
            float((m[1, 0] - m[0, 1]) / s),
            float(s / 4),
        )
    i = int(np.argmax(np.diagonal(m)))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = np.sqrt(1.0 + m[i, i] - m[j, j] - m[k, k]) * 2
    q = [0.0, 0.0, 0.0, 0.0]
    q[i] = s / 4
    q[j] = (m[j, i] + m[i, j]) / s
    q[k] = (m[k, i] + m[i, k]) / s
    q[3] = (m[k, j] - m[j, k]) / s
    return (float(q[0]), float(q[1]), float(q[2]), float(q[3]))


def _joints(bones: list[ttdisp.Bone]) -> list[Joint]:
    out = []
    for b in bones:
        world = b.bind.astype(np.float64)
        local = (
            world @ np.linalg.inv(bones[b.parent].bind.astype(np.float64))
            if b.parent >= 0
            else world
        )
        rot = local[:3, :3].T  # row-vector -> column-vector
        scale = np.linalg.norm(rot, axis=0)
        scale = np.where(scale > 0, scale, 1.0)
        out.append(
            Joint(
                name=b.name,
                parent=b.parent if b.parent >= 0 else None,
                translation=tuple(float(x) for x in local[3, :3]),
                rotation=_quat(rot / scale),
                scale=tuple(float(x) for x in scale),
            )
        )
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    if low.endswith(".csc"):
        return ttdisp.is_csc(head)
    if low.endswith(".chg"):
        return ttdisp.is_chg(head, size)
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = ttdisp.parse(data)
    if not model.meshes:
        return []
    scene = Scene(name=posixpath.basename(path).rsplit(".", 1)[0])
    if model.bones:
        scene.joints = _joints(model.bones)
    mats: dict[int, int] = {}
    groups: dict[int, list[ttdisp.Mesh]] = {}
    for m in model.meshes:
        if m.material not in mats:
            tex = None
            mat = model.materials[m.material] if 0 <= m.material < len(model.materials) else None
            if mat is not None and 0 <= mat.texture < len(model.textures):
                t = model.textures[mat.texture]
                if t.rgba is not None:
                    tex = f"tex{mat.texture:03d}"
                    scene.textures.setdefault(tex, t.rgba)
            diffuse = mat.diffuse if mat is not None else (1.0, 1.0, 1.0)
            alpha = bool(tex) and bool(np.any(scene.textures[tex][..., 3] < 255))
            scene.materials.append(
                MaterialDef(
                    name=tex or f"mat{max(m.material, 0):03d}",
                    texture=tex,
                    base_color=(*diffuse, 1.0),
                    alpha_blend=alpha,
                    double_sided=True,
                )
            )
            mats[m.material] = len(scene.materials) - 1
        groups.setdefault(mats[m.material], []).append(m)
    for mi, meshes in groups.items():
        base = 0
        idx = []
        for m in meshes:
            idx.append(m.indices + base)
            base += len(m.positions)
        any_nrm = any(m.normals is not None for m in meshes)
        any_uv = any(m.uvs is not None for m in meshes)
        any_col = any(m.colors is not None for m in meshes)
        nrm = uv = col = None
        if any_nrm:
            nrm = np.concatenate(
                [m.normals if m.normals is not None else _flat_normals(m) for m in meshes]
            )
        if any_uv:
            uv = np.concatenate(
                [
                    m.uvs if m.uvs is not None else np.zeros((len(m.positions), 2), np.float32)
                    for m in meshes
                ]
            )
        if any_col:
            col = np.concatenate(
                [
                    m.colors if m.colors is not None else np.ones((len(m.positions), 4), np.float32)
                    for m in meshes
                ]
            )
        joints = weights = None
        if model.bones:
            nv = sum(len(m.positions) for m in meshes)
            joints = np.zeros((nv, 4), np.uint16)
            weights = np.zeros((nv, 4), np.float32)
            weights[:, 0] = 1.0
            joints[:, 0] = np.concatenate(
                [np.full(len(m.positions), max(m.joint, 0), np.uint16) for m in meshes]
            )
        scene.primitives.append(
            Primitive(
                material=mi,
                positions=np.concatenate([m.positions for m in meshes]),
                indices=np.concatenate(idx).astype(np.uint32),
                normals=nrm,
                uvs=uv,
                colors=col,
                joints=joints,
                weights=weights,
            )
        )
    scene.extras = {
        "format": "tt-disp",
        "meshes": len(model.meshes),
        "materials": len(model.materials),
        "textures": len(model.textures),
        "bones": len(model.bones),
        "skipped_draws": model.skipped,
    }
    return [scene]
