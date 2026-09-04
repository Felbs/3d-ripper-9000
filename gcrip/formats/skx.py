"""Darkened Skye ``SKX`` models, the members of its ``PAK`` archives
(:mod:`gcrip.formats.skye_pak`) - 255 of them.

Big-endian throughout.  The header names the object and places it in the world::

    +0   char magic[4]  "\x00XKS"   - "SKX" byte-swapped
    +4   u32 version 2
    +8   u32 file size              matches the member length exactly
    +16  u32 0x24                   offset of the matrix below
    +24  u32 object-name offset     -> "AwGargSt#120"
    +32  u32 class-name offset      -> "Gargoyle"
    +36  f32[9] rotation, f32[3] placement   (-1663.2, 931.6, 173.15)

Each mesh is an eight-word directory.  A file may hold several, packed together and
interleaved with the meshes' name strings, so they are found by scanning::

    +0  u32 vertex count      +4  u32 vertex array size
    +8  f32 radius            +12 u32 vertex array offset
    +16 u32 triangle count    +20 u32 triangle array offset
    +24 u32 uv count          +28 u32 uv array offset

**A triangle is 16 bytes - eight `u16` - and its two index triples address different
arrays**: columns 0-2 index the vertices, columns 3-5 index the uvs.  Reading columns 0-2
as uv indices is what an earlier pass did, and it silently produced a quarter of the models
because the uv array is usually the larger of the two.

**A vertex is a variable-length skinning record**, which is why no fixed stride ever tiled
the array::

    u32 influences n, then n times:  s16 x, s16 y, s16 z, u16 joint, f32 weight

The position is stored once per influence in that joint's own space.  Coordinates are `s16`
over the `radius` in the directory, so world scale is ``radius / 32768``.

Every one of those fields is checked against the others rather than trusted, and the three
equalities settle the layout on their own::

    vertex offset + vertex size == triangle offset
    triangle offset + triangles * 16 == uv offset
    walking `n` skinning records lands exactly on the triangle offset

Normals are optional: when ``uv end + vertices * 12`` fits and those vectors are unit
length, they are per-vertex `f32` normals - on the gargoyle 399 of them, mean length 1.0
and standard deviation 0.0.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"\x00XKS"
DIRECTORY = 32
TRIANGLE = 16
INFLUENCE = 12
MAX_COUNT = 200000
MAX_INFLUENCES = 8
FULL = 32768.0  # the s16 range the radius spans


@dataclass
class Mesh:
    positions: np.ndarray  # (N,3) f32, world scale
    indices: np.ndarray  # (M*3,) u32, one vertex a corner
    uvs: np.ndarray | None
    normals: np.ndarray | None
    joints: np.ndarray  # (N,) u16, the first influence's joint
    joints4: np.ndarray | None = None  # (N,4) u16 skin joints
    weights4: np.ndarray | None = None  # (N,4) f32 skin weights


@dataclass
class Directory:
    nverts: int
    vsize: int
    radius: float
    voff: int
    ntris: int
    ioff: int
    nuvs: int
    uvoff: int


def is_skx(head: bytes) -> bool:
    return len(head) >= 12 and head[:4] == MAGIC


def _walk(data: bytes, at: int, count: int, limit: int) -> int | None:
    """Step over ``count`` skinning records; the landing offset is the proof."""
    p = at
    for _ in range(count):
        if p + 4 > limit:
            return None
        n = struct.unpack_from(">I", data, p)[0]
        if not 0 < n <= MAX_INFLUENCES or p + 4 + INFLUENCE * n > limit:
            return None
        p += 4 + INFLUENCE * n
    return p


def directories(data: bytes) -> list[Directory]:
    out: list[Directory] = []
    for at in range(0, max(0, len(data) - DIRECTORY), 4):
        nverts, vsize, radius, voff, ntris, ioff, nuvs, uvoff = struct.unpack_from(
            ">2If5I", data, at
        )
        if not (0 < nverts < MAX_COUNT and 0 < ntris < MAX_COUNT and 0 < nuvs < MAX_COUNT):
            continue
        if voff <= DIRECTORY or voff + vsize != ioff or ioff + ntris * TRIANGLE != uvoff:
            continue
        if uvoff + nuvs * 8 > len(data) or not 0.0 < radius < 1e9:
            continue
        if _walk(data, voff, nverts, ioff) != ioff:
            continue
        out.append(Directory(nverts, vsize, radius, voff, ntris, ioff, nuvs, uvoff))
    return out


FIXED_POINT = 1024.0  # s16 vertex coords are 6.10 fixed-point in the joint's local frame


def _vertices(
    data: bytes, d: Directory, skeleton: list[np.ndarray] | None
) -> tuple[np.ndarray, np.ndarray]:
    """Positions and first-influence joints.

    With a ``skeleton`` (4x4 joint globals from :mod:`gcrip.formats.skye_skel`), every
    influence is decoded properly: ``v = sum w_i * (G_j @ (raw/1024))``; the joint index
    addresses the joint-global list directly (0-based, proven by the render oracle).
    Without one (props, or no matching ``.skg``), the first
    influence's raw coords at /1024 stand alone - exact for the single-joint props, and an
    honest approximation otherwise."""
    pos = np.empty((d.nverts, 3), np.float32)
    joints = np.empty(d.nverts, np.uint16)
    j4 = np.zeros((d.nverts, 4), np.uint16)
    w4 = np.zeros((d.nverts, 4), np.float32)
    p = d.voff
    for i in range(d.nverts):
        n = struct.unpack_from(">I", data, p)[0]
        p += 4
        acc = np.zeros(3)
        tw = 0.0
        first_j = 0
        for k in range(n):
            x, y, z, j = struct.unpack_from(">4h", data, p)
            w = struct.unpack_from(">f", data, p + 8)[0]
            p += INFLUENCE
            if k == 0:
                first_j = j
            if k < 4:
                j4[i, k] = j
                w4[i, k] = w
            local = np.array((x, y, z), np.float64) / FIXED_POINT
            if skeleton is not None and 0 <= j < len(skeleton):
                G = skeleton[j]
                acc += w * (G[:3, :3] @ local + G[:3, 3])
                tw += w
            elif skeleton is None and k == 0:
                acc = local
                tw = 1.0
        pos[i] = acc / max(tw, 1e-9)
        s4 = w4[i].sum()
        if s4 > 0:
            w4[i] /= s4
        joints[i] = first_j
    return pos, joints, j4, w4


def _normals(data: bytes, d: Directory) -> np.ndarray | None:
    end = d.uvoff + d.nuvs * 8
    if end + d.nverts * 12 > len(data):
        return None
    n = np.frombuffer(data[end : end + d.nverts * 12], ">f4").reshape(d.nverts, 3)
    if not np.isfinite(n).all():
        return None
    length = np.linalg.norm(n.astype(np.float64), axis=1)
    if abs(length.mean() - 1.0) > 1e-3 or length.std() > 1e-3:
        return None
    return n.astype(np.float32)


def meshes(data: bytes, skeleton: list[np.ndarray] | None = None) -> list[Mesh]:
    """One mesh a directory, expanded to one vertex a triangle corner - the position and uv
    index streams are separate, so corners are the only common vertex.  ``skeleton`` is the
    joint-global list from :func:`gcrip.formats.skye_skel.match_skeleton`."""
    out: list[Mesh] = []
    for d in directories(data):
        pos, joints, j4, w4 = _vertices(data, d, skeleton)
        tri = np.frombuffer(data[d.ioff : d.ioff + d.ntris * TRIANGLE], ">u2").reshape(d.ntris, 8)
        vi, ti = tri[:, :3].astype(np.int64), tri[:, 3:6].astype(np.int64)
        if vi.max() >= d.nverts or ti.max() >= d.nuvs:
            continue
        uv = np.frombuffer(data[d.uvoff : d.uvoff + d.nuvs * 8], ">f4").reshape(d.nuvs, 2)
        normals = _normals(data, d)
        corner_pos = pos[vi].reshape(-1, 3)
        corner_uv = uv[ti].reshape(-1, 2).astype(np.float32)
        corner_n = normals[vi].reshape(-1, 3) if normals is not None else None
        out.append(
            Mesh(
                positions=corner_pos,
                indices=np.arange(len(corner_pos), dtype=np.uint32),
                uvs=corner_uv,
                normals=corner_n,
                joints=joints[vi].reshape(-1),
                joints4=j4[vi].reshape(-1, 4),
                weights4=w4[vi].reshape(-1, 4),
            )
        )
    return out
