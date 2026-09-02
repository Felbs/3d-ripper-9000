"""``XMDL`` models (gcrip.formats.xmdl): Home Run King keeps 69 of these in ``data.afs``, each
a run of self-contained models.  Every model becomes one primitive; the textures live in the
sibling `DDS ` members (gcrip.plugins.dds_pack) and are not bound yet."""

from __future__ import annotations

import posixpath

from gcrip.formats import xmdl
from ripcore.scene import MaterialDef, Primitive, Scene

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
        # `material` is an INDEX into scene.materials, so -1 against an empty list is not
        # "no material" - it is an IndexError at export.  That cost Home Run King 6,273 of its
        # models, the largest single failure count in the library, and cost `res` and
        # `wart_bmsh` theirs before it.
        scene.materials.append(MaterialDef(f"{scene.name}_mat", None))
        scene.primitives.append(
            Primitive(
                material=0,
                positions=model.positions,
                indices=model.indices,
                normals=model.normals,
                uvs=model.uvs,
            )
        )
        scene.extras = {"format": "xmdl", "index": i}
        out.append(scene)
    return out
