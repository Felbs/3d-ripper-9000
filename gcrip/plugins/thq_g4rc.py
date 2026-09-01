"""THQ ``g4rc`` textures (gcrip.formats.thq_g4rc) - Avatar: The Last Airbender and Jimmy
Neutron: Attack of the Twonkies.

Two jobs: inflate the ``.rcb`` leaves of a ``.rad`` pack, which are plain zlib, and decode the
``g4rc`` objects that come out.  One textures-only Scene an image.
"""

from __future__ import annotations

import posixpath

from gcrip.formats import thq_g4rc
from ripcore.scene import Scene

NAME = "thq_g4rc"
SUFFIXES = (".rcb",)


def detect(path: str, head: bytes, size: int) -> bool:
    return thq_g4rc.is_g4rc(head)


def is_container(name: str, head: bytes) -> bool:
    """``rip.py`` passes the member's basename, never a path."""
    return name.lower().endswith(SUFFIXES) and thq_g4rc.is_rcb(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = thq_g4rc.inflate(data)
    if out is None:
        return []
    tag = out[:4]
    stem = tag.decode("latin-1") if tag.isalnum() else "member"
    return [(f"{stem}.bin", out)]


def extract(data: bytes, path: str, src) -> list[Scene]:
    tex = thq_g4rc.texture(data)
    if tex is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "texture"
    scene = Scene(name=stem)
    scene.textures[stem] = tex.rgba
    scene.extras = {
        "textures_only": True,
        "format": "thq_g4rc",
        "size": f"{tex.width}x{tex.height}",
        "levels": tex.levels,
    }
    return [scene]
