"""EA Sports EBO geometry (NHL 2005/06, NBA Live 2005/06, FIFA 05, 2006 FIFA World Cup,
UEFA Champions League): the ``.ebo`` objects inside EA BIG/VIV archives
(gcrip.formats.ebo).  One Scene per file; textures are not linked yet (the Material
imports name them - ``gTexture_RMRuntime`` - but the binding lives in the game code)."""

from __future__ import annotations

import os

from gcrip.formats import ebo
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "ebo"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".ebo") and ebo.is_ebo(head) and size >= 256


def extract(data: bytes, path: str, src) -> list[Scene]:
    obj = ebo.parse(data)
    meshes = ebo.geometry(obj)
    if not meshes:
        return []
    stem = os.path.basename(path)[:-4]
    scene = Scene(name=stem)
    for m in meshes:
        scene.materials.append(MaterialDef(name=m.name, texture=None, double_sided=True))
        scene.primitives.append(
            Primitive(
                material=len(scene.materials) - 1,
                positions=m.positions,
                indices=m.indices,
                normals=m.normals,
                uvs=m.uvs,
                colors=m.colors,
            )
        )
    scene.extras = {
        "format": "ebo",
        "version": obj.version,
        "exports": [f"{e.type} {e.name}" for e in obj.exports[:16]],
        "meshes": len(meshes),
    }
    return [scene]
