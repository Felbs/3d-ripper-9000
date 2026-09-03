"""Terminal Reality ``.SMB`` models: 4x4 Evo 2's ``C3DModel`` version 1 (gcrip.formats.tr_smb)
and RoadKill's ``CModel`` version 6 (gcrip.formats.tr_cmodel, the layout its ``.smf`` share).
One Scene a file, a primitive a part, textured by the material's ``.TIF`` / ``.RAW`` from the
POD archives (``.TEX`` layout, read by gcrip.formats.tr_tex)."""

from __future__ import annotations

import contextlib
import posixpath

from gcrip.formats import tr_cmodel, tr_smb, tr_tex
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "tr_smb"
_INDEX_ATTR = "_tr_smb_textures"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".smb") and (
        tr_smb.is_smb(head, size) or tr_cmodel.is_cmodel(head, size)
    )


def _index(src) -> dict[str, list[str]]:
    """lower-case texture stem -> paths of .TIF / .RAW / .TEX members, built once."""
    index = getattr(src, _INDEX_ATTR, None)
    if index is not None:
        return index
    index = {}
    for p in getattr(src, "by_path", {}) or {}:
        low = p.lower()
        if low.endswith((".tif", ".raw", ".tex")):
            index.setdefault(low.rsplit("/", 1)[-1].rsplit(".", 1)[0], []).append(p)
    with contextlib.suppress(Exception):  # a source that cannot hold the cache still works
        setattr(src, _INDEX_ATTR, index)
    return index


def _texture(src, name: str, warnings: list[str]):
    if src is None or not hasattr(src, "by_path") or not name:
        return None
    stem = name.rsplit(".", 1)[0].lower()
    for p in sorted(_index(src).get(stem, []), key=len):
        try:
            rgba = tr_tex.decode(src.get(p))
        except Exception as e:  # noqa: BLE001 - try the next copy
            warnings.append(f"{p}: {e}")
            continue
        if rgba is not None:
            return rgba
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    if tr_cmodel.is_cmodel(data[:24], len(data)):
        model = tr_cmodel.parse(data)
        parts = model.objects
        fmt = "tr_cmodel"
    else:
        model = tr_smb.parse(data)
        parts = model.parts
        fmt = "tr_smb"
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    scene.warnings += model.warnings
    slots: dict[str, int] = {}
    for part in parts:
        key = part.material.lower()
        if key not in slots:
            tex = _texture(src, part.material, scene.warnings)
            tname = part.material.rsplit(".", 1)[0] if part.material else ""
            if tex is not None:
                scene.textures[tname] = tex
            slots[key] = len(scene.materials)
            scene.materials.append(
                MaterialDef(name=tname or stem, texture=tname if tex is not None else None)
            )
        scene.primitives.append(
            Primitive(
                material=slots[key],
                positions=part.positions,
                indices=part.indices,
                normals=part.normals,
                uvs=part.uvs,
            )
        )
    if not scene.primitives:
        return []  # legitimate: every part was refused, each with a warning above
    scene.extras = {
        "format": fmt,
        "parts": [p.name for p in parts],
        "frames": max(getattr(p, "frames", getattr(model, "frames", 1)) for p in parts),
    }
    return [scene]
