"""Free Radical ``gcr`` character models - TimeSplitters 2's ``ob/chrs/chr*.gcr`` (314 in
``data/chr.pak``).  Read against the draw routine in the TS2 ``main.dol`` (no symbols: the
function at ``0x8024a454`` that calls ``GXSetArray`` nine times), 2026-09-03.

The file is the runtime image: pointers are offsets from byte 0, and the header the game
keeps is the **last 52 bytes** (``+4`` of the file says where: ``file length - 52``)::

    +0    u32 12              -> a table of 16-byte texture slots: u32 gct id
                                 (``textures/%04d.gct`` in the same pak), u32[3] zero,
                                 ended by 0xFFFFFFFF
    +4    u32 trailer offset  the last 52 bytes: u32 records, u32 bones, u32 1, ..., f32
    the records precede the trailer: ``records x 0xa0`` bytes, each a node

    node  +0   u8 kind         0 rigid (one bone, byte +1), 1 / 2 / 3 skinned pieces
          +1   u8 bone         +2 .. +5 more node bytes (parent / next, 0xff none)
          +0x14 + 4 * lod   -> batch table: 10-byte ``u16 texture slot, u16 index,
                               u16 first vertex, u16 vertices, u16 flags``, ended by an
                               entry whose flags are 0xFFFF (three LODs at most)
          +0x24 + 0x14 * lod   u32, ptr positions (f32 x3), ptr uvs (f32 x2, x3 when
                               bit ``lod`` of +0x67 is set), ptr colours (RGBA8, or 0),
                               ptr normals (s8 x3 + pad, / 64)
          +0x60 u16, +0x62 u16, +0x67 u8 uv flags, +0x8c f32 (1 / 0.5 / 0.3)
          +0x90 + 4 * lod   -> per batch ``u32 display list, u32 bytes`` (0, 0 = none)

A display list is GX: ``0x98 | fmt, u16 count`` strips of vertices that are four big-endian
``u16`` indices - position, normal, colour, uv - with, on the skinned kinds, a leading ``u8``
matrix (bone) index, so 8 bytes on kind 0 and 9 on the others.  Positions are the bind pose in
model space (feet at y = 0, head at 1.86 on ``chr128``), so a rigid node's bone is only
metadata here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats.eagl import _triangulate

TRAILER = 52
RECORD = 0xA0
LODS = 3
BATCH = 10
TEXTURE_SLOT = 16
END = 0xFFFF
END32 = 0xFFFFFFFF
PRIM_MASK = 0xF8
PRIM_OPS = {0x80, 0x90, 0x98, 0xA0}
MAX_RECORDS = 1024
MAX_BATCHES = 256
MAX_VERTS = 1 << 16
NRM_SCALE = 1.0 / 64.0


@dataclass
class Batch:
    node: int
    kind: int
    bone: int
    slot: int  # texture slot -> Model.textures
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    colors: np.ndarray | None
    indices: np.ndarray
    bones: np.ndarray | None  # per-vertex matrix index on the skinned kinds


@dataclass
class Model:
    records: int = 0
    bones: int = 0
    textures: list[int] = field(default_factory=list)  # gct ids by slot
    batches: list[Batch] = field(default_factory=list)
    lods: int = 1
    warnings: list[str] = field(default_factory=list)


def is_gcr(head: bytes, size: int) -> bool:
    if len(head) < 12 or size < TRAILER + RECORD + 16:
        return False
    a, b, c = struct.unpack_from(">3I", head, 0)
    return a == 12 and b == size - TRAILER and c == 0


def _textures(data: bytes) -> list[int]:
    out = []
    p = 12
    while p + TEXTURE_SLOT <= len(data) and len(out) < MAX_BATCHES:
        gct = struct.unpack_from(">I", data, p)[0]
        if gct == END32:
            break
        out.append(gct)
        p += TEXTURE_SLOT
    return out


def _batches(data: bytes, at: int) -> list[tuple[int, int, int, int]] | None:
    out = []
    p = at
    while p + BATCH <= len(data) and len(out) < MAX_BATCHES:
        slot, index, first, count, flags = struct.unpack_from(">5H", data, p)
        if flags == END:
            return out
        out.append((slot, index, first, count))
        p += BATCH
    return None


def _strips(data: bytes, at: int, size: int, stride: int):
    """(index rows (n, 4), matrix bytes or None, triangle corner order) of one display list."""
    end = min(at + size, len(data))
    p = at
    rows, mtx, prims = [], [], []
    base = 0
    while p + 3 <= end:
        op = data[p]
        if op == 0:
            p += 1
            continue
        if op & PRIM_MASK not in PRIM_OPS:
            return None
        count = struct.unpack_from(">H", data, p + 1)[0]
        p += 3
        if count < 1 or p + count * stride > end:
            return None
        raw = np.frombuffer(data, np.uint8, count * stride, p).reshape(count, stride)
        if stride == 9:
            mtx.append(raw[:, 0].copy())
            raw = raw[:, 1:]
        rows.append(raw.copy().view(">u2").reshape(count, 4))
        prims.append((op & PRIM_MASK, count, base))
        base += count
        p += count * stride
    if not rows:
        return None
    tri = _triangulate(prims, np.arange(base, dtype=np.uint32)).reshape(-1, 3)
    return np.concatenate(rows), (np.concatenate(mtx) if mtx else None), tri


def parse(data: bytes) -> Model | None:
    if not is_gcr(data[:12], len(data)):
        return None
    out = Model()
    trailer = len(data) - TRAILER
    count, bones = struct.unpack_from(">2I", data, trailer)
    if not 0 < count <= MAX_RECORDS or trailer - count * RECORD < 12:
        out.warnings.append(f"{count} records do not fit")
        return out
    out.records, out.bones = count, bones
    out.textures = _textures(data)
    base = trailer - count * RECORD
    for i in range(count):
        r = base + i * RECORD
        kind, bone = data[r], data[r + 1]
        stride = 8 if kind == 0 else 9
        uv_flags = data[r + 0x67]
        for lod in range(LODS):
            table = struct.unpack_from(">I", data, r + 0x14 + 4 * lod)[0]
            pairs = struct.unpack_from(">I", data, r + 0x90 + 4 * lod)[0]
            if not table:
                break
            if lod:
                out.lods = max(out.lods, lod + 1)
                continue  # the finest level is the model; the others are the same shape
            arrays = r + 0x24 + 0x14 * lod
            _h, pos_at, uv_at, clr_at, nrm_at = struct.unpack_from(">5I", data, arrays)
            batches = _batches(data, table)
            if batches is None or not pos_at or not uv_at:
                out.warnings.append(f"node {i}: batch table unreadable")
                break
            nverts = batches[-1][2] + batches[-1][3] if batches else 0
            if not 0 < nverts <= MAX_VERTS or pos_at + nverts * 12 > len(data):
                out.warnings.append(f"node {i}: {nverts} vertices past the file")
                break
            uv_stride = 12 if uv_flags & (1 << lod) else 8
            positions = np.frombuffer(data, ">f4", nverts * 3, pos_at).reshape(nverts, 3)
            for k, (slot, _index, _first, _n) in enumerate(batches):
                if pairs + 8 * k + 8 > len(data):
                    break
                dl_at, dl_size = struct.unpack_from(">2I", data, pairs + 8 * k)
                if not dl_at or not dl_size:
                    continue
                got = _strips(data, dl_at, dl_size, stride)
                if got is None:
                    out.warnings.append(f"node {i}: batch {k} display list unreadable")
                    continue
                rows, mtx, tri = got
                if int(rows[:, 0].max()) >= nverts:
                    out.warnings.append(f"node {i}: batch {k} indexes past {nverts} vertices")
                    continue
                uniq, inverse = np.unique(rows, axis=0, return_inverse=True)
                tri = inverse.reshape(-1)[tri]
                keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2])
                tri = tri[keep & (tri[:, 0] != tri[:, 2])]
                if not len(tri):
                    continue
                pi = uniq[:, 0].astype(np.int64)
                ni = uniq[:, 1].astype(np.int64)
                ti = uniq[:, 3].astype(np.int64)
                nmax, tmax = int(ni.max()), int(ti.max())
                if nrm_at and nrm_at + (nmax + 1) * 4 <= len(data):
                    nrm = np.frombuffer(data, np.int8, (nmax + 1) * 4, nrm_at).reshape(-1, 4)[:, :3]
                    normals = (nrm[ni].astype(np.float32) * NRM_SCALE).astype(np.float32)
                else:
                    normals = np.zeros((len(uniq), 3), np.float32)
                if uv_at + (tmax + 1) * uv_stride <= len(data):
                    uv = np.frombuffer(data, ">f4", (tmax + 1) * uv_stride // 4, uv_at).reshape(
                        -1, uv_stride // 4
                    )[:, :2]
                    uvs = np.ascontiguousarray(uv[ti], np.float32)
                else:
                    uvs = np.zeros((len(uniq), 2), np.float32)
                colors = None
                if clr_at:
                    ci = uniq[:, 2].astype(np.int64)
                    ncol = int(ci.max()) + 1
                    if clr_at + ncol * 4 <= len(data):
                        c = np.frombuffer(data, np.uint8, ncol * 4, clr_at).reshape(-1, 4)
                        colors = np.ascontiguousarray(c[ci])
                per_vertex_bone = None
                if mtx is not None:
                    # the matrix byte travels with the corner; take it from the first corner
                    # that names each unique vertex
                    first = np.zeros(len(uniq), np.int64)
                    first[inverse.reshape(-1)[::-1]] = np.arange(len(inverse) - 1, -1, -1)
                    per_vertex_bone = mtx[first].astype(np.uint16)
                out.batches.append(
                    Batch(
                        i,
                        kind,
                        bone,
                        slot,
                        np.ascontiguousarray(positions[pi], np.float32),
                        normals,
                        uvs,
                        colors,
                        tri.ravel().astype(np.uint32),
                        per_vertex_bone,
                    )
                )
    return out
