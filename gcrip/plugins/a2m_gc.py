"""``.gc`` resource files (gcrip.formats.a2m_gc) - Teen Titans, Monster House, Ed Edd n Eddy,
The Ant Bully and Happy Feet.  One Scene a file, one primitive a mesh, named by the artist.

Happy Feet stores the same files zlib-compressed as ``.cp``; those are expanded as a container
so the ``.gc`` inside reaches this plugin as an ordinary file.
"""

from __future__ import annotations

import posixpath

from gcrip.formats import a2m_gc
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "a2m_gc"


def detect(path: str, head: bytes, size: int) -> bool:
    return a2m_gc.is_gc(head)


def is_container(name: str, head: bytes) -> bool:
    """Happy Feet's ``.cp``.  ``rip.py`` passes the member's basename, never a path."""
    return name.lower().endswith(".cp") and a2m_gc.is_cp(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = a2m_gc.decompress(data)
    if out is None or not a2m_gc.is_gc(out[:64]):
        return []
    stem = out[a2m_gc.NAME_AT : a2m_gc.NAME_AT + a2m_gc.NAME_LEN]
    name = stem.split(b"\x00", 1)[0].decode("latin-1", "replace") or "level"
    return [(f"{name}.gc", out)]


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = a2m_gc.resources(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "level"
    scene = Scene(name=stem)
    for res in found:
        for mesh in a2m_gc.meshes(data[res.offset : res.offset + res.size], res.name):
            scene.materials.append(MaterialDef(name=mesh.name, texture=None))
            scene.primitives.append(
                Primitive(
                    material=len(scene.materials) - 1,
                    positions=mesh.positions,
                    indices=mesh.indices,
                    normals=mesh.normals,
                    uvs=mesh.uvs,
                    colors=mesh.colours,
                )
            )
    if not scene.primitives:
        return []
    scene.extras = {"format": "a2m_gc", "resources": len(found)}
    return [scene]
