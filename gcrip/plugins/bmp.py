"""Windows ``BMP`` images (gcrip.formats.bmp), shipped loose on a dozen discs that produced
nothing else.  One textures-only Scene an image."""

from __future__ import annotations

import posixpath

from gcrip.formats import bmp
from ripcore.scene import Scene

NAME = "bmp"


def detect(path: str, head: bytes, size: int) -> bool:
    return bmp.is_bmp(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = bmp.decode(data)
    if rgba is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "bitmap"
    scene = Scene(name=stem)
    scene.textures[stem] = rgba
    scene.extras = {"textures_only": True, "format": "bmp"}
    return [scene]
