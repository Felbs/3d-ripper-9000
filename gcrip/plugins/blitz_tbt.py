"""Blitz Games texture resources (``.tbt`` members of ``.gcp`` packs) as standalone textures."""

from __future__ import annotations

import posixpath

from gcrip.formats import blitz_actor
from ripcore.scene import MaterialDef, Scene

NAME = "blitz_tbt"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".tbt") and size >= 160 and len(head) > 6 and head[6] == 0


def extract(data: bytes, path: str, src) -> list[Scene]:
    name = posixpath.basename(path).split(".")[0]
    try:
        rgba = blitz_actor.texture(data)
    except blitz_actor.TextureError:
        return []
    scene = Scene(name=name)
    scene.textures[name] = rgba
    scene.materials.append(MaterialDef(name=name, texture=name))
    scene.extras = {"textures_only": True}
    return [scene]
