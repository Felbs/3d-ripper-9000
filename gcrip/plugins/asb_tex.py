"""Acclaim ``TBLOCKTEX`` texture blocks (gcrip.formats.asb_tex): the All-Star Baseball discs
keep every texture in them.  One textures-only Scene a block, each image under its own name."""

from __future__ import annotations

import posixpath

from gcrip.formats import asb_tex
from ripcore.scene import Scene

NAME = "asb_tex"


def detect(path: str, head: bytes, size: int) -> bool:
    return asb_tex.is_tblocktex(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = asb_tex.images(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "tex"
    scene = Scene(name=stem)
    seen: dict[str, int] = {}
    for image in found:
        rgba = asb_tex.decode(data, image)
        if rgba is None:
            continue
        name = image.name
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:
            name = f"{name}_{n:03d}"
        scene.textures[name] = rgba
    if not scene.textures:
        return []
    scene.extras = {"textures_only": True, "format": "asb_tex", "images": len(scene.textures)}
    return [scene]
