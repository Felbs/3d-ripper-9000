"""EA ``OBG`` terrain (gcrip.formats.ea_obg) - the ``ter`` members of the Tiger Woods ``SHOC``
archives.  One Scene a member: the shared position array, indexed by every element's strip."""

from __future__ import annotations

import posixpath

from gcrip.formats import ea_obg
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "ea_obg"
MIN_TRIANGLES = 4


def detect(path: str, head: bytes, size: int) -> bool:
    return ea_obg.is_obg(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = ea_obg.chunks(data)
    pos = ea_obg.positions(data, found)
    if pos is None:
        return []
    tri = ea_obg.triangles(data, len(pos), found)
    if len(tri) < MIN_TRIANGLES:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "terrain"
    scene = Scene(name=stem)
    scene.materials = [MaterialDef(name=stem, texture=None)]
    scene.primitives = [
        Primitive(material=stem, positions=pos.astype("f4"), indices=tri.astype("u4").ravel())
    ]
    scene.extras = {"format": "ea_obg", "elements": sum(1 for c in found if c.tag == b"ELDA")}
    return [scene]
