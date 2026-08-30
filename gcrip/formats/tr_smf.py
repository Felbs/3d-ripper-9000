"""Terminal Reality ``_smf`` static meshes, the geometry chunks of a ``.PKG`` package
(:mod:`gcrip.formats.tr_pkg`) on BloodRayne, Blowout and RoadKill.

Layout of the chunk payload (little-endian for the bookkeeping, big-endian for the GX data)::

    u32  version        7
    u32  material count
    ...
    0x24: material records, 360 bytes each, each starting with a NUL-terminated texture
          name - the artist's ".tif", which is the name the package's 1tex chunks carry

then, for each object, a name, a bounding box, and one or more GX display lists.

The geometry is a **GX display list with the vertices written inline** rather than pulled from
indexed arrays, which is why scanning for the usual ``0x98`` triangle-strip opcode finds
nothing here: every list seen so far draws QUADS, opcode ``0x84`` (``0x80 | prim | vat 4``).
Each list is ``u8 opcode | u16 vertex count | count * 13 bytes``:

======  =========================  ==================================================
bytes   field                      scale
======  =========================  ==================================================
0-5     position, 3 x big-endian   s16 * 2^-8
        s16
6-8     normal, 3 x s8             /128
9-12    uv, 2 x big-endian s16     s16 * 2^-8
======  =========================  ==================================================

The 2^-8 position scale is not a guess: decoding Blowout's ``WEAP_MACHINEGUN.SMF`` that way
reproduces the bounding box stored beside the mesh to within 0.004 (quantisation), while
2^-7 and 2^-9 are out by 1.2 and 2.3.

A list is found by the eight-byte big-endian preamble ``00000008 00000001`` that sits in front
of every one of them (version 7 puts ``00000007`` in front of that as well), followed by zero
padding and then the opcode.  The preamble also turns up inside the ``F00DBAAD`` fill that
version 4 pads with, so a candidate only counts once the opcode and vertex count check out.  Walking with
a 13-byte vertex lands exactly on the next preamble, which is what confirms the stride: over
Blowout's ``GCB_11_CREDITS.PKG`` all 42 lists in 25 meshes walk clean, for 8,088 vertices and
4,044 triangles.

Quads are also how this engine writes triangles - it repeats a vertex - and the quads are not
consistently wound, so ~7% of the split triangles come out with zero area and ~10% inside out.
Both are corrected from data already in the file: a triangle is dropped if it is degenerate and
flipped if it disagrees with its own stored normals.  After that, 98% of Blowout's triangles
agree with their normals and none are inverted.

Version 4 (BloodRayne) writes the same ``0x84`` quad lists behind the same preamble, but with a
wider vertex - 16 bytes, all big-endian - and it stores its one texture name at 0x6c instead of
in 360-byte records:

======  =========================  ==================================================
bytes   field                      scale
======  =========================  ==================================================
0-5     position, 3 x s16          ``* 2^-15``
6-11    normal, 3 x s16            ``/ 16384`` (Q1.14 - the values run to exactly
                                   +/-16384 and come out unit length, 0.949 mean)
12-15   uv, 2 x u16                ``/ 256``
======  =========================  ==================================================

Version 4 stores NO bounding box, so its position scale has no anchor inside the file.  It has
one outside: both games ship a ``bullet.smf``, and BloodRayne's spans 10,496 units, which at
``2^-15`` is 0.3203 - the exact length Blowout's stored bounding box gives for its own bullet.
The other meshes fall in line (the missile 0.86, ``tatermasher`` 1.18 against Blowout's 1.98
machine gun).  Version 4 also pads with ``F00DBAAD`` and carries a ``kfmp1`` marker where
version 7 keeps its material records.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

SIGNATURE = b"\x00\x00\x00\x08\x00\x00\x00\x01"
MATERIAL_RECORD = 360
NAME_MAX = 64
MAX_VERTS = 1 << 16


@dataclass(frozen=True)
class Layout:
    """Where a version keeps its texture names, and how it writes a vertex."""

    stride: int
    materials_at: int
    material_record: int
    pos_scale: float
    normal_16: bool  # normals are s16 (version 4) rather than s8 (version 7)
    normal_at: int
    uv_at: int
    uv_scale: float


LAYOUTS = {
    4: Layout(16, 0x6C, 0, 1.0 / (1 << 15), True, 6, 12, 1.0 / 256.0),
    7: Layout(13, 0x24, MATERIAL_RECORD, 1.0 / (1 << 8), False, 6, 9, 1.0 / 256.0),
}
VERSIONS = tuple(sorted(LAYOUTS))
NORMAL_SCALE_8 = 1.0 / 128.0
NORMAL_SCALE_16 = 1.0 / 16384.0


@dataclass
class Mesh:
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray
    material: str = ""


@dataclass
class Smf:
    version: int
    materials: list[str] = field(default_factory=list)
    meshes: list[Mesh] = field(default_factory=list)


def layout(head: bytes) -> Layout | None:
    if len(head) < 8:
        return None
    version, materials = struct.unpack_from("<2I", head, 0)
    if version not in LAYOUTS or not 0 < materials < 4096:
        return None
    return LAYOUTS[version]


def is_smf(head: bytes) -> bool:
    return layout(head) is not None


def materials(data: bytes) -> list[str]:
    lay = layout(data[:8])
    if lay is None:
        return []
    # version 4 keeps a single name; version 7 repeats a record per object
    count = struct.unpack_from("<I", data, 4)[0] if lay.material_record else 1
    out = []
    for i in range(count):
        p = lay.materials_at + i * lay.material_record
        if p + NAME_MAX > len(data):
            break
        name = data[p : p + NAME_MAX].split(b"\0")[0].decode("latin-1", "replace")
        if name:
            out.append(name)
    return out


def _triangles(prim: int, count: int) -> np.ndarray:
    """Indices for one GX primitive drawn over `count` inline vertices."""
    idx = np.arange(count, dtype=np.uint32)
    if prim == 0x80:  # quads
        q = idx[: count // 4 * 4].reshape(-1, 4)
        return np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    if prim == 0x90:  # independent triangles
        return idx[: count // 3 * 3].reshape(-1, 3)
    if prim == 0x98:  # triangle strip - flip the winding on odd triangles
        if count < 3:
            return np.zeros((0, 3), np.uint32)
        a, b, c = idx[:-2], idx[1:-1], idx[2:]
        tris = np.stack([a, b, c], 1)
        tris[1::2] = tris[1::2][:, [0, 2, 1]]
        return tris
    if prim == 0xA0:  # triangle fan
        if count < 3:
            return np.zeros((0, 3), np.uint32)
        return np.stack([np.zeros(count - 2, np.uint32), idx[1:-1], idx[2:]], 1)
    return np.zeros((0, 3), np.uint32)


def _orient(pos: np.ndarray, nrm: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Drop degenerate triangles and wind the rest to agree with their stored normals.

    A quad list is how this engine writes triangles too - it repeats a vertex, which leaves
    ~7% of the split triangles with zero area - and the quads themselves are not consistently
    wound (10% come out inside-out).  Both are decided by data already in the file: the
    per-vertex normal says which way the face should point.
    """
    if not len(tris):
        return tris
    p = pos[tris]
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    length = np.linalg.norm(face, axis=1)
    keep = length > 1e-9
    tris, face, length = tris[keep], face[keep], length[keep]
    if not len(tris):
        return tris
    stored = nrm[tris].mean(axis=1)
    flip = (face / length[:, None] * stored).sum(axis=1) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    return tris


