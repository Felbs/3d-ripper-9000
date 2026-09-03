"""RenderWare GameCube native geometry (gcrip.formats.rw_native): the unchunked tail of a
CLUMP, which holds GX display lists and vertex arrays with no chunk framing.

``plugins/renderware.py`` reads the chunked half of these files; this reads what it declines,
which on Piglet's BIG GAME is most of the geometry.  One Scene a clump, one primitive a group.
"""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import rw_native
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "rw_native"


def detect(path: str, head: bytes, size: int) -> bool:
    """A CLUMP big enough to hold a native block.  Whether it has one is `extract`'s job -
    64 bytes cannot show where the chunk walk stops."""
    if len(head) < 12 or size < rw_native.MIN_TAIL:
        return False
    cid = int.from_bytes(head[:4], "little")
    csize = int.from_bytes(head[4:8], "little")
    return cid == rw_native.CLUMP and csize <= size - 12


def extract(data: bytes, path: str, src) -> list[Scene]:
    at = rw_native.tail_of(data)
    if at is None:
        return []
    tail = data[at:]
    groups = rw_native.groups(tail)
    owned = rw_native.owned_spans(data)
    # a group whose lists sit inside a GEOMETRY chunk is that chunk's native data, and
    # renderware.py reads it; only the groups outside every GEOMETRY are this plugin's
    groups = [
        g for g in groups if not any(a <= at + g.lists_at < b for a, b in owned)
    ]
    resolved = [g for g in groups if g.resolved]
    if not resolved:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "clump"
    scene = Scene(name=stem)
    scene.materials.append(MaterialDef(name=f"{stem}_mat", texture=None))
    for g in resolved:
        tris = rw_native.triangles(tail, g)
        if not tris:
            continue
        scene.primitives.append(
            Primitive(
                material=0,
                positions=np.ascontiguousarray(rw_native.positions(tail, g), dtype=np.float32),
                indices=np.asarray(tris, dtype=np.uint32).reshape(-1),
                normals=np.ascontiguousarray(rw_native.normals(tail, g), dtype=np.float32),
            )
        )
    if not scene.primitives:
        return []
    declined = len(groups) - len(resolved)
    if declined:
        # a group whose normals cannot be found is left out rather than guessed at: the
        # positions are located *from* the normals, so without them there is nothing to read
        scene.warnings.append(f"{declined} of {len(groups)} groups had no unit-length normals")
    scene.extras = {"format": "rw_native", "groups": len(resolved)}
    return [scene]
