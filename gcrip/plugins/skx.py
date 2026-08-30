"""Darkened Skye ``SKX`` models (gcrip.formats.skx), the members of its ``PAK`` archives
(gcrip.plugins.skye_pak).  One primitive a mesh directory; the sibling ``GCT`` textures ship
separately and are not bound yet."""

from __future__ import annotations

import posixpath

from gcrip.formats import skx
from ripcore.scene import Primitive, Scene

NAME = "skx"


def detect(path: str, head: bytes, size: int) -> bool:
    return skx.is_skx(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = skx.meshes(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "skx"
    scene = Scene(name=stem)
    for mesh in found:
        scene.primitives.append(
            Primitive(
                material=-1,
                positions=mesh.positions,
                indices=mesh.indices,
                normals=mesh.normals,
                uvs=mesh.uvs,
            )
        )
    scene.extras = {"format": "skx", "meshes": len(found)}
    return [scene]
