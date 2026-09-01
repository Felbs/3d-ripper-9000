"""Yuke's ``YOBJ`` meshes - the ``.ymg`` files of the WWE discs.

WrestleMania X8 carries 732 of them (31 MB) and WrestleMania XIX 1,464 (28 MB); the two Day of
Reckoning discs have 1,099 and 207, though nearly all of theirs are ``DUMY`` wrappers rather
than ``YOBJ`` (see the note).  All four discs produced no models at all.

Big-endian::

    +0    char magic[4]   "YOBJ"
    +12   u32 table offset
    +16   u32

The table holds one record per mesh, but **the record length is not constant** - it drifts by
four bytes between records because the trailing float block varies - so records are found by
the constant word ``0x0a000000`` that every one contains rather than by a stride.  Relative to
that marker at ``m``::

    m-8   u16 vertex count
    m+4   u32 -> positions
    m+8   u32 -> normals
    m+16  u32 -> the index block

**Every offset in this format points eight bytes before its data.**  That is the whole trick:
read the arrays at the offset itself and the first normal comes out with a length of 7.05
instead of 1, while the other eleven are exactly 1 - which reads like an off-by-one in the
count rather than a block header.  At ``offset + 8`` all of them are unit vectors.

Positions and normals are ``count`` triples of big-endian ``f32``, and ``normals - positions ==
count * 12`` has to hold.  The index block is a run of ``u32 count`` followed by that many
``u16`` triangle-strip indices, packed with no padding, starting at ``C + 16`` - the extra
eight bytes past the usual ``+8`` being a small header the strips follow.

## How well it checks out

The positions and normals are confirmed on both variants and are not in doubt: **981 of 981
records** in X8's ``dummy_x8.ymg`` and **10,445 of 10,445** normals in XIX's ``0_2.ymg`` come
out unit length at ``+8``, which no wrong layout does.

On X8 the index lists read too - 8,104 meshes, 125,428 vertices and 47,090 triangles from ten
files, with an unsigned normal agreement of **0.983 and 98% of meshes above 0.9**.  Winding is
inconsistent as it is in Terminal Reality's ``_smf`` and A2M's ``.gc``, so triangles are flipped
to agree with their own stored normals and the figure quoted is the unsigned one taken before
the flip.

**XIX's index block is laid out differently** and is not read here: it opens with a table of
eight-byte entries (``u16``, ``u16``, ``u32`` pointer) rather than going straight into strips.
A reader for that was tried and produced 97 triangles at 0.451 agreement while also cutting
X8 from 8,104 meshes to 5,480, so it is left out and the files are declined instead of being
turned into rubbish.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"YOBJ"
MARKER = 0x0A000000
COUNT_AT = -8
POS_AT = 4
NRM_AT = 8
IDX_AT = 16
BLOCK_SKIP = 8  # every offset points eight bytes before its data
INDEX_SKIP = 16
STRIDE = 12  # one f32 triple
MIN_COUNT = 3
MAX_COUNT = 1 << 16
MAX_STRIP = 8192
UNIT_TOLERANCE = 1e-2


@dataclass
class Mesh:
    positions: np.ndarray
    normals: np.ndarray
    indices: np.ndarray
    unsigned_agreement: float


def is_yobj(head: bytes) -> bool:
    return head[:4] == MAGIC


def _strips(data: bytes, start: int, count: int) -> list[tuple[int, int, int]]:
    tris: list[tuple[int, int, int]] = []
    at = start
    while at + 4 <= len(data):
        n = struct.unpack_from(">I", data, at)[0]
        if not (MIN_COUNT <= n <= MAX_STRIP) or at + 4 + n * 2 > len(data):
            break
        ids = struct.unpack_from(f">{n}H", data, at + 4)
        if max(ids) >= count:
            break
        at += 4 + n * 2
        for k in range(n - 2):
            tris.append(
                (ids[k], ids[k + 1], ids[k + 2]) if k % 2 == 0 else (ids[k + 1], ids[k], ids[k + 2])
            )
    return tris


def _orient(positions, normals, tri):
    a, b, c = positions[tri[:, 0]], positions[tri[:, 1]], positions[tri[:, 2]]
    face = np.cross(b - a, c - a).astype(np.float64)
    length = np.linalg.norm(face, axis=1)
    keep = length > 1e-9
    if not keep.any():
        return None, 0.0
    tri, face, length = tri[keep], face[keep], length[keep]
    face /= length[:, None]
    vert = (normals[tri[:, 0]] + normals[tri[:, 1]] + normals[tri[:, 2]]).astype(np.float64) / 3
    vlen = np.linalg.norm(vert, axis=1)
    vert[vlen > 0] /= vlen[vlen > 0][:, None]
    cos = (face * vert).sum(1)
    flip = cos < 0
    tri[flip] = tri[flip][:, ::-1]
    return tri, float(np.abs(cos).mean())


def meshes(data: bytes) -> list[Mesh]:
    if not is_yobj(data[:4]):
        return []
    out: list[Mesh] = []
    for m in range(8, max(0, len(data) - 20), 4):
        if struct.unpack_from(">I", data, m)[0] != MARKER:
            continue
        count = struct.unpack_from(">H", data, m + COUNT_AT)[0]
        pos_at, nrm_at, idx_at = (
            struct.unpack_from(">I", data, m + o)[0] for o in (POS_AT, NRM_AT, IDX_AT)
        )
        if not (MIN_COUNT <= count <= MAX_COUNT):
            continue
        if not (0 < pos_at < nrm_at < idx_at < len(data)):
            continue
        if nrm_at - pos_at != count * STRIDE:
            continue
        if nrm_at + BLOCK_SKIP + count * STRIDE > len(data) or idx_at + INDEX_SKIP > len(data):
            continue
        normals = np.frombuffer(data, ">f4", count * 3, nrm_at + BLOCK_SKIP).reshape(count, 3)
        lengths = np.linalg.norm(normals.astype(np.float64), axis=1)
        if np.abs(lengths - 1.0).max() > UNIT_TOLERANCE:
            continue
        positions = np.frombuffer(data, ">f4", count * 3, pos_at + BLOCK_SKIP).reshape(count, 3)
        tris = _strips(data, idx_at + INDEX_SKIP, count)
        if not tris:
            continue
        tri, agreement = _orient(
            np.ascontiguousarray(positions),
            np.ascontiguousarray(normals),
            np.array(tris, np.int64),
        )
        if tri is None:
            continue
        out.append(
            Mesh(
                np.ascontiguousarray(positions, np.float32),
                np.ascontiguousarray(normals, np.float32),
                tri.ravel().astype(np.uint32),
                agreement,
            )
        )
    return out