def _vertices(data: bytes, at: int, count: int, lay: Layout):
    raw = np.frombuffer(data[at : at + count * lay.stride], np.uint8).reshape(count, lay.stride)
    pos = raw[:, 0:6].copy().view(">i2").reshape(count, 3).astype(np.float32) * lay.pos_scale
    if lay.normal_16:
        nrm = raw[:, lay.normal_at : lay.normal_at + 6].copy().view(">i2")
        nrm = nrm.reshape(count, 3).astype(np.float32) * NORMAL_SCALE_16
    else:
        nrm = raw[:, lay.normal_at : lay.normal_at + 3].astype(np.int8).astype(np.float32)
        nrm = nrm * NORMAL_SCALE_8
    uv = raw[:, lay.uv_at : lay.uv_at + 4].copy().view(">i2")
    uv = uv.reshape(count, 2).astype(np.float32) * lay.uv_scale
    return pos, nrm, uv


def _list_at(data: bytes, start: int, lay: Layout) -> tuple[int, int, int, int] | None:
    """(prim, count, body, end) for the display list beginning at `start`, if it walks."""
    p = start
    while p < len(data) and data[p] == 0:
        p += 1
    if p + 3 > len(data):
        return None
    op = data[p]
    if op < 0x80 or (op & 0xF8) not in (0x80, 0x88, 0x90, 0x98, 0xA0, 0xA8):
        return None
    count = struct.unpack_from(">H", data, p + 1)[0]
    if not 0 < count <= MAX_VERTS:
        return None
    end = p + 3 + count * lay.stride
    return (op & 0xF8, count, p + 3, end) if end <= len(data) else None


def parse(data: bytes) -> Smf | None:
    lay = layout(data[:8])
    if lay is None:
        return None
    version = struct.unpack_from("<I", data, 0)[0]
    names = materials(data)
    out = Smf(version=version, materials=names)
    # a mesh often repeats one texture record per object, so judge by distinct names
    material = names[0] if len(set(names)) == 1 else ""
    p = 0
    while True:
        q = data.find(SIGNATURE, p)
        if q < 0:
            break
        p = q + len(SIGNATURE)
        found = _list_at(data, p, lay)
        if not found:
            continue
        prim, count, body, end = found
        tris = _triangles(prim, count)
        if not len(tris):
            continue
        pos, nrm, uv = _vertices(data, body, count, lay)
        tris = _orient(pos, nrm, tris)
        if not len(tris):
            continue
        out.meshes.append(Mesh(pos, nrm, uv, tris.reshape(-1), material))
        p = end
    return out
