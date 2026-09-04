"""Darkened Skye skeletons - the piece that turns ``SKX`` joint-space vertices into bodies.

Cracked 2026-09-04 (the overnight sprint) by hypothesis-grid + oracle + render.  Three facts,
each proven on the data:

1. **Every ``SKX`` carries its own joint table.**  The header word at +12 is the joint-record
   count (0x4b = 75 on Skye, 0x5b = 91 on the vampire, matching each mesh's max joint index),
   and 128-byte rows start at +0xa4: ``f32[9]`` local rotation (row-major), ``f32[3]`` local
   translation at +36, a per-joint bbox at +96, ``{u16 index, u16 index+2}`` at +120 and
   ``{s16 mirror-or--1, 0}`` at +124.  Row locals equal the group skeleton's records exactly.

2. **Parents live only in the group ``.skg``** (the animation banks): 64-byte joint records
   found by their constant ``f32 (-5,-5,-5,5,5,5)`` signature, ``{i32 parent, u32 1-based
   index, i32 mirror, f32 t[3], f32 quat[4], bbox}`` - the first record is a table header
   (its second word is the record count), real joints follow.  75/75 quaternions unit on
   BoneSkye - that identity pinned the field split.

3. **Vertex coordinates are s16 fixed-point, /1024, in the joint's local frame** - not
   scaled by the directory radius (the old reader's mistake, which made every multi-joint
   model spaghetti), not bbox-quantized.  ``v = sum_i w_i * (G_j @ (raw_i / 1024))`` over
   the influences, with ``G_j`` the chained parent@local global.
"""

from __future__ import annotations

import struct

import numpy as np

SKG_BBOX = struct.pack(">6f", -5, -5, -5, 5, 5, 5)
SKG_RECORD = 64
SKX_TABLE_AT = 0xA4
SKX_ROW = 128
FIXED_POINT = 1024.0


def skg_parents(data: bytes) -> list[int] | None:
    """The parent index per joint from a group ``.skg``, or None when the file has no
    skeleton table.  Record 0 is the table header and is dropped."""
    first = data.find(SKG_BBOX)
    if first < 40:
        return None
    at = first - 40
    parents: list[int] = []
    while at + SKG_RECORD <= len(data):
        if data[at + 40 : at + 64] != SKG_BBOX:
            break
        parents.append(struct.unpack_from(">i", data, at)[0])
        at += SKG_RECORD
    return parents[1:] if len(parents) >= 2 else None


def skx_joint_count(data: bytes) -> int:
    """The header's joint-record count (includes the header record of the group table)."""
    if len(data) < 16:
        return 0
    return struct.unpack_from(">I", data, 12)[0]


def skx_joint_locals(data: bytes) -> list[tuple[np.ndarray, np.ndarray]] | None:
    """(R, t) local transforms from the SKX's own joint table, validated row by row (a
    rotation's rows must be near-unit).  Returns None when the table is absent/implausible."""
    n = skx_joint_count(data)
    joints = n - 1  # the count includes the group table's header record
    if not 1 <= joints <= 512 or SKX_TABLE_AT + joints * SKX_ROW > len(data):
        return None
    out = []
    for i in range(joints):
        off = SKX_TABLE_AT + i * SKX_ROW
        f = np.frombuffer(data, dtype=">f4", count=12, offset=off)
        if not np.all(np.isfinite(f)):
            return None
        R = np.array(f[:9], dtype=np.float64).reshape(3, 3)
        lens = np.linalg.norm(R, axis=1)
        if np.any(np.abs(lens - 1) > 0.1):
            return None
        out.append((R, np.array(f[9:12], dtype=np.float64)))
    return out


def joint_globals(
    locals_: list[tuple[np.ndarray, np.ndarray]], parents: list[int]
) -> list[np.ndarray]:
    """Chained 4x4 globals; a parent index outside 0..i-1 makes a root."""
    G: list[np.ndarray] = []
    for i, (R, t) in enumerate(locals_):
        L = np.eye(4)
        L[:3, :3] = R
        L[:3, 3] = t
        p = parents[i] if i < len(parents) else -1
        G.append(G[p] @ L if 0 <= p < i else L)
    return G


def match_skeleton(data: bytes, skgs: list[bytes]) -> list[np.ndarray] | None:
    """The SKX's joint globals, using the first candidate ``.skg`` whose skeleton record
    count matches the SKX header's; None when no candidate matches."""
    locals_ = skx_joint_locals(data)
    if locals_ is None:
        return None
    want = skx_joint_count(data)
    for skg in skgs:
        parents = skg_parents(skg)
        if parents is not None and len(parents) + 1 == want and len(parents) >= len(locals_):
            return joint_globals(locals_, parents)
    return None
