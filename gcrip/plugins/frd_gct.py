"""Free Radical ``gct`` textures (gcrip.formats.frd_gct): the members of the ``P*CK`` archives
on TimeSplitters 2, TimeSplitters: Future Perfect and Second Sight.  Textures-only Scenes named
after the member."""

from __future__ import annotations

import posixpath

from gcrip.formats import frd_gct
from ripcore.scene import Scene

NAME = "frd_gct"


def detect(path: str, head: bytes, size: int) -> bool:
    # detect gets 64 bytes; the pixel-length check needs the whole member, so extract does it
    return path.lower().endswith(".gct") and frd_gct.looks_like(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = frd_gct.decode(data)
    if rgba is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "texture"
    scene = Scene(name=stem)
    scene.textures[stem] = rgba
    scene.extras = {"textures_only": True, "format": "frd_gct"}
    return [scene]
