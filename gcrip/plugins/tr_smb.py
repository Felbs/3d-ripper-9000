"""4x4 Evo 2's ``.SMB`` models (gcrip.formats.tr_smb): one Scene a file, a primitive a part,
textured by the material's ``.TIF`` / ``.RAW`` from the POD archives (``.TEX`` layout, read
by gcrip.formats.tr_tex)."""

from __future__ import annotations

import contextlib
import posixpath

from gcrip.formats import tr_smb, tr_tex
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "tr_smb"
_INDEX_ATTR = "_tr_smb_textures"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".smb") and tr_smb.is_smb(head, size)


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
    model = tr_smb.parse(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    scene.warnings += model.warnings
    slots: dict[str, int] = {}
    for part in model.parts:
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
        "format": "tr_smb",
        "parts": [p.name for p in model.parts],
        "frames": max(p.frames for p in model.parts),
    }
    return [scene]
