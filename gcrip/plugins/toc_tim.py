"""``TIM`` textures (gcrip.formats.toc_tim): the members of Spawn: Armageddon's ``TOC``
archives.  One textures-only Scene an image."""

from __future__ import annotations

import posixpath

from gcrip.formats import toc_tim
from ripcore.scene import Scene

NAME = "toc_tim"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.upper().endswith(".TIM") and toc_tim.is_tim(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = toc_tim.decode(data)
    if rgba is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "texture"
    scene = Scene(name=stem)
    scene.textures[stem] = rgba
    scene.extras = {"textures_only": True, "format": "toc_tim"}
    return [scene]
