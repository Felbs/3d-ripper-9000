"""``bmsh`` - the skinned character meshes of the ``res`` middleware (Samurai Jack: The
Shadow of Aku, Lemony Snicket's A Series of Unfortunate Events, Digimon Rumble Arena 2).
Levels are ``rdms`` (:mod:`gcrip.formats.res_rdms`); characters are one ``bmsh`` a file, CPU
skinned, and drawn from a vertex buffer the game fills every frame.  The file stores that
buffer in its bind pose, so the rip needs no bone maths.

Section layout (big-endian, every pointer **self-relative**)::

    +0x00 u32 batches           +0x08 f32 position scale (1/4096)
    +0x24 ptr main table        - the last batch's table, see below
    +0x30 0x28-byte sub-batch records, batches - 1 of them:
          ptr gshd, u32 6, u32 palette bones, ptr palette, 0, 1, 0, ptr table, f32 radius, 0
    then  the main batch: ptr gshd, u32[] bone list, table (16-aligned, at the +0x24 pointer)

A **table** is 0x40 bytes and is followed by the mesh's vertex buffer::

    +0x00 u32 rigid rows,   ptr rigid table     16-byte rows  u32 bone, u32 count, ptr run, u32
    +0x08 u32 pair rows,    ptr pair table      24-byte rows  u32 bone a, u32 bone b, u32 count,
                                                              u32, ptr run, u32
    +0x10 u32 blend rows,   ptr blend table     20-byte rows  u32 bone, u32 count, ptr run, u32, u32
    +0x18 ptr bounds (8 x s16)                  +0x1c u32 36
    +0x20 ptr uvs (f32 u, f32 v, 0, 0 a vertex) +0x24 u32 vertices
    +0x28 u32 display-list bytes                +0x2c ptr display list
    +0x40 the vertex buffer: ``s16 x y z, s16 nx ny nz`` (12 bytes a vertex, x scale, /1024)

The rigid and pair rows point *into* the vertex buffer (their slot is the run offset from the
buffer start over 12), which is how the slots were found: a bone's run sits at
``(run - buffer) / 12`` and nowhere else.  The blend rows point at runs stored *after* the
buffer, one copy of the vertex per contributing bone, and the table is followed by their slot
lists - ``u16[count]`` padded to 32 bytes then ``u8[count]`` weights (sum 256) padded to 32 -
so a blended slot's bind-pose position is any of its copies (they are all equal at bind).  A
slot no row claims is still a vertex; the buffer holds it.

The display list is one ``0x99`` (triangle strip, VAT 1) with a ``u16`` count and 8-byte
corners of four identical ``u16`` slot indices - position, normal, uv and a fourth attribute
all indexed by the slot - restarted with repeated indices.  On the Scotsman that gives 2,098
triangles whose face normals agree with the stored ones on 100 % (mean 0.87), longest edge
0.29 on a 1.0-wide model; the eyeball test mesh (one bone, 164 vertices) agrees on 100 %.

The batch's ``gshd`` shader links its ``surf`` texture the way ``rdms`` shaders do
(:func:`gcrip.formats.res.surf_of_shader`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

HEADER = 0x30
SUB_BATCH = 0x28
TABLE = 0x40
VERTEX = 12
RIGID_ROW = 16
PAIR_ROW = 24
BLEND_ROW = 20
ALIGN = 32
CORNER = 8
STRIP = 0x99
NORMAL_SCALE = 1.0 / 1024.0
MAX_BATCHES = 64
MAX_VERTICES = 65536


@dataclass
class Batch:
    shader: int | None  # offset of the batch's gshd relative to the section, None when unknown
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray


@dataclass
class Model:
    batches: list[Batch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _ptr(data: bytes, at: int) -> int:
    return at + struct.unpack_from(">i", data, at)[0]


def is_bmsh(data: bytes) -> bool:
    if len(data) < HEADER + TABLE:
        return False
    batches = struct.unpack_from(">I", data, 0)[0]
    scale = struct.unpack_from(">f", data, 8)[0]
    return 1 <= batches <= MAX_BATCHES and 0 < scale < 1 and 0 < _ptr(data, 0x24) < len(data)


def tables(data: bytes) -> list[tuple[int, int]]:
    """``(gshd offset, table offset)`` a batch; the gshd offset is relative to the section
    (so usually negative - the shaders precede the mesh)."""
    batches = struct.unpack_from(">I", data, 0)[0]
    out = []
    at = HEADER
    for _ in range(batches - 1):
        if at + SUB_BATCH > len(data):
            break
        out.append((_ptr(data, at), _ptr(data, at + 0x1C)))
        at += SUB_BATCH
    if at + 4 <= len(data):
        # the main record: its shader, then a bone list of varying length; the header's
        # +0x24 pointer says where its table starts
        out.append((_ptr(data, at), _ptr(data, 0x24)))
    return out


def _strip(data: bytes, at: int, size: int, vertices: int) -> np.ndarray | None:
    if at < 0 or at + 4 > len(data) or data[at + 1] != STRIP:
        return None
    count = struct.unpack_from(">H", data, at + 2)[0]
    if count < 3 or at + 4 + count * CORNER > len(data) or 4 + count * CORNER > size + ALIGN:
        return None
    corners = np.frombuffer(data, ">u2", count * 4, at + 4).reshape(count, 4)[:, 0].astype(np.int64)
    if int(corners.max()) >= vertices:
        return None
    a, b, c = corners[:-2], corners[1:-1], corners[2:]
    keep = (a != b) & (b != c) & (a != c)
    odd = (np.arange(len(a)) & 1).astype(bool)
    tri = np.where(odd[:, None], np.stack([b, a, c], 1), np.stack([a, b, c], 1))[keep]
    return tri.astype(np.uint32) if len(tri) else None


def mesh(data: bytes, table: int, scale: float) -> Batch | None:
    n = len(data)
    if table < 0 or table + TABLE > n:
        return None
    vertices = struct.unpack_from(">I", data, table + 0x24)[0]
    dl_size = struct.unpack_from(">I", data, table + 0x28)[0]
    uv_at = _ptr(data, table + 0x20)
    dl_at = _ptr(data, table + 0x2C)
    buffer = table + TABLE
    if not (0 < vertices <= MAX_VERTICES):
        return None
    if buffer + vertices * VERTEX > n or uv_at < 0 or uv_at + vertices * 16 > n:
        return None
    raw = np.frombuffer(data, ">i2", vertices * 6, buffer).reshape(vertices, 6).astype(np.float32)
    positions = raw[:, :3] * scale
    normals = raw[:, 3:] * NORMAL_SCALE
    # blended slots: the buffer holds their contribution runs, not the vertex - take a copy
    rows = struct.unpack_from(">I", data, table + 0x10)[0]
    blend = _ptr(data, table + 0x14)
    if rows and blend >= 0 and blend + rows * BLEND_ROW <= n:
        lists = (blend + rows * BLEND_ROW + ALIGN - 1) & ~(ALIGN - 1)
        for k in range(rows):
            row = blend + k * BLEND_ROW
            count = struct.unpack_from(">I", data, row + 4)[0]
            run = _ptr(data, row + 8)
            slots_end = lists + 2 * count
            weights_end = ((slots_end + ALIGN - 1) & ~(ALIGN - 1)) + count
            if run + count * VERTEX > n or weights_end > n:
                break
            slots = np.frombuffer(data, ">u2", count, lists).astype(np.int64)
            lists = (weights_end + ALIGN - 1) & ~(ALIGN - 1)
            ok = slots < vertices
            copy = np.frombuffer(data, ">i2", count * 6, run).reshape(count, 6).astype(np.float32)
            positions[slots[ok]] = copy[ok, :3] * scale
            normals[slots[ok]] = copy[ok, 3:] * NORMAL_SCALE
    uvs = np.frombuffer(data, ">f4", vertices * 4, uv_at).reshape(vertices, 4)[:, :2]
    indices = _strip(data, dl_at, dl_size, vertices)
    if indices is None:
        return None
    return Batch(
        None,
        np.ascontiguousarray(positions),
        np.ascontiguousarray(normals),
        np.ascontiguousarray(uvs.astype(np.float32)),
        indices.ravel(),
    )


def model(data: bytes) -> Model | None:
    if not is_bmsh(data):
        return None
    scale = struct.unpack_from(">f", data, 8)[0]
    out = Model()
    for shader, table in tables(data):
        m = mesh(data, table, scale)
        if m is None:
            out.warnings.append(f"batch table at {table:#x} did not read")
            continue
        m.shader = shader
        out.batches.append(m)
    return out
