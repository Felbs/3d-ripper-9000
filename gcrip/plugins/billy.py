"""Billy Hatcher and the Giant Egg: ``.prd`` packages (container, gcrip.formats.prd) and
``.arc`` Ginja models with their embedded GVM textures (gcrip.formats.billy)."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import billy, prd
from ripcore.scene import Scene

NAME = "billy"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".prd") and prd.is_prd(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    try:
        u = prd.unpack(data)
    except Exception:  # noqa: BLE001
        return []
    return [(m.name, u[m.offset : m.offset + m.size]) for m in prd.members(u)]


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".arc") and billy.is_arc(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scenes, textures = billy.scenes(data, name)
    rgba = {t.name: t.rgba for t in textures if t.rgba is not None}
    if not scenes:
        if not rgba:
            return []
        scene = Scene(name=name)
        scene.textures.update(rgba)
        scene.extras = {"format": "billy-arc", "textures_only": True}
        return [scene]
    for scene in scenes:
        for m in scene.materials:
            if m.texture and m.texture in rgba:
                scene.textures.setdefault(m.texture, rgba[m.texture])
                m.alpha_blend = m.alpha_blend or bool(np.any(rgba[m.texture][..., 3] < 255))
            elif m.texture:
                m.texture = None
    return scenes
