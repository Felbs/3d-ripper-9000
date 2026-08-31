"""``PNG`` images (gcrip.formats.png).  gcrip recognised the magic but never decoded one, so a
PNG handed out by a container produced nothing.  One textures-only Scene an image."""

from __future__ import annotations

import posixpath

from gcrip.formats import png
from ripcore.scene import Scene

NAME = "png"


def detect(path: str, head: bytes, size: int) -> bool:
    return png.is_png(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = png.decode(data)
    if rgba is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "image"
    scene = Scene(name=stem)
    scene.textures[stem] = rgba
    scene.extras = {"textures_only": True, "format": "png"}
    return [scene]
