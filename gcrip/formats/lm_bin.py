"""Luigi's Mansion ``.bin`` room / furniture models.

    0x00 u8 version (2), char[11] name, then 21 u32 section offsets (0 = absent):
      0 textures (12 B: u16 w, u16 h, u8 GX format, u8, u16, u32 data offset in section)
      1 samplers (20 B: s16 texture, u16 palette, u8 wrap u, u8 wrap v, ...)
      2 positions (s16 x3)     3 normals (f32 x3)    4/5 colour 0/1 (RGBA8)
      6..9 texcoord 0..3 (f32 x2)
      10 shaders (40 B: 3 x u8, RGBA tint, u8, 8 x s16 sampler, 8 x s16)
      11 batches (24 B header: u16 faces, u16 list size / 32, u32 GX attribute mask,
         u8 normals, u8 positions, u8 uv count, u8 NBT, u32 display list offset in section)
      12 graph objects (0x8C B: s16 parent/child/next/prev, u8, u8 render flags, u16,
         scale, rotation (degrees), translation, bbox, f32, u16 part count, u16,
         u32 parts offset in section; parts = (s16 shader, s16 batch))

Section sizes are implied by the next non-zero offset, so array counts are upper bounds.
Display lists are GX with u16 indices for every attribute in the mask (u8 for the matrix
index attributes; an NBT normal is three u16, the first is the normal).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture
from gcrip.formats.j3d import PRIM_QUADS, PRIM_TRIANGLES, PRIM_TRIFAN, PRIM_TRISTRIP

_PRIMS = {PRIM_TRIANGLES, PRIM_TRISTRIP, PRIM_TRIFAN, PRIM_QUADS}

SEC_TEXTURES, SEC_SAMPLERS, SEC_POSITIONS, SEC_NORMALS = 0, 1, 2, 3
SEC_COLOR0, SEC_COLOR1, SEC_TEXCOORD0 = 4, 5, 6
SEC_SHADERS, SEC_BATCHES, SEC_GRAPH = 10, 11, 12


class LMBinError(Exception):
    pass


@dataclass
class Texture:
    width: int
    height: int
    fmt: int
    data: bytes


@dataclass
class Sampler:
    texture: int
    palette: int
    wrap_u: int
    wrap_v: int


@dataclass
class Shader:
    flags: tuple[int, int, int]
    tint: tuple[int, int, int, int]
    samplers: list[int]  # 8 entries, -1 = none


@dataclass
class Batch:
    face_count: int
    attribs: int
    use_normals: int
    use_positions: int
    uv_count: int
    nbt: int
    data: bytes


@dataclass
class GraphNode:
    parent: int
    child: int
    next: int
    prev: int
    render_flags: int
    scale: tuple[float, float, float]
    rotation: tuple[float, float, float]  # degrees
    translation: tuple[float, float, float]
    bmin: tuple[float, float, float]
    bmax: tuple[float, float, float]
    parts: list[tuple[int, int]]  # (shader, batch)


@dataclass
class Model:
    name: str
    textures: list[Texture]
    samplers: list[Sampler]
    positions: np.ndarray  # (N,3) f32
    normals: np.ndarray
    colors: list[np.ndarray]  # 2 x (N,4) u8
    texcoords: list[np.ndarray]  # 4 x (N,2) f32
    shaders: list[Shader]
    batches: dict[int, Batch]
    nodes: list[GraphNode]
    warnings: list[str] = field(default_factory=list)


def looks_like_bin(head: bytes, size: int) -> bool:
    """Sniff on the first 64 bytes: version 2, a printable name, and the 13 section
    offsets that fit in 64 bytes (positions, batches and graph present, ascending)."""
    if len(head) < 0x40 or head[0] != 2 or size < 0x60:
        return False
    if any(b and (b < 0x20 or b > 0x7E) for b in head[1:12]):
        return False
    offs = struct.unpack_from(">13I", head, 0x0C)
    if offs[SEC_POSITIONS] == 0 or offs[SEC_BATCHES] == 0 or offs[SEC_GRAPH] == 0:
        return False
    if any(o >= size for o in offs):
        return False
    used = [o for o in offs if o]
    return used == sorted(used) and used[0] >= 0x60


def parse(data: bytes) -> Model:
    n = len(data)
    if not looks_like_bin(data[:0x60], n):
        raise LMBinError("not an LM .bin")
    name = data[1:12].split(b"\0")[0].decode("ascii", "replace").strip()
    offs = list(struct.unpack_from(">21I", data, 0x0C))

    def section_end(i: int) -> int:
        nxt = [o for o in offs[i + 1 :] if o]
        return min(nxt) if nxt else n

    def count(i: int, stride: int) -> int:
        return (section_end(i) - offs[i]) // stride if offs[i] else 0

    textures = []
    to = offs[SEC_TEXTURES]
    for i in range(count(SEC_TEXTURES, 12)):
        w, h, fmt, _u8, _u16, doff = struct.unpack_from(">HHBBHI", data, to + 12 * i)
        if fmt not in gx_texture.TILE_DIMS or w == 0 or h == 0:
            break
        size = gx_texture.encoded_size(fmt, w, h)
        textures.append(Texture(w, h, fmt, data[to + doff : to + doff + size]))
    samplers = []
    so = offs[SEC_SAMPLERS]
    for i in range(count(SEC_SAMPLERS, 20)):
        samplers.append(Sampler(*struct.unpack_from(">hHBB", data, so + 20 * i)))

    def arr(i: int, dtype: str, width: int, stride: int) -> np.ndarray:
        c = count(i, stride)
        if c <= 0:
            return np.zeros((0, width), np.uint8 if dtype == ">u1" else np.float32)
        a = np.frombuffer(data, dtype, c * width, offs[i]).reshape(c, width)
        return a.astype(np.uint8) if dtype == ">u1" else a.astype(np.float32)

    positions = arr(SEC_POSITIONS, ">i2", 3, 6)
    normals = arr(SEC_NORMALS, ">f4", 3, 12)
    colors = [arr(SEC_COLOR0, ">u1", 4, 4), arr(SEC_COLOR1, ">u1", 4, 4)]
    texcoords = [arr(SEC_TEXCOORD0 + k, ">f4", 2, 8) for k in range(4)]

    shaders = []
    sho = offs[SEC_SHADERS]
    for i in range(count(SEC_SHADERS, 0x28)):
        o = sho + 0x28 * i
        f0, f1, f2 = data[o], data[o + 1], data[o + 2]
        tint = tuple(data[o + 3 : o + 7])
        samps = list(struct.unpack_from(">8h", data, o + 8))
        shaders.append(Shader((f0, f1, f2), tint, samps))  # type: ignore[arg-type]

    nodes: list[GraphNode] = []
    go = offs[SEC_GRAPH]
    if go:
        _read_nodes(data, go, nodes)

    batches: dict[int, Batch] = {}
    bo = offs[SEC_BATCHES]
    if bo:
        wanted = sorted({b for nd in nodes for _s, b in nd.parts if b >= 0})
        for bi in wanted:
            o = bo + 0x18 * bi
            if o + 0x18 > n:
                break
            fc, lsz, attribs, un, up, uv, nbt, doff = struct.unpack_from(">HHIBBBBI", data, o)
            start = bo + doff
            end = min(start + lsz * 32, n)
            batches[bi] = Batch(fc, attribs, un, up, uv, nbt, data[start:end])
    return Model(
        name, textures, samplers, positions, normals, colors, texcoords, shaders, batches, nodes
    )


def _read_nodes(data: bytes, go: int, nodes: list[GraphNode]) -> None:
    """The graph is a linked list of siblings with child pointers; walk it from node 0."""
    n = len(data)
    seen: set[int] = set()
    stack = [0]
    by_index: dict[int, GraphNode] = {}
    while stack:
        i = stack.pop()
        if i in seen or i < 0 or go + 0x8C * (i + 1) > n:
            continue
        seen.add(i)
        o = go + 0x8C * i
        parent, child, nxt, prev = struct.unpack_from(">4h", data, o)
        flags = data[o + 9]
        f = struct.unpack_from(">15f", data, o + 12)
        _unk, pc, _pad, po = struct.unpack_from(">fHHI", data, o + 72)
        parts = []
        if pc < 4096 and go + po + 4 * pc <= n:
            parts = [struct.unpack_from(">hh", data, go + po + 4 * k) for k in range(pc)]
        by_index[i] = GraphNode(
            parent, child, nxt, prev, flags, f[0:3], f[3:6], f[6:9], f[9:12], f[12:15], parts
        )
        stack.append(nxt)
        stack.append(child)
    for i in sorted(by_index):
        nodes.append(by_index[i])
    # keep parent/child/next as node-table indices; remap to positions in `nodes`
    remap = {idx: k for k, idx in enumerate(sorted(by_index))}
    for nd in nodes:
        nd.parent = remap.get(nd.parent, -1)
        nd.child = remap.get(nd.child, -1)
        nd.next = remap.get(nd.next, -1)
        nd.prev = remap.get(nd.prev, -1)


_ATTR_NAMES = {9: "pos", 10: "nrm", 11: "clr0", 12: "clr1"}


def vertex_fields(batch: Batch) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for bit in range(26):
        if not batch.attribs & (1 << bit):
            continue
        if bit == 0:
            fields.append(("mtx", ">u1"))
        elif bit <= 8:
            fields.append((f"t{bit - 1}mtx", ">u1"))
        elif bit == 10:
            fields.append(("nrm", ">u2"))
            if batch.nbt:
                fields.append(("bin", ">u2"))
                fields.append(("tan", ">u2"))
        elif bit in _ATTR_NAMES:
            fields.append((_ATTR_NAMES[bit], ">u2"))
        elif 13 <= bit <= 20:
            fields.append((f"tex{bit - 13}", ">u2"))
        elif bit == 25:
            fields.append(("nbt", ">u2"))
    return fields


def parse_display_list(dl: bytes, fields: list[tuple[str, str]]) -> list[tuple[int, np.ndarray]]:
    vdt = np.dtype(fields)
    stride = vdt.itemsize
    out = []
    pos = 0
    n = len(dl)
    while pos + 3 <= n:
        op = dl[pos]
        if op == 0:
            break
        if op & 0xF8 not in _PRIMS:
            raise LMBinError(f"unknown display list opcode {op:#x} at {pos}")
        cnt = dl[pos + 1] << 8 | dl[pos + 2]
        pos += 3
        if pos + cnt * stride > n:
            raise LMBinError("display list primitive overruns the batch")
        out.append((op & 0xF8, np.frombuffer(dl, vdt, cnt, pos)))
        pos += cnt * stride
    return out


def decode_texture(t: Texture) -> np.ndarray:
    return gx_texture.decode(t.fmt, t.width, t.height, t.data)
