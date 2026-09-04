"""Krome Studios ``GC01`` models - the ``.mdl`` + ``.mdg`` pairs of Jimmy Neutron: Jet
Fusion (1,317 in its RKV), the Merkury engine before MDL3.  ``Model::UnpackTemplate`` and
``Model::ExploreBuildVertex`` in the shipped ``Jimmy.elf`` (symtab, no DWARF).

``.mdl`` (``ModelTemplate``, big-endian, pointers as offsets from the file start)::

    +0    "GC01"
    +4    u16
    +6    i16 subobjects
    +8    i16 refpoints
    +12   u32 subobject table        0x50-byte records
    +16   u32 refpoint table         0x20-byte records, name pointer at +16
    +20   u32
    +32   f32 min[3], f32, max[3]    (the same seven floats open each subobject)
    +44   f32 radius
    subobject   +0 f32 bounds[7]; +0x30 ptr name; +0x34 ptr; +0x42 i16 materials;
                +0x44 ptr material list
    material    u32 ptr name (the .tex stem, ``Material::Create``), u32 .mdg offset,
                u16 bytes >> 4, u16, u32 strips

``.mdg``: GX display lists as the hardware reads them - ``u8 opcode (0x98 strip ...), u16
count`` then 24-byte vertices: f32 position[3], s8 normal[3] / 64, u16 RGBA4 colour, s16 uv
/ 4096, three bytes of padding (``ExploreBuildVertex``: stride 0x18, the constants 1/64, 15
and 4096 next to it in sdata2).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats.eagl import _triangulate

MAGIC = b"GC01"
SUBOBJECT = 0x50
MATERIAL = 0x10
REFPOINT = 0x20
VERTEX = 24
PRIM_OPS = {0x80, 0x90, 0x98, 0xA0}
MAX_COUNT = 1 << 16


@dataclass
class Part:
    subobject: str
    material: str
    positions: np.ndarray
    normals: np.ndarray
    colors: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray


@dataclass
class Model:
    parts: list[Part] = field(default_factory=list)
    refpoints: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_gc01(head: bytes) -> bool:
    if len(head) < 16 or head[:4] != MAGIC:
        return False
    nsub, nref = struct.unpack_from(">hh", head, 6)
    sub_at = struct.unpack_from(">I", head, 12)[0]
    return 0 < nsub < MAX_COUNT and 0 <= nref < MAX_COUNT and sub_at >= 16


def _cstr(d: bytes, o: int) -> str:
    if o <= 0 or o >= len(d):
        return ""
    end = d.find(b"\0", o)
    return d[o : end if end > 0 else len(d)].decode("latin-1", "replace")


def _lists(mdg: bytes, at: int, size: int, warn: list[str], label: str):
    """Every display list in ``mdg[at:at+size]``: (positions, normals, colours, uvs, tris)."""
    end = min(at + size, len(mdg))
    p = at
    pos, nrm, clr, uv, tris = [], [], [], [], []
    base = 0
    while p + 3 <= end:
        op = mdg[p]
        if op == 0:
            p += 1
            continue
        if op not in PRIM_OPS:
            warn.append(f"{label}: opcode {op:#x} at {p}")
            break
        count = struct.unpack_from(">H", mdg, p + 1)[0]
        body = p + 3
        if body + count * VERTEX > end or count < 3:
            warn.append(f"{label}: a list of {count} vertices past its {size} bytes")
            break
        raw = np.frombuffer(mdg, np.uint8, count * VERTEX, body).reshape(count, VERTEX)
        pos.append(raw[:, :12].copy().view(">f4").reshape(count, 3))
        nrm.append(raw[:, 12:15].astype(np.int8).astype(np.float32) / 64.0)
        c = raw[:, 15:17].copy().view(">u2").reshape(count)
        clr.append(
            np.stack([(c >> 12) & 15, (c >> 8) & 15, (c >> 4) & 15, c & 15], 1).astype(np.uint8)
            * 17
        )
        uv.append(raw[:, 17:21].copy().view(">i2").reshape(count, 2).astype(np.float32) / 4096.0)
        t = _triangulate([(op, count, 0)], np.arange(count, dtype=np.uint32)).reshape(-1, 3)
        tris.append(t + base)
        base += count
        p = body + count * VERTEX
    if not pos:
        return None
    return (
        np.concatenate(pos).astype(np.float32),
        np.concatenate(nrm),
        np.concatenate(clr),
        np.concatenate(uv),
        np.concatenate(tris).astype(np.uint32).reshape(-1),
    )


def parse(mdl: bytes, mdg: bytes) -> Model:
    out = Model()
    if not is_gc01(mdl[:16]):
        raise ValueError("not a GC01 model")
    nsub, nref = struct.unpack_from(">hh", mdl, 6)
    sub_at, ref_at = struct.unpack_from(">2I", mdl, 12)
    for i in range(nref):
        o = ref_at + i * REFPOINT
        if o + REFPOINT > len(mdl):
            break
        out.refpoints.append(_cstr(mdl, struct.unpack_from(">I", mdl, o + 16)[0]))
    for i in range(nsub):
        o = sub_at + i * SUBOBJECT
        if o + SUBOBJECT > len(mdl):
            out.warnings.append(f"subobject {i} past the file")
            break
        name = _cstr(mdl, struct.unpack_from(">I", mdl, o + 0x30)[0])
        nmat = struct.unpack_from(">h", mdl, o + 0x42)[0]
        mat_at = struct.unpack_from(">I", mdl, o + 0x44)[0]
        for k in range(max(nmat, 0)):
            m = mat_at + k * MATERIAL
            if m + MATERIAL > len(mdl):
                out.warnings.append(f"{name}: material {k} past the file")
                break
            name_at, offset, size16, _x, _strips = struct.unpack_from(">IIHHI", mdl, m)
            material = _cstr(mdl, name_at)
            got = _lists(mdg, offset, size16 << 4, out.warnings, f"{name}/{material}")
            if got is None:
                continue
            pos, nrm, clr, uv, tris = got
            out.parts.append(Part(name, material, pos, nrm, clr, uv, tris))
    return out
