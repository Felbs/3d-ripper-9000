"""A2M's 2004-05 engine (Scooby-Doo! Unmasked, Scaler): the ``.ghr`` level archive as a
container and its ``.hgobj`` / ``.hgworld`` members as scenes (gcrip.formats.a2m_hg).
Textures come from the ``.htd`` dictionaries of the level folder (``gen/TEXDIC.htd`` beside
the archive first, then the language folders' ``LoadNTSC.htd`` / ``FONTDIC.htd``)."""

from __future__ import annotations

import contextlib
import posixpath

import numpy as np

from gcrip.formats import a2m_hg, hsd
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "a2m_hg"
_HTD_ATTR = "_a2m_htd_index"


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    if low.endswith(a2m_hg.OBJECT_EXT):
        return size > 64 and 0 < head[0] < 200
    return low.endswith(a2m_hg.WORLD_EXT) and size > 64


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".ghr") and a2m_hg.is_ghr(head, 1 << 31)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return a2m_hg.expand(data)


def _level_paths(src, path: str) -> list[str]:
    """Paths in the archive's folder and in the folders beside it (gen/ <-> EN/ <-> FR/)."""
    folder = posixpath.dirname(path)  # .../gen/LEVEL.ghr
    level = posixpath.dirname(posixpath.dirname(folder))  # .../LEVEL
    out = []
    for p in getattr(src, "by_path", {}) or {}:
        if p.startswith(level + "/") and p.lower().endswith(".htd"):
            out.append(p)
    out.sort(
        key=lambda p: (
            not p.startswith(posixpath.dirname(folder) + "/"),
            "texdic" not in p.lower(),
            len(p),
        )
    )
    return out


def _htd_index(src, path: str) -> dict[str, tuple[str, int]]:
    """upper-case texture name -> (.htd path, index) over the level's dictionaries."""
    cache = getattr(src, _HTD_ATTR, None)
    if cache is None:
        cache = {}
        with contextlib.suppress(Exception):
            setattr(src, _HTD_ATTR, cache)
    key = posixpath.dirname(posixpath.dirname(posixpath.dirname(path)))
    if key not in cache:
        index: dict[str, tuple[str, int]] = {}
        for p in _level_paths(src, path):
            with contextlib.suppress(Exception):
                for i, name in enumerate(a2m_hg.htd_names(src.get(p))):
                    index.setdefault(name.upper(), (p, i))
        cache[key] = index
    return cache[key]


class _Textures:
    def __init__(self, src, path: str):
        self.src = src
        self.index = _htd_index(src, path) if src is not None and hasattr(src, "by_path") else {}
        self.decoded: dict[str, list[a2m_hg.Texture]] = {}

    def get(self, name: str, warnings: list[str]) -> np.ndarray | None:
        hit = self.index.get(name.upper())
        if hit is None:
            return None
        p, i = hit
        if p not in self.decoded:
            try:
                self.decoded[p] = a2m_hg.parse_htd(self.src.get(p))
            except Exception as e:  # noqa: BLE001 - one bad dictionary, the others serve
                warnings.append(f"{p}: {e}")
                self.decoded[p] = []
        texs = self.decoded[p]
        if i < len(texs) and texs[i].name.upper() == name.upper():
            return texs[i].rgba
        return next((t.rgba for t in texs if t.name.upper() == name.upper()), None)


def _scene(model: a2m_hg.Model, textures: _Textures) -> Scene:
    scene = Scene(name=model.name)
    scene.warnings += model.warnings
    skinned = any(m.joints is not None for m in model.meshes) and model.bones
    if skinned:
        for k, b in enumerate(model.bones):
            r = b.matrix[:3, :3]
            scale = np.linalg.norm(r, axis=1)
            rot = r / np.where(scale > 0, scale, 1)[:, None]
            q = hsd.quat_from_matrix(rot.T)
            scene.joints.append(
                Joint(
                    f"bone_{k}",
                    b.parent if 0 <= b.parent < k else -1,
                    tuple(float(x) for x in b.matrix[3, :3]),
                    tuple(float(x) for x in q),
                    tuple(float(x) for x in scale),
                )
            )
    material_index: dict[int, int] = {}
    for m in model.meshes:
        if m.material not in material_index:
            mat = model.materials[m.material] if m.material < len(model.materials) else None
            key = None
            if mat is not None:
                for n in mat.textures:
                    img = textures.get(n, scene.warnings)
                    if img is not None:
                        key = n
                        scene.textures.setdefault(n, img)
                        break
            material_index[m.material] = len(scene.materials)
            scene.materials.append(
                MaterialDef(name=f"material_{m.material}", texture=key, double_sided=True)
            )
        joints = weights = None
        if skinned and m.joints is not None and m.weights is not None:
            joints = m.joints.astype(np.uint16)
            weights = m.weights.astype(np.float32)
        scene.primitives.append(
            Primitive(
                material=material_index[m.material],
                positions=m.positions,
                indices=m.triangles.reshape(-1).astype(np.uint32),
                normals=m.normals,
                uvs=m.uvs,
                colors=m.colors,
                joints=joints if scene.joints else None,
                weights=weights if scene.joints else None,
            )
        )
    if scene.primitives:
        scene.extras = {"format": "a2m_hg", "bones": len(model.bones), "lods": model.lods}
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    textures = _Textures(src, path)
    if path.lower().endswith(a2m_hg.WORLD_EXT):
        model = a2m_hg.parse_world(data)
    else:
        model = a2m_hg.parse_object(data)
    scene = _scene(model, textures)
    if not scene.primitives:
        if model.warnings:
            raise a2m_hg.HgError("; ".join(model.warnings[:3]))
        return []  # legitimate: a placeholder object with no surfaces
    return [scene]
