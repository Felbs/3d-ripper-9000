"""``XMDL`` models (Home Run King, ``data.afs``: 69 members holding 32 or more models each).

A member is a run of self-contained models, each laid out big-endian::

    char magic[4]   "XMDL"
    char platform[4] "NTGC"      - Nintendo GameCube
    u16, u16                     - 4, 3
    u32 size                     - of the model after this 16-byte header
    ... sections ...

and the next model starts at ``align32(16 + size)``.  The sections are tagged but not
length-prefixed: ``MDEL`` (a bounding box), ``MATR`` (material), ``TXNM`` (texture name),
``GRPV``, ``VRTX``, ``COLV``, ``INDX``.

``GRPV`` is the one that matters, because it is the directory - eight big-endian ``u32``::

    +4  0x0e | +8  flags | +12 vertex count | +16 0
    +20 VRTX offset | +24 0 | +28 INDX offset | +32 index count

Both offsets are relative to the model start plus 12.  The vertex offset is 344 in every model
seen, but it is read rather than assumed.

A vertex is **32 bytes, all big-endian f32**: position, normal, uv.  The normals are the proof -
decoded this way every normal in the file comes out at length 1.0000 to four decimals.  Indices
are one byte each, three to a triangle.

As in other GameCube exporters of the period the triangle list is not tidy: ~15% of triangles
repeat a vertex and so have zero area, and ~5% are wound inside out.  Both are corrected from
data the file already carries - a triangle is dropped if it is degenerate and flipped if it
disagrees with its own stored normals.  This is cleanup, not guesswork: the layout comes from
``GRPV``, not from fitting anything.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"XMDL"
PLATFORM = b"NTGC"
HEADER = 16
ALIGN = 32
VERTEX = 32
SECTION_BASE = 12  # GRPV offsets are relative to the model start plus this
GRPV = b"GRPV"
MAX_MODELS = 20000


@dataclass
class Model:
    offset: int  # of the model within the blob
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray


def is_xmdl(head: bytes) -> bool:
    return len(head) >= 8 and head[:4] == MAGIC and head[4:8] == PLATFORM


def _orient(pos: np.ndarray, nrm: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Drop zero-area triangles and wind the rest to agree with their stored normals."""
    # in float64: some models span thousands of units and the cross product overflows f32
    p = pos[tris].astype(np.float64)
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    length = np.linalg.norm(face, axis=1)
    keep = length > 1e-12
    tris, face, length = tris[keep], face[keep], length[keep]
    if not len(tris):
        return tris
    stored = nrm[tris].astype(np.float64).mean(axis=1)
    slen = np.linalg.norm(stored, axis=1)
    good = slen > 1e-6
    flip = np.zeros(len(tris), bool)
    flip[good] = (face[good] / length[good, None] * stored[good] / slen[good, None]).sum(1) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    return tris


def _model(data: bytes, at: int, total: int) -> Model | None:
    blk = data[at : at + total]
    g = blk.find(GRPV)
    if g < 0 or g + 36 > len(blk):
        return None
    nverts, _z, voff, _z2, ioff, nidx = struct.unpack_from(">6I", blk, g + 12)
    if not (0 < nverts <= 65536 and 0 < nidx <= 1 << 20):
        return None
    vtx = voff + SECTION_BASE
    idx = ioff + SECTION_BASE
    if blk[vtx : vtx + 4] != b"VRTX" or blk[idx : idx + 4] != b"INDX":
        return None
    if vtx + 4 + nverts * VERTEX > len(blk) or idx + 4 + nidx > len(blk):
        return None
    v = np.frombuffer(blk[vtx + 4 : vtx + 4 + nverts * VERTEX], ">f4").reshape(nverts, 8)
    tri = np.frombuffer(blk[idx + 4 : idx + 4 + nidx // 3 * 3], np.uint8).astype(np.uint32)
    if len(tri) == 0 or tri.max() >= nverts:
        return None
    positions = v[:, 0:3].astype(np.float32)
    normals = v[:, 3:6].astype(np.float32)
    tris = _orient(positions, normals, tri.reshape(-1, 3))
    if not len(tris):
        return None
    return Model(
        offset=at,
        positions=positions,
        normals=normals,
        uvs=v[:, 6:8].astype(np.float32),
        indices=tris.reshape(-1),
    )


def models(data: bytes) -> list[Model]:
    """Every model in the blob; stops at the first thing that is not an XMDL header."""
    out: list[Model] = []
    p = 0
    while p + HEADER <= len(data) and len(out) < MAX_MODELS:
        if not is_xmdl(data[p : p + 8]):
            break
        size = struct.unpack_from(">I", data, p + 12)[0]
        total = (HEADER + size + ALIGN - 1) // ALIGN * ALIGN
        if size == 0 or p + total > len(data):
            break
        found = _model(data, p, total)
        if found is not None:
            out.append(found)
        p += total
    return out
