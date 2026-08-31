"""EA ``TXG`` texture groups (gcrip.formats.ea_txg) - the ``txf`` members of the Tiger Woods
``SHOC`` archives.  One textures-only Scene a group, an image per texture."""

from __future__ import annotations

import posixpath

from gcrip.formats import ea_txg
from ripcore.scene import MaterialDef, Scene

NAME = "ea_txg"


def detect(path: str, head: bytes, size: int) -> bool:
    return ea_txg.is_txg(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = ea_txg.textures(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "txg"
    scene = Scene(name=stem)
    for tex in found:
        rgba = ea_txg.decode(data, tex)
        if rgba is None:
            continue
        key = tex.name if tex.name not in scene.textures else f"{tex.name}_{tex.offset}"
        scene.textures[key] = rgba
    if not scene.textures:
        return []
    # a texture no material names is dropped at export - see docs/formats/textures-only-scenes.md
    scene.materials = [MaterialDef(name=k, texture=k) for k in scene.textures]
    scene.extras = {"textures_only": True, "format": "ea_txg", "count": len(scene.textures)}
    return [scene]
