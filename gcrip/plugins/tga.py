"""Truevision ``TGA`` images (gcrip.formats.tga): Splinter Cell Chaos Theory / Double
Agent ship hundreds of loading screens and menu plates as loose ``.tga``.  One
textures-only Scene an image.  Claiming them is also what keeps the ``gx`` fallback off
their pixel data - unclaimed, they scanned as 51 noise meshes a disc (quality audit,
GCJE41).

TGA has no magic, so detect() wants both the ``.tga`` name and ``tga.claimable`` (the
strict header + size arithmetic); the lenient ``tga.decode`` stays shared with the
RenderWare loose-texture binding and Kashmir's pictures.  Kashmir's GameCube-repacked
".tga" (``RPMOC3S`` at +1) fails the sniff and stays with its own reader.
"""

from __future__ import annotations

import posixpath

from gcrip.formats import tga
from ripcore.scene import Scene

NAME = "tga"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".tga") and tga.claimable(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    try:
        rgba = tga.decode(data)
    except tga.TgaError:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "image"
    scene = Scene(name=stem)
    scene.textures[stem] = rgba
    scene.extras = {"textures_only": True, "format": "tga"}
    return [scene]
