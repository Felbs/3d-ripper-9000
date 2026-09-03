"""Edge of Reality textures - ``TXFL`` members (``Textures/<hash>.bin`` out of ``textures.arc``)
and dataset entries (``.eort``) - as standalone textures."""

from __future__ import annotations

import posixpath

from gcrip.formats import edge_model
from ripcore.scene import MaterialDef, Scene

NAME = "edge_tex"


def detect(path: str, head: bytes, size: int) -> bool:
    lower = path.lower()
    if lower.endswith(".eort"):
        return size > 28
    return lower.endswith(".bin") and size > 52 and edge_model.is_texture(head[:8])


def extract(data: bytes, path: str, src) -> list[Scene]:
    tex = edge_model.any_texture(data)
    name = tex.name or posixpath.basename(path).split(".")[0]
    scene = Scene(name=name)
    scene.textures[name] = tex.rgba
    scene.materials.append(MaterialDef(name=name, texture=name))
    scene.extras = {"textures_only": True}
    return [scene]
