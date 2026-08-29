"""Traveller's Tales NU2 files (LEGO Star Wars ``.gsc`` / ``.csc`` and other early TT discs;
gcrip.formats.nu2): one Scene per file holding every vertex-stream mesh as a primitive.
Materials are not decoded yet, so the meshes carry UVs and normals but no textures."""

from __future__ import annotations

import posixpath

from gcrip.formats import nu2
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "nu2"


def detect(path: str, head: bytes, size: int) -> bool:
    # LSW2 / Narnia files share the magic but are big-endian with reversed tags (LBTN at
    # 0x10) and belong to plugins.ttdisp
    return size > 64 and nu2.is_nu2(head) and head[0x10:0x14] != b"LBTN"


def extract(data: bytes, path: str, src) -> list[Scene]:
    meshes = nu2.meshes(data)
    if not meshes:
        return []
    scene = Scene(name=posixpath.basename(path).rsplit(".", 1)[0])
    scene.materials.append(MaterialDef(name="nu2", texture=None, double_sided=True))
    for m in meshes:
        scene.primitives.append(
            Primitive(
                material=0,
                positions=m.positions,
                indices=m.indices,
                normals=m.normals,
                uvs=m.uvs,
                colors=m.colors,
            )
        )
    scene.extras = {"format": "nu2", "meshes": len(meshes), "textured": False}
    return [scene]
