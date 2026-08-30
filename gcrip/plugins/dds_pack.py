"""Byte-swapped DDS texture packs (gcrip.formats.dds_pack): Home Run King keeps 236 of them in
``data.afs``, each a run of concatenated big-endian DXT1 files.  Emitted as textures-only
Scenes."""

from __future__ import annotations

import posixpath

from gcrip.formats import dds_pack
from ripcore.scene import Scene

NAME = "dds_pack"


def detect(path: str, head: bytes, size: int) -> bool:
    return dds_pack.is_pack(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = dds_pack.entries(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "textures"
    scene = Scene(name=stem)
    for i, entry in enumerate(found):
        try:
            rgba = dds_pack.decode(data, entry)
        except Exception:  # noqa: BLE001 - one bad texture must not lose the rest
            continue
        scene.textures[f"{stem}_{i:03d}"] = rgba
    if not scene.textures:
        return []
    scene.extras = {"textures_only": True, "format": "dds_pack", "count": len(scene.textures)}
    return [scene]
