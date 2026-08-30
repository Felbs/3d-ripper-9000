"""``GCT`` textures (gcrip.formats.gct): Darkened Skye keeps 4,340 of them.  Textures-only
Scenes named after the file."""

from __future__ import annotations

import posixpath

from gcrip.formats import gct
from ripcore.scene import Scene

NAME = "gct"


def detect(path: str, head: bytes, size: int) -> bool:
    return gct.is_gct(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = gct.decode(data)
    if rgba is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "texture"
    scene = Scene(name=stem)
    scene.textures[stem] = rgba
    scene.extras = {"textures_only": True, "format": "gct"}
    return [scene]
