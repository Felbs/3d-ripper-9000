"""Sony ``TIM2`` textures (gcrip.formats.tim2) - Capcom's GameCube ports keep them from the
PS2: Auto Modellista and Capcom vs SNK 2 EO carry them inside AFS members.  One textures-only
Scene, an image per picture."""

from __future__ import annotations

import posixpath

from gcrip.formats import tim2
from ripcore.scene import Scene

NAME = "tim2"
INSIDE_AFS = ".afs/"


def detect(path: str, head: bytes, size: int) -> bool:
    return tim2.is_tim2(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "texture"
    scene = Scene(name=stem)
    for i, pic in enumerate(tim2.pictures(data)):
        rgba = tim2.decode(pic)
        if rgba is not None:
            scene.textures[f"{stem}_{i}" if i else stem] = rgba
    if not scene.textures:
        return []
    scene.extras = {"textures_only": True, "format": "tim2"}
    return [scene]


def is_container(name: str, head: bytes) -> bool:
    """Claims an AFS member that opens with an ascending offset table.

    It cannot check the magic those offsets point at: the first offset is very often exactly
    64, so on the 64 bytes ``classify`` sniffs the magic sits one byte out of reach, and
    ``expand`` has to do the real check.  That makes the shape test alone far too eager - on
    Auto Modellista it claims 50 members to find 7 real tables - so the claim is confined to
    where this structure has actually been seen, inside an AFS archive.  Requiring the
    ``0xffffffff`` terminator was tried instead and is wrong twice over: one real table of 16
    offsets does not carry one, and one member that does carry one holds no TIM2.

    A TIM2 lying loose anywhere else is still picked up by :func:`detect`, which can see the
    magic at offset zero.
    """
    return INSIDE_AFS in name.lower() and tim2.looks_like_table(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return [(f"{i}.tm2", data[a:b]) for i, (a, b) in enumerate(tim2.table(data))]
