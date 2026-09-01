"""Yuke's ``YOBJ`` meshes (gcrip.formats.yukes_yobj) - the ``.ymg`` files of the WWE discs.
One Scene a file, one primitive a mesh."""

from __future__ import annotations

import posixpath

from gcrip.formats import yukes_yobj
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "yukes_yobj"


def detect(path: str, head: bytes, size: int) -> bool:
    return yukes_yobj.is_yobj(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = yukes_yobj.meshes(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "model"
    scene = Scene(name=stem)
    for i, mesh in enumerate(found):
        scene.materials.append(MaterialDef(name=f"{stem}_{i:04d}", texture=None))
        scene.primitives.append(
            Primitive(
                material=len(scene.materials) - 1,
                positions=mesh.positions,
                indices=mesh.indices,
                normals=mesh.normals,
            )
        )
    scene.extras = {"format": "yukes_yobj", "meshes": len(found)}
    return [scene]
