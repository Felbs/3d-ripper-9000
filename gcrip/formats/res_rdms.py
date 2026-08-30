"""``rdms`` meshes - the geometry sections of the ``res`` middleware used by Digimon Rumble
Arena 2, Lemony Snicket's A Series of Unfortunate Events and Samurai Jack: The Shadow of Aku.
Sibling ``surf`` sections hold the textures (:mod:`gcrip.formats.res_surf`).

A section is a small big-endian header, a GX display list, and four indexed attribute arrays::

    +0x00 u32 1
    +0x04 u32 0xffffff1c
    +0x08 u32 display-list block size   - undercounts the padding on some sections
    +0x0c u32 display-list block offset (0x54)
    +0x1c f32 position scale        - only when positions are s16, see below
    +0x40 u32[5] array offsets      - **each one relative to its own header word**
    +0x54 u8  position format       - 0 = f32 triples, 1 = s16 triples
    ...   the display list, after a short preamble

**The array offsets are self-relative**, which is what made every earlier reading come out one
element short: array *i* lives at ``u32[i] + 0x40 + 4*i``, so a single base makes the first
array right and every later one wrong by a growing multiple of four.  With the right base the
five offsets are all 32-byte aligned and the last is the end of the section.

A display-list corner is five big-endian ``u16`` attribute indices - position, normal, colour,
uv, and a fifth that is always zero - so the stride is 10.  The preamble before the first
opcode is not fixed, so the list is found by scanning for the first opcode from which the walk
lands on the end of the block.

The **strides come from the arrays' own sizes**, not from a guess: each array is padded to a
32-byte boundary, so a stride is admissible only when ``count * stride`` rounds up to exactly
the gap to the next array.  On every section sampled that leaves one candidate - 6 for
positions (or 12 where the header says f32), 3 for normals, 4 for uvs - which is the check that
the layout is right.

Fixed-point scales: normals are ``s8/64`` (an `s8` normal of (24, -59, 0) has length 63.7),
uvs are ``s16/4096`` (the maximum on most sections is exactly 4096, one texture edge), and
``s16`` positions are multiplied by the ``f32`` at +0x1c.  That last one is the least certain
part of this reader, but it is the reading that makes the two encodings agree: raw ``s16``
positions are quantised into a power-of-two box (256, 512, 1024, 1536), and the float brings
them back to the same 100-1,000 unit range as the sections that store ``f32`` directly.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats.hsd import triangulate

ARRAYS_AT = 0x40
ARRAYS = 5
BLOCK_AT = 0x0C
SCALE_AT = 0x1C
FORMAT_AT = 0x54
CORNER = 10  # five u16 attribute indices
ALIGN = 32
PREAMBLE = 48  # how far into the block the first opcode may sit
OPS = (0x80, 0x90, 0x98, 0xA0)
UV_SCALE = 1.0 / 4096.0
NORMAL_SCALE = 1.0 / 64.0
POSITION_STRIDES = {0: 12, 1: 6}


@dataclass
class Mesh:
    positions: np.ndarray  # (N,3) f32
    indices: np.ndarray  # (M*3,) u32
    normals: np.ndarray | None
    uvs: np.ndarray | None


def _arrays(data: bytes) -> list[int] | None:
    if len(data) < ARRAYS_AT + ARRAYS * 4:
        return None
    words = struct.unpack_from(f">{ARRAYS}I", data, ARRAYS_AT)
    out = [w + ARRAYS_AT + 4 * i for i, w in enumerate(words)]
    if any(a % ALIGN for a in out) or out != sorted(out) or out[-1] > len(data):
        return None
    return out


def _walk(data: bytes, start: int, end: int) -> list[tuple[int, int, int]] | None:
    """Display lists from ``start``; None unless the walk lands on the end of the block."""
    p, out = start, []
    while p + 3 <= end:
        op = data[p]
        if op not in OPS:
            break
        count = struct.unpack_from(">H", data, p + 1)[0]
        if count == 0 or p + 3 + count * CORNER > end:
            break
        out.append((op, count, p + 3))
        p += 3 + count * CORNER
    if not out or not 0 <= end - p <= ALIGN:
        return None
    return out


def _corners(data: bytes, lists: list[tuple[int, int, int]]) -> np.ndarray:
    return np.concatenate(
        [
            np.frombuffer(data[o : o + c * CORNER], ">u2").reshape(c, CORNER // 2)
            for _, c, o in lists
        ]
    )


def _stride(gap: int, count: int, allowed: tuple[int, ...]) -> int | None:
    """The one stride whose array, padded to 32 bytes, is exactly the gap to the next array."""
    fits = [s for s in allowed if count * s <= gap and -(-count * s // ALIGN) * ALIGN == gap]
    return fits[0] if len(fits) == 1 else None


def mesh(data: bytes) -> Mesh | None:
    arrays = _arrays(data)
    if arrays is None or len(data) <= FORMAT_AT:
        return None
    block = struct.unpack_from(">I", data, BLOCK_AT)[0]
    end = arrays[0]  # the block size at +8 undercounts the padding on some sections
    lists = None
    for start in range(block, min(block + PREAMBLE, end)):
        lists = _walk(data, start, end)
        if lists:
            break
    if not lists:
        return None

    corners = _corners(data, lists)
    counts = (corners.max(0) + 1).tolist()
    gaps = [arrays[i + 1] - arrays[i] for i in range(ARRAYS - 1)]

    pos_stride = POSITION_STRIDES.get(data[FORMAT_AT])
    if pos_stride is None or _stride(gaps[0], counts[0], (pos_stride,)) is None:
        return None
    if pos_stride == 12:
        positions = np.frombuffer(data[arrays[0] : arrays[0] + counts[0] * 12], ">f4")
        positions = positions.reshape(-1, 3).astype(np.float32)
    else:
        raw = np.frombuffer(data[arrays[0] : arrays[0] + counts[0] * 6], ">i2").reshape(-1, 3)
        scale = struct.unpack_from(">f", data, SCALE_AT)[0]
        positions = (raw * scale).astype(np.float32)
    if not np.isfinite(positions).all():
        return None

    normals = None
    if counts[1] > 1 and _stride(gaps[1], counts[1], (3,)) == 3:
        raw = np.frombuffer(data[arrays[1] : arrays[1] + counts[1] * 3], ">i1").reshape(-1, 3)
        normals = (raw * NORMAL_SCALE).astype(np.float32)

    uvs = None
    if counts[3] > 1 and _stride(gaps[3], counts[3], (4,)) == 4:
        raw = np.frombuffer(data[arrays[3] : arrays[3] + counts[3] * 4], ">i2").reshape(-1, 2)
        uvs = (raw * UV_SCALE).astype(np.float32)

    tris = []
    base = 0
    for op, count, _ in lists:
        tris.append(triangulate(op, count) + base)
        base += count
    faces = np.concatenate(tris) if tris else np.zeros((0, 3), np.int64)
    if not len(faces):
        return None

    # strips stitch many short runs together, so half the corners are zero-area joins
    p0, p1, p2 = (positions[corners[faces[:, k], 0]].astype(np.float64) for k in range(3))
    area = np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    faces = faces[area > 1e-9]
    if not len(faces):
        return None

    # one vertex a corner: the attribute index streams are separate
    pick = faces.reshape(-1)
    out_pos = positions[corners[pick, 0]]
    out_nrm = normals[corners[pick, 1]] if normals is not None else None
    out_uv = uvs[corners[pick, 3]] if uvs is not None else None
    return Mesh(
        positions=out_pos,
        indices=np.arange(len(out_pos), dtype=np.uint32),
        normals=out_nrm,
        uvs=out_uv,
    )
