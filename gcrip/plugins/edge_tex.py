"""Edge of Reality ``TXFL`` members (``Textures/<hash>.bin`` out of ``textures.arc``) as
standalone textures."""

from __future__ import annotations

import posixpath

from gcrip.formats import edge_model
from ripcore.scene import MaterialDef, Scene

NAME = "edge_tex"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".bin") and size > 52 and edge_model.is_texture(head[:8])


def extract(data: bytes, path: str, src) -> list[Scene]:
    tex = edge_model.parse_texture(data)
    name = tex.name or posixpath.basename(path).split(".")[0]
    scene = Scene(name=name)
    scene.textures[name] = tex.rgba
    scene.materials.append(MaterialDef(name=name, texture=name))
    scene.extras = {"textures_only": True}
    return [scene]
