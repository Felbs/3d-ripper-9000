"""Warthog `.btga` textures (gcrip.formats.wart_btga) - CMPR and IA4 images from inside a
``WART3.00`` `.hog`.  One textures-only Scene an image, top mip only."""

from __future__ import annotations

import posixpath

from gcrip.formats import gx_texture as gx
from gcrip.formats import wart_btga
from ripcore.scene import Scene

NAME = "wart_btga"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".btga") and wart_btga.looks_like(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    tex = wart_btga.texture(data)
    if tex is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "texture"
    scene = Scene(name=stem)
    scene.textures[stem] = tex.rgba
    scene.extras = {
        "textures_only": True,
        "format": "wart_btga",
        "size": f"{tex.width}x{tex.height}",
        "gx_format": gx.FORMAT_NAMES.get(tex.fmt, tex.fmt),
        "levels": tex.levels,
    }
    return [scene]
