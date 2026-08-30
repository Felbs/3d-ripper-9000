"""``XMDL`` models (gcrip.formats.xmdl): Home Run King keeps 69 of these in ``data.afs``, each
a run of self-contained models.  Every model becomes one primitive; the textures live in the
sibling `DDS ` members (gcrip.plugins.dds_pack) and are not bound yet."""

from __future__ import annotations

import posixpath

from gcrip.formats import xmdl
from ripcore.scene import Primitive, Scene

NAME = "xmdl"


def detect(path: str, head: bytes, size: int) -> bool:
    return xmdl.is_xmdl(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = xmdl.models(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "xmdl"
    out = []
    for i, model in enumerate(found):
        scene = Scene(name=stem if len(found) == 1 else f"{stem}_{i:03d}")
        scene.primitives.append(
            Primitive(
                material=-1,
                positions=model.positions,
                indices=model.indices,
                normals=model.normals,
                uvs=model.uvs,
            )
        )
        scene.extras = {"format": "xmdl", "index": i}
        out.append(scene)
    return out
