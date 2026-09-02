"""Billy Hatcher and the Giant Egg (GameCube) ``.arc`` resources: Ginja object trees with an
embedded GVM.  Big-endian; every pointer is relative to 0x20, so the file after its header
is a plain Ginja buffer (gcrip.formats.ginja parses it, gcrip.ninja_eval evaluates it).

Header (0x20): ``u32 file size | u32 pointer table (relocation list at the end of the file)
| u32 | 0 | 0 | "0100" | 0 | 0``, then a resource record list at 0x20 whose first word is
the resource type (0x20 model, 0x10 UI textures, 0x1c animated model, 0x1a0 player, ...).
Objects are Ninja NJS_OBJECTs (flags, attach, pos f32[3], rot BAMS[3], scale f32[3], child,
sibling) padded to 0x38 bytes with ``FDFDFDFD``; the object tree roots are found by that
pad rather than by decoding every record type.  Attaches are SA Tools' GCAttach with the
skin-set pointer in use: bone nodes write ``s16 pos[3] + s16 nrm[3]`` rows (/256) into a
shared vertex cache (``u16 type | u16 size | u16 slot | u16 count | u32 rows | u32 weights``
records: type 0 single bone, 1 first weighted write at slot + i, 2 accumulate at the slot
named in the ``u16 slot, u16 weight/255`` pairs) and the mesh node indexes that cache.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip import ninja_eval
from gcrip.formats import ninja
from gcrip.formats import ginja, gvr
from ripcore.scene import Scene

BASE = 0x20
_PAD = b"\xfd\xfd\xfd\xfd"


def is_arc(head: bytes, size: int | None = None) -> bool:
    if len(head) < 0x18 or head[0x14:0x18] != b"0100":
        return False
    total, table = struct.unpack_from(">2I", head, 0)
    if size is not None and total != size:
        return False
    return 0x60 < table <= total


def objects(p: bytes) -> list[int]:
    """Offsets (in the 0x20-based buffer) of every plausible NJS_OBJECT."""
    out = []
    q = 0
    n = len(p)
    while True:
        q = p.find(_PAD, q)
        if q < 0:
            break
        o = q - 0x34
        q += 4
        if o < 0x20 or o % 4:
            continue
        w = struct.unpack_from(">II3f3i3fII", p, o)
        if w[0] >= 0x10000 or w[1] >= n or w[11] >= n or w[12] >= n:
            continue
        if not all(np.isfinite(v) and abs(v) < 1e6 for v in w[2:5]):
            continue
        if not all(np.isfinite(v) and abs(v) < 1e4 for v in w[8:11]):
            continue
        out.append(o)
    return out


def roots(p: bytes) -> list[int]:
    cands = objects(p)
    referenced = set()
    for o in cands:
        child, sib = struct.unpack_from(">2I", p, o + 0x2C)
        referenced.update(x for x in (child, sib) if x)
    return [o for o in cands if o not in referenced]


def textures(d: bytes) -> list[gvr.Texture]:
    g = d.find(b"GVMH", 0x60)
    return gvr.gvm_textures(d[g:]) if g > 0 else []


def scenes(d: bytes, name: str) -> tuple[list[Scene], list[gvr.Texture]]:
    """(rigged scenes, one per object-tree root with geometry; GVM textures)."""
    if not is_arc(d[:0x60], len(d)):
        return [], []
    texs = textures(d)
    p = d[BASE:]
    out: list[Scene] = []
    for r in roots(p):
        warnings: list[str] = []
        parser = ginja.GinjaParser(p, warnings)
        try:
            root = parser.object(r, None)
        except (ninja.NinjaError, struct.error, IndexError, ValueError):
            continue
        if not any(o.model is not None and o.model.strips for o in parser.objects):
            continue
        nj = ninja.Ninja(root=root, objects=parser.objects, kind="ginja", warnings=warnings)
        if texs:
            nj.texlist = ninja.TexList([t.name for t in texs])
        scene = ninja_eval.evaluate(nj, name if not out else f"{name}_{len(out)}")
        if scene.primitives:
            scene.extras = {"format": "billy-arc", "objects": len(parser.objects), "root": r}
            out.append(scene)
    return out, texs
