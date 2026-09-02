"""``PHM`` models - Neversoft's ``.wad`` discs: Spawn: Armageddon and The Scorpion King.

The container and its 12,018 ``TIM`` textures have read for a while (see
``docs/formats/spawn-toc-wad.md``); ``PHM`` is the geometry, and it was blocked on the vertex
layout - ``gxscan`` finds no display lists, and there is no ``f32`` run outside the matrix
block, so the vertices are quantised.

**The vertex record is 20 bytes, ten big-endian ``s16``**::

    0,1    texture coordinates, 0..1024
    2,3,4  position
    5,6,7  normal, divided by 4096
    8,9    -1, -1 on every vertex

Three identities pin it, and none of them is a guess about what looks right:

* **the normal is unit length**.  Columns 5, 6 and 7 over 4096 give a mean length of 0.9998 with
  a standard deviation of 0.0001, and **every one of the 1,987 vertices** falls between 0.98 and
  1.02.  That confirms the stride, the array's offset and the field's position together - a
  wrong stride smears a column and this one does not smear;
* **columns 8 and 9 are constant**.  A wrong stride cannot hold a column constant across 1,987
  records;
* **the array ends where the next section starts**.  1,987 x 20 = 39,740 from 30,384 reaches
  70,124, and the header lists 70,128.

Which three columns are the *position* is then settled by agreement with those known-good
normals: face normals from columns 2, 3 and 4 agree with the stored normal at **0.748 mean, 59.7%
of triangles above 0.8**, against 0.42 to 0.56 and 15 to 32% for every other triple.  Using
normal agreement to choose among candidates when the normals are already verified is sound; using
it to *search* for a layout is not, and that distinction is what the Terminal Reality note
records after it went the other way.

The index array is ``u16`` and its values run 0 to ``vertices - 1`` exactly, which is how it is
recognised.  The triangles come out as a strip; agreement is short of 1.0 because the array is
almost certainly several strips rather than one, and the run boundaries are not yet read.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

STRIDE = 20
FIELDS = STRIDE // 2
NORMAL_SCALE = 4096.0
UV_SCALE = 1024.0
HEADER_WORDS = 64  # the section table sits in the first few hundred bytes
MAX_VERTS = 1 << 18


@dataclass
class Mesh:
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray  # (M, 3)


def is_phm(head: bytes) -> bool:
    """``u32 0, u32 1, u32 64`` then a block of f32 that reads as a matrix per bone."""
    if len(head) < 12:
        return False
    a, b, c = struct.unpack_from(">3I", head, 0)
    return a == 0 and b == 1 and c == 64


def _unit_normals(data: bytes, offset: int, count: int) -> bool:
    if offset + count * STRIDE > len(data) or count < 3:
        return False
    raw = np.frombuffer(data, ">i2", count * FIELDS, offset).reshape(count, FIELDS)
    if not (raw[:, 8] == -1).all() or not (raw[:, 9] == -1).all():
        return False
    n = np.linalg.norm(raw[:, 5:8].astype(np.float64) / NORMAL_SCALE, axis=1)
    return bool(((n > 0.98) & (n < 1.02)).mean() > 0.99)


def _candidates(data: bytes) -> list[tuple[int, int]]:
    """(count, offset) pairs from the header that could be an array."""
    out = []
    top = min(len(data) - 8, HEADER_WORDS * 4)
    for at in range(0, top, 4):
        count, offset = struct.unpack_from(">2I", data, at)
        if 0 < count <= MAX_VERTS and 0 < offset < len(data):
            out.append((count, offset))
    return out


def mesh(data: bytes) -> Mesh | None:
    """The model, or ``None``.

    The arrays are located by their own arithmetic rather than by fixed offsets: the vertex
    array is the one whose normals come out unit length, and the index array is the one whose
    values span exactly ``0 .. vertices - 1``.
    """
    if not is_phm(data[:12]):
        return None
    pairs = _candidates(data)
    vertices = next(((c, o) for c, o in pairs if _unit_normals(data, o, c)), None)
    if vertices is None:
        return None
    nverts, voff = vertices
    raw = np.frombuffer(data, ">i2", nverts * FIELDS, voff).reshape(nverts, FIELDS)
    indices = None
    for count, offset in pairs:
        if offset + count * 2 > len(data) or count < 3 or (count, offset) == vertices:
            continue
        candidate = np.frombuffer(data, ">u2", count, offset)
        if int(candidate.max()) == nverts - 1:
            indices = candidate.astype(np.int64)
            break
    if indices is None:
        return None
    strip = np.stack([indices[:-2], indices[1:-1], indices[2:]], 1)
    positions = raw[:, 2:5].astype(np.float32)
    keep = (
        (strip[:, 0] != strip[:, 1]) & (strip[:, 1] != strip[:, 2]) & (strip[:, 0] != strip[:, 2])
    )
    return Mesh(
        positions=positions,
        normals=(raw[:, 5:8].astype(np.float32) / NORMAL_SCALE),
        uvs=(raw[:, 0:2].astype(np.float32) / UV_SCALE),
        indices=strip[keep].astype(np.int32),
    )
