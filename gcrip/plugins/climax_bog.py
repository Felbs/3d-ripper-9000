"""Climax ``.bog`` textures (gcrip.formats.climax_bog): the art inside the ``.bad`` archives
of ATV: Quad Power Racing 2, Hot Wheels World Race and The Italian Job, as textures-only
Scenes."""

from __future__ import annotations

import posixpath

from gcrip.formats import climax_bog
from ripcore.scene import Scene

NAME = "climax_bog"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".bog") and climax_bog.is_bog(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = climax_bog.decode(data)
    if rgba is None:
        return []  # legitimate: a header the format table does not cover, or a short file
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=name)
    scene.textures[name] = rgba
    scene.extras = {"textures_only": True, "format": "climax_bog"}
    return [scene]
