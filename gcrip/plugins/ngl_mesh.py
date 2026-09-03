"""Treyarch NGL ``GCNM`` mesh files (``.gcmesh`` out of ``amalga_gc.pak``) - one Scene a
file: static props, city pieces and CPU-skinned characters with their bind-pose skeleton.
Textures bind through the material's texture-name hash: the file's own material records,
then the pack's ``.gcmat`` files, then any ``.gct`` under the same pack, then the whole
archive."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import hsd, ngl_gc
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "ngl_mesh"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".gcmesh") and ngl_gc.is_gcnm(head[:20], size)


class _Resources:
    """Per-source index: texture hash -> member path, material files parsed per pack."""

    def __init__(self, src) -> None:
        self.src = src
        self.textures: dict[int, list[str]] | None = None
        self.materials: dict[str, dict[str, ngl_gc.Material]] = {}
        self.cache: dict[str, np.ndarray | None] = {}

    def _index(self) -> None:
        if self.textures is not None:
            return
        self.textures = {}
        for p in self.src.by_path:
            if p.lower().endswith((".gct", ".ifl")):
                try:
                    h = int(posixpath.basename(p).split("_")[0].split(".")[0], 16)
                except ValueError:
                    continue
                self.textures.setdefault(h, []).append(p)

    def pack_materials(self, folder: str) -> dict[str, ngl_gc.Material]:
        if folder not in self.materials:
            table: dict[str, ngl_gc.Material] = {}
            for p in self.src.by_path:
                if p.lower().endswith(".gcmat") and posixpath.dirname(p) == folder:
                    try:
                        mf = ngl_gc.parse_gcnm(self.src.get(p))
                    except Exception:  # noqa: BLE001 - one bad material file, the rest bind
                        continue
                    for k, m in mf.materials.items():
                        table.setdefault(k, m)
            self.materials[folder] = table
        return self.materials[folder]

    def texture_path(self, h: int, folder: str) -> str | None:
        self._index()
        assert self.textures is not None
        paths = self.textures.get(h)
        if not paths:
            return None
        for p in paths:
            if posixpath.dirname(p) == folder:
                return p
        return paths[0]

    def image(self, path: str, depth: int = 0) -> np.ndarray | None:
        if path not in self.cache:
            img = None
            try:
                blob = self.src.get(path)
                if path.lower().endswith(".ifl"):
                    # an animated texture: its first frame, by name hash
                    frames = ngl_gc.ifl_frames(blob)
                    frame = (
                        self.texture_path(ngl_gc.name_hash(frames[0]), posixpath.dirname(path))
                        if frames
                        else None
                    )
                    if frame and depth < 2:
                        img = self.image(frame, depth + 1)
                else:
                    img = ngl_gc.decode_gct(blob)
            except Exception:  # noqa: BLE001 - a bad texture leaves the material bare
                img = None
            if len(self.cache) > 256:
                self.cache.clear()
            self.cache[path] = img
        return self.cache[path]


_cache: dict[int, _Resources] = {}


def _resources(src) -> _Resources | None:
    if src is None or not hasattr(src, "by_path"):
        return None
    key = id(src)
    t = _cache.get(key)
    if t is None or t.src is not src:
        _cache.clear()
        t = _cache[key] = _Resources(src)
    return t


def _joints(bones: np.ndarray) -> list[Joint]:
    """Bind matrices (row vectors, translation in the last row) as a flat skeleton."""
    out = []
    for i, m in enumerate(bones):
        r = m[:3, :3].T.astype(np.float64)
        scale = np.linalg.norm(r, axis=0)
        scale[scale == 0] = 1.0
        q = hsd.quat_from_matrix(r / scale) if np.isfinite(r).all() else (0.0, 0.0, 0.0, 1.0)
        if not np.isfinite(q).all():
            q = (0.0, 0.0, 0.0, 1.0)
        out.append(
            Joint(
                f"bone{i}",
                None,
                tuple(float(x) for x in m[3, :3]),
                tuple(float(x) for x in q),
                tuple(float(x) for x in scale),
            )
        )
    return out


def extract(data: bytes, path: str, src) -> list[Scene]:
    mf = ngl_gc.parse_gcnm(data)
    stem = posixpath.basename(path).split(".")[0]
    folder = posixpath.dirname(path)
    res = _resources(src)
    scene = Scene(name=stem)
    scene.warnings += mf.warnings
    pack_mats = res.pack_materials(folder) if res is not None else {}
    materials: dict[str, int] = {}
    missing: list[str] = []
    joint_base = 0
    for mesh in mf.meshes:
        skinned = mesh.bones is not None and any(s.joints is not None for s in mesh.sections)
        if skinned:
            joint_base = len(scene.joints)
            scene.joints += _joints(mesh.bones)
        for sec in mesh.sections:
            key = sec.material.lower()
            if key not in materials:
                mat = mf.materials.get(key) or pack_mats.get(key)
                tex_key = None
                if res is not None and mat is not None:
                    for h, name in mat.textures:
                        p = res.texture_path(h, folder)
                        img = res.image(p) if p else None
                        if img is not None:
                            tex_key = name or f"{h:08x}"
                            scene.textures.setdefault(tex_key, img)
                            break
                if tex_key is None and mat is not None and mat.textures:
                    missing.append(mat.textures[0][1])
                materials[key] = len(scene.materials)
                scene.materials.append(MaterialDef(name=sec.material, texture=tex_key))
            joints = weights = None
            if sec.joints is not None and skinned:
                joints = sec.joints.astype(np.uint16) + np.uint16(joint_base)
                joints[sec.weights == 0] = 0
                weights = sec.weights
            normals = sec.normals
            if normals is not None:
                length = np.linalg.norm(normals, axis=1, keepdims=True)
                normals = np.where(
                    length > 1e-6, normals / np.maximum(length, 1e-6), normals
                ).astype(np.float32)
            scene.primitives.append(
                Primitive(
                    material=materials[key],
                    positions=np.ascontiguousarray(sec.positions, dtype=np.float32),
                    indices=sec.triangles.reshape(-1).astype(np.uint32),
                    normals=normals,
                    uvs=None
                    if sec.uvs is None
                    else np.ascontiguousarray(sec.uvs, dtype=np.float32),
                    colors=None
                    if sec.colors is None
                    else np.ascontiguousarray(sec.colors, dtype=np.uint8),
                    joints=joints,
                    weights=weights,
                )
            )
    if missing:
        scene.warnings.append(
            f"{len(missing)} textures not found: {', '.join(sorted(set(missing))[:8])}"
        )
    scene.extras["meshes"] = [m.name for m in mf.meshes]
    return [scene] if scene.primitives else []
