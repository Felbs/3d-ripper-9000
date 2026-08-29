"""Krome Studios MDL2 models (``.gmd`` inside RKV archives: Ty the Tasmanian Tiger).  One
Scene per model with a Primitive per subobject mesh; textures are the ``.gtx`` files named
by each mesh's material (gcrip.formats.mdl2)."""

from __future__ import annotations

import contextlib
import posixpath

import numpy as np

from gcrip.formats import mdl2
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "mdl2"

_INDEX_ATTR = "_mdl2_gtx_index"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".gmd") and mdl2.is_mdl2(head)


def _gtx_index(src) -> dict[str, str]:
    """lower-case texture stem -> manifest path of every .gtx the source knows (cached)."""
    cache = getattr(src, _INDEX_ATTR, None)
    if cache is not None:
        return cache
    index: dict[str, str] = {}
    for p in getattr(src, "by_path", {}) or {}:
        if p.lower().endswith(".gtx"):
            index.setdefault(posixpath.basename(p)[:-4].lower(), p)
    with contextlib.suppress(Exception):
        setattr(src, _INDEX_ATTR, index)
    return index


def _texture(src, scene: Scene, lookup: dict[str, str], material: str) -> str | None:
    key = material.lower()
    if key in scene.textures:
        return key
    path = lookup.get(key)
    if not path:
        return None
    try:
        rgba = mdl2.gtx_decode(src.get(path))
    except Exception as e:  # noqa: BLE001
        scene.warnings.append(f"{path}: {e}")
        return None
    if rgba is None:
        return None
    scene.textures[key] = rgba
    return key


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = mdl2.parse(data, posixpath.basename(path)[:-4])
    if not model.parts:
        return []
    lookup = _gtx_index(src)
    scene = Scene(name=model.name)
    scene.joints = [
        Joint(
            f"bone{i:02d}",
            None,
            (float(x), float(y), float(z)),
            (0.0, 0.0, 0.0, 1.0),
            (1.0, 1.0, 1.0),
        )
        for i, (x, y, z) in enumerate(model.bones)
    ]
    mats: dict[str, int] = {}
    for part in model.parts:
        if part.material not in mats:
            tex = _texture(src, scene, lookup, part.material)
            alpha = bool(tex) and bool(np.any(scene.textures[tex][..., 3] < 255))
            scene.materials.append(
                MaterialDef(name=part.material, texture=tex, alpha_blend=alpha, double_sided=True)
            )
            mats[part.material] = len(scene.materials) - 1
        scene.primitives.append(
            Primitive(
                material=mats[part.material],
                positions=part.positions,
                indices=part.indices,
                normals=part.normals,
                uvs=part.uvs,
                colors=part.colors,
                joints=part.joints if scene.joints else None,
                weights=part.weights if scene.joints else None,
            )
        )
    scene.extras = {
        "format": "mdl2",
        "subobjects": sorted({p.name for p in model.parts}),
        "bones": len(model.bones),
        "skeleton": "bone positions only - hierarchy lives in the sibling .bad text file",
    }
    return [scene]
