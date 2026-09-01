"""Pokemon Colosseum / XD textures (gcrip.formats.fsys_tex) - the image members of an ``FSYS``
archive.  One textures-only Scene an image."""

from __future__ import annotations

import posixpath

from gcrip.formats import fsys_tex
from ripcore.scene import Scene

NAME = "fsys_tex"


def detect(path: str, head: bytes, size: int) -> bool:
    return fsys_tex.looks_like(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    tex = fsys_tex.texture(data)
    if tex is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "texture"
    scene = Scene(name=stem)
    scene.textures[stem] = tex.rgba
    scene.extras = {
        "textures_only": True,
        "format": "fsys_tex",
        "size": f"{tex.width}x{tex.height}",
        "depth": tex.depth,
    }
    return [scene]
