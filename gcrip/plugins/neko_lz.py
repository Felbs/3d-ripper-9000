"""Cocoto / Charlie's Angels ``.GCN`` / ``.pc`` (gcrip.formats.neko_lz): a container of one
member - the file unpacked, named ``.mwld`` when it is a level - and the level's static world
as one Scene (gcrip.formats.neko_mwld), a primitive a material id."""

from __future__ import annotations

import posixpath
import struct

import numpy as np

from gcrip.formats import neko_lz, neko_mwld
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "neko_lz"
EXTENSIONS = (".gcn", ".pc")


def is_container(name: str, head: bytes) -> bool:
    # the sniff has no file size, so this accepts a header whose unpacked count exceeds its
    # packed one; expand() checks the packed count against the real size
    if not name.lower().endswith(EXTENSIONS) or len(head) < 8:
        return False
    packed, unpacked = struct.unpack_from(">2I", head, 0)
    return 0 < packed < unpacked <= neko_lz.MAX_UNPACKED


def expand(data: bytes) -> list[tuple[str, bytes]]:
    blob = neko_lz.unpack(data)
    if not blob:
        return []
    name = "world.mwld" if neko_mwld.is_level(blob[:16], len(blob)) else "unpacked.bin"
    return [(name, blob)]


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".mwld") and neko_mwld.is_level(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    w = neko_mwld.parse(data)
    if w is None or not len(w.triangles):
        return []
    # the container's stem names the level: files/data/L11/L11.GCN/world.mwld -> L11
    stem = posixpath.basename(posixpath.dirname(path)).rsplit(".", 1)[0] or "world"
    scene = Scene(name=stem)
    scene.warnings.extend(w.warnings)
    for material in np.unique(w.materials):
        tri = w.triangles[w.materials == material]
        uniq, inverse = np.unique(tri.ravel(), return_inverse=True)
        scene.materials.append(MaterialDef(name=f"material_{int(material)}", texture=None))
        scene.primitives.append(
            Primitive(
                material=len(scene.materials) - 1,
                positions=np.ascontiguousarray(w.positions[uniq]),
                indices=inverse.reshape(-1).astype(np.uint32),
                uvs=np.ascontiguousarray(w.uvs[uniq]),
                colors=(w.colors[uniq].astype(np.float32) / 255.0).astype(np.float32),
            )
        )
    scene.extras = {
        "format": "neko_mwld",
        "objects": [o[0] for o in w.objects],
        "faces": int(len(w.triangles)),
    }
    return [scene]
