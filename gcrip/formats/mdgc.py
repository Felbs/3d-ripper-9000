"""``MDGC0200`` levels (Superman: Shadow of Apokolips, 255 ``.dgc`` files).

Nothing to do with the TotemTech ``.dgc`` of Spirits & Spells - the extension is shared, the
format is not.  This one is uncompressed (entropy 5.27 on the biggest level against 7.7+ for a
compressed payload), so everything is readable in place.

File header::

    +0   char magic[8]  "MDGC0200"
    +8   u32 size
    +16  u32 count
    +20  u32 0x1007     the block tag, repeated on every block

A mesh block is a 64-byte header of big-endian ``u32``, and the fields that matter are::

    w5   corner count
    w6   vertex count
    w11  offset of the display list
    w13  offset of the per-corner RGBA colours
    w15  offset of the per-corner s8 normals

All three offsets are relative to **the end of the header** (block + 64), which is also where
the vertex positions start - ``count`` big-endian ``f32`` triples.

The display list is ordinary **GX**: ``u8 opcode | u16 count | count * 6 bytes``, where a vertex
is three big-endian ``u16`` - position index, colour index, normal index - and ``0xffff`` marks
an attribute the block does not use.  Every list seen draws triangle strips (``0x98``).

Two details are found rather than assumed.  The list does not begin at ``w11`` but after a
sub-header of varying length (40, 52 and 56 bytes on the three blocks measured), so the reader
scans forward for the first opcode from which the whole list walks.  And the walk is its own
proof: on two of the three blocks it consumes the bytes up to the next block exactly, and no
position index ever exceeds the vertex count.

Yield on ``L95.dgc``: 78 blocks in the first 3 MB, 9,328 vertices; the file is 6 MB of 255.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"MDGC0200"
TAG = 0x1007
HEADER = 64
STRIDE = 6  # a display-list vertex: position, colour and normal index, each a u16
PRIMS = {0x98: "strip", 0xA0: "fan", 0x90: "triangles", 0x80: "quads"}
SUBHEADER_SEARCH = 128
MAX_VERTS = 200000
NO_INDEX = 0xFFFF


@dataclass
class Mesh:
    positions: np.ndarray
    indices: np.ndarray
    colors: np.ndarray | None


def is_mdgc(head: bytes) -> bool:
    return head[:8] == MAGIC


def _triangles(prim: int, run: np.ndarray) -> list[np.ndarray]:
    if prim == 0x98:
        if len(run) < 3:
            return []
        a, b, c = run[:-2], run[1:-1], run[2:]
        tris = np.stack([a, b, c], axis=1)
        tris[1::2] = tris[1::2][:, [0, 2, 1]]
        return [tris]
    if prim == 0xA0:
        if len(run) < 3:
            return []
        return [np.stack([np.full(len(run) - 2, run[0]), run[1:-1], run[2:]], axis=1)]
    if prim == 0x90:
        return [run[: len(run) // 3 * 3].reshape(-1, 3)]
    if prim == 0x80:
        q = run[: len(run) // 4 * 4].reshape(-1, 4)
        return [np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])]
    return []


def _walk(data: bytes, start: int, limit: int, nverts: int):
    """(triangles, end) for the display list beginning at `start`, or (None, start)."""
    out: list[np.ndarray] = []
    p = start
    while p < limit:
        op = data[p]
        if op == 0:
            p += 1
            continue
        if op not in PRIMS:
            break
        count = struct.unpack_from(">H", data, p + 1)[0]
        body = p + 3
        if count == 0 or body + count * STRIDE > limit:
            break
        idx = np.frombuffer(data[body : body + count * STRIDE], ">u2").reshape(count, 3)
        if int(idx[:, 0].max()) >= nverts:
            break
        out.extend(_triangles(op, idx[:, 0].astype(np.uint32)))
        p = body + count * STRIDE
    if not out:
        return None, start
    return np.concatenate(out), p


def _clean(pos: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Drop zero-area triangles.

    Triangle strips stitch separate runs together by repeating a vertex, so ~12% of the
    triangles a strip expands to have no area at all; they are an artefact of the encoding, not
    geometry.
    """
    p = pos[tris].astype(np.float64)
    area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    return tris[area > 1e-9]


def blocks(data: bytes) -> list[int]:
    """Offsets of the mesh-block headers."""
    found: list[int] = []
    tag = struct.pack(">I", TAG)
    p = 4
    while True:
        q = data.find(tag, p)
        if q < 0:
            break
        p = q + 4
        base = q - 4
        if base >= 0 and base + HEADER <= len(data):
            found.append(base)
    return found


def meshes(data: bytes) -> list[Mesh]:
    if not is_mdgc(data[:8]):
        return []
    starts = blocks(data)
    out: list[Mesh] = []
    for i, base in enumerate(starts):
        w = struct.unpack_from(">16I", data, base)
        nverts, dl_off, colour_off = w[6], w[11], w[13]
        body = base + HEADER
        if not 0 < nverts <= MAX_VERTS or body + nverts * 12 > len(data):
            continue
        limit = starts[i + 1] if i + 1 < len(starts) else len(data)
        at = body + dl_off
        if not body < at < limit:
            continue
        best = None
        for start in range(at, min(at + SUBHEADER_SEARCH, limit)):
            if data[start] not in PRIMS:
                continue
            tris, end = _walk(data, start, limit, nverts)
            if tris is not None and (best is None or end - start > best[1] - best[0]):
                best = (start, end, tris)
        if best is None:
            continue
        positions = np.frombuffer(data[body : body + nverts * 12], ">f4").reshape(nverts, 3)
        tris = _clean(positions, best[2])
        if not len(tris):
            continue
        colors = None
        cstart = body + colour_off
        if colour_off and cstart + nverts * 4 <= len(data):
            colors = np.frombuffer(data[cstart : cstart + nverts * 4], np.uint8).reshape(nverts, 4)
        out.append(Mesh(positions.astype(np.float32), tris.reshape(-1), colors))
    return out
