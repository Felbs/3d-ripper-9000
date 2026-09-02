"""``MDGC0200`` level meshes (gcrip.formats.mdgc): Superman: Shadow of Apokolips keeps 255 of
these.  Each mesh block becomes one Scene; the display list indexes the block's own vertex
array, and the per-corner colours are carried through where they line up."""

from __future__ import annotations

import posixpath

from gcrip.formats import mdgc
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "mdgc"


def detect(path: str, head: bytes, size: int) -> bool:
    return mdgc.is_mdgc(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = mdgc.meshes(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "mdgc"
    out = []
    for i, mesh in enumerate(found):
        scene = Scene(name=stem if len(found) == 1 else f"{stem}_{i:03d}")
        # `material` indexes scene.materials, so -1 against an empty list is an
        # IndexError at export rather than "no material" - see plugins/xmdl.py
        scene.materials.append(MaterialDef(f"{scene.name}_mat", None))
        scene.primitives.append(
            Primitive(material=0, positions=mesh.positions, indices=mesh.indices)
        )
        scene.extras = {"format": "mdgc", "index": i}
        out.append(scene)
    return out
