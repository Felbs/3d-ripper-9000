"""``AGG`` meshes (gcrip.formats.agg): High Voltage ships its geometry as text, and Hunter:
The Reckoning keeps 2,114 of them inside its ``LJAM`` archives.  One primitive a
``MeshComponent``; the material name survives, but binding it to a texture needs the sibling
``AGM`` / ``AGD`` material text, which is not read yet."""

from __future__ import annotations

import posixpath

from gcrip.formats import agg
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "agg"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".agg") and agg.is_agg(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = agg.parts(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "agg"
    scene = Scene(name=stem)
    materials: dict[str, int] = {}
    for part in found:
        index = -1
        if part.material:
            if part.material not in materials:
                materials[part.material] = len(scene.materials)
                scene.materials.append(MaterialDef(name=part.material, texture=None))
            index = materials[part.material]
        scene.primitives.append(
            Primitive(
                material=index,
                positions=part.positions,
                indices=part.indices,
                normals=part.normals,
                uvs=part.uvs,
                colors=part.colors,
            )
        )
    scene.extras = {"format": "agg", "parts": len(found)}
    return [scene]
