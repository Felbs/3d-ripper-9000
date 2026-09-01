"""Warthog ``.bmsh`` meshes (gcrip.formats.wart_bmsh) - GX display lists and indexed vertex
arrays from inside a ``WART3.00`` ``.hog``.  One Scene a member, one Primitive a sub-mesh."""

from __future__ import annotations

import posixpath

from gcrip.formats import wart_bmsh
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "wart_bmsh"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".bmsh") and wart_bmsh.is_bmsh(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    mesh = wart_bmsh.parse(data)
    if mesh is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "mesh"
    scene = Scene(name=stem)
    for i, part in enumerate(mesh.parts):
        material = MaterialDef(f"{stem}_{i}", None)
        scene.materials.append(material)
        scene.primitives.append(
            Primitive(
                material=material.name,
                positions=part.positions,
                indices=part.indices,
                uvs=part.uvs,
            )
        )
    scene.extras = {
        "format": "wart_bmsh",
        "parts": len(mesh.parts),
        "triangles": sum(len(p.indices) for p in mesh.parts),
    }
    return [scene]
