"""Luigi's Mansion ``.mdl`` character models (magic 0x04B40000, big-endian).

Layout (offsets in the 0x80-byte header):

    0x00 u32 magic         0x04 u16 face count
    0x08 u16 node count    0x0A packet count   0x0C weight count   0x0E joint count
    0x10 u16 positions     0x12 normals        0x14 colours        0x16 texcoords
    0x20 u16 textures      0x24 samplers       0x26 draw elements  0x28 materials  0x2A shapes
    0x30 node table (16 B each)       0x34 packets (32 B each; packet count x 2, LOD set second)
    0x38 joint matrices (3x4 f32)     0x3C weights (f32)   0x40 weight joints (u16)
    0x44 weight counts (u8)           0x48 positions (f32x3, LOD positions follow)
    0x4C normals  0x50 colours (RGBA8)  0x54 texcoords (f32x2)
    0x60 texture offset table (u32)   0x68 materials (0x120 B)   0x6C samplers (8 B)
    0x70 shapes (8 B)                 0x74 draw elements (u16 material, u16 shape)

A node is (index, has-child, next-sibling delta, pad, draw element count, first draw element)
in depth-first order; its joint matrix is the same index into the matrix table.  A draw
element pairs a material with a shape; a shape owns a run of packets, each a GX display
list with the vertex layout  s8 pnmtx-slot, s8, s8, then u16 indices for the attributes in
the shape's mask (bit 1 position, 2 normal (x3 when NBT), 3 colour 0, 5/6 texcoord 0/1).
A packet's matrix slots name joints (< joint count) or weight entries (index - joint count).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture
from gcrip.formats.j3d import PRIM_QUADS, PRIM_TRIANGLES, PRIM_TRIFAN, PRIM_TRISTRIP

MAGIC = 0x04B40000

# LM's texture format byte -> GX format
LM_TO_GX = {3: 0, 4: 1, 5: 2, 6: 3, 7: 4, 8: 5, 9: 6, 10: 14}

_PRIMS = {PRIM_TRIANGLES, PRIM_TRISTRIP, PRIM_TRIFAN, PRIM_QUADS}


class LMError(Exception):
    pass


@dataclass
class Texture:
    fmt: int  # GX format
    width: int
    height: int
    data: bytes


@dataclass
class Sampler:
    texture: int
    palette: int
    wrap_u: int  # 0 clamp, 1 repeat, 2 mirror
    wrap_v: int
    min_filter: int = 0
    mag_filter: int = 0


@dataclass
class Shape:
    normal_flags: int  # 0 none, 1 normals, 3 NBT
    attr_mask: int
    packet_count: int
    packet_start: int
    unknown: int = 0


@dataclass
class Packet:
    data: bytes
    matrices: list[int]


@dataclass
class Material:
    color: tuple[int, int, int, int]
    alpha_flags: int
    tev_count: int
    samplers: list[int]  # per tev stage, 0xFFFF = none
    unknown: int = 0


@dataclass
class Node:
    index: int
    has_child: bool
    sibling_delta: int
    draw_count: int
    draw_start: int
    parent: int = -1


@dataclass
class Model:
    positions: np.ndarray
    normals: np.ndarray
    colors: np.ndarray
    texcoords: np.ndarray
    textures: list[Texture]
    samplers: list[Sampler]
    shapes: list[Shape]
    packets: list[Packet]
    draw_elements: list[tuple[int, int]]
    materials: list[Material]
    nodes: list[Node]
    matrices: np.ndarray  # (joints, 4, 4)
    weights: list[list[tuple[int, float]]]
    face_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def joint_count(self) -> int:
        return len(self.matrices)


def looks_like_mdl(head: bytes) -> bool:
    if len(head) < 0x30:
        return False
    if struct.unpack_from(">I", head, 0)[0] != MAGIC:
        return False
    node, packet, weight, joint, pos = struct.unpack_from(">5H", head, 8)
    return node > 0 and pos > 0 and node == joint


def parse(data: bytes) -> Model:
    if len(data) < 0x80 or struct.unpack_from(">I", data, 0)[0] != MAGIC:
        raise LMError("not an LM .mdl (magic)")
    (
        face_count,
        _pad,
        n_node,
        n_packet,
        n_weight,
        n_joint,
        n_pos,
        n_nrm,
        n_clr,
        n_tc,
    ) = struct.unpack_from(">10H", data, 4)
    n_tex, _p, n_samp, n_draw, n_mat, n_shape = struct.unpack_from(">6H", data, 0x20)
    (
        node_o,
        packet_o,
        matrix_o,
        weight_o,
        widx_o,
        wcnt_o,
        pos_o,
        nrm_o,
        clr_o,
        tc_o,
    ) = struct.unpack_from(">10I", data, 0x30)
    texarr_o, _p2, mat_o, samp_o, shape_o, draw_o = struct.unpack_from(">6I", data, 0x60)
    n = len(data)
    for name, off in (
        ("node", node_o),
        ("packet", packet_o),
        ("matrix", matrix_o),
        ("position", pos_o),
        ("shape", shape_o),
        ("draw element", draw_o),
    ):
        if off >= n:
            raise LMError(f"{name} table offset {off:#x} beyond file")

    def arr(off: int, count: int, dtype: str, width: int) -> np.ndarray:
        if count == 0 or off == 0:
            return np.zeros((0, width), np.float32 if dtype != ">u1" else np.uint8)
        need = count * width * np.dtype(dtype).itemsize
        if off + need > n:
            raise LMError("vertex array beyond file")
        a = np.frombuffer(data, dtype, count * width, off).reshape(count, width)
        return a.astype(np.uint8) if dtype == ">u1" else a.astype(np.float32)

    positions = arr(pos_o, n_pos, ">f4", 3)
    normals = arr(nrm_o, n_nrm, ">f4", 3)
    colors = arr(clr_o, n_clr, ">u1", 4)
    texcoords = arr(tc_o, n_tc, ">f4", 2)

    textures: list[Texture] = []
    if n_tex and texarr_o:
        offs = struct.unpack_from(f">{n_tex}I", data, texarr_o)
        for o in offs:
            fmt, _pad, w, h = struct.unpack_from(">BBHH", data, o)
            gx = LM_TO_GX.get(fmt)
            if gx is None:
                raise LMError(f"unknown texture format {fmt}")
            size = gx_texture.encoded_size(gx, w, h)
            textures.append(Texture(gx, w, h, data[o + 0x20 : o + 0x20 + size]))

    samplers = [
        Sampler(*struct.unpack_from(">HHBBBB", data, samp_o + 8 * i)) for i in range(n_samp)
    ]
    shapes = []
    for i in range(n_shape):
        nf, u1, mask, u3, pc, pb = struct.unpack_from(">BBBBHH", data, shape_o + 8 * i)
        shapes.append(Shape(nf, mask, pc, pb, u3))
    packets = []
    for i in range(n_packet * 2):
        o = packet_o + 0x20 * i
        if o + 0x20 > n:
            break
        doff, dsize, _u, mcount = struct.unpack_from(">IIHH", data, o)
        mats = list(struct.unpack_from(">10H", data, o + 12))[: min(mcount, 10)]
        if doff + dsize > n:
            raise LMError("packet data beyond file")
        packets.append(Packet(data[doff : doff + dsize], mats))
    draw_elements = [struct.unpack_from(">HH", data, draw_o + 4 * i) for i in range(n_draw)]
    materials = []
    for i in range(n_mat):
        o = mat_o + 0x120 * i
        color = tuple(data[o : o + 4])
        unk, alpha_flags, tev_count, _u3 = struct.unpack_from(">HBBB", data, o + 4)
        samps = [struct.unpack_from(">HH", data, o + 0x20 + 0x20 * k)[1] for k in range(8)]
        materials.append(Material(color, alpha_flags, tev_count, samps, unk))  # type: ignore[arg-type]

    nodes = []
    for i in range(n_node):
        idx, child, sib, _u, dc, ds = struct.unpack_from(">6H", data, node_o + 16 * i)
        nodes.append(Node(idx, bool(child), sib, dc, ds))
    _link_nodes(nodes)

    matrices = np.tile(np.eye(4, dtype=np.float32), (n_joint, 1, 1))
    if n_joint:
        raw = np.frombuffer(data, ">f4", n_joint * 12, matrix_o).reshape(n_joint, 3, 4)
        matrices[:, :3, :] = raw

    weights: list[list[tuple[int, float]]] = []
    if n_weight and wcnt_o and weight_o and widx_o:
        counts = data[wcnt_o : wcnt_o + n_weight]
        total = sum(counts)
        ws = struct.unpack_from(f">{total}f", data, weight_o)
        js = struct.unpack_from(f">{total}H", data, widx_o)
        k = 0
        for c in counts:
            weights.append(list(zip(js[k : k + c], ws[k : k + c], strict=True)))
            k += c

    return Model(
        positions,
        normals,
        colors,
        texcoords,
        textures,
        samplers,
        shapes,
        packets,
        draw_elements,
        materials,
        nodes,
        matrices,
        weights,
        face_count,
    )


def _link_nodes(nodes: list[Node]) -> None:
    """Depth-first order: has_child -> the next node is my first child; sibling_delta -> my
    next sibling is that many entries later (and shares my parent)."""
    for i, nd in enumerate(nodes):
        if nd.has_child and i + 1 < len(nodes):
            nodes[i + 1].parent = i
        if nd.sibling_delta and i + nd.sibling_delta < len(nodes):
            nodes[i + nd.sibling_delta].parent = nd.parent


def vertex_fields(model: Model, shape: Shape, lod: bool = False) -> list[tuple[str, str]]:
    """The display-list vertex layout depends on which arrays the *file* has (the shape's
    attribute mask only says which ones the shape uses): three matrix-slot bytes, then
    position, normal (+ tangent, binormal for NBT shapes), colour, texcoord."""
    if lod:
        return [("mtx", ">i1"), ("pos", ">u2"), ("nrm", ">u1")]
    fields: list[tuple[str, str]] = [("mtx", ">i1"), ("t0mtx", ">i1"), ("t1mtx", ">i1")]
    fields.append(("pos", ">u2"))
    if len(model.normals):
        fields.append(("nrm", ">u2"))
        if shape.normal_flags > 1:
            fields.append(("tan", ">u2"))
            fields.append(("bin", ">u2"))
    if len(model.colors):
        fields.append(("clr0", ">u2"))
    if len(model.texcoords):
        fields.append(("tex0", ">u2"))
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
            raise LMError(f"unknown display list opcode {op:#x} at {pos}")
        count = dl[pos + 1] << 8 | dl[pos + 2]
        pos += 3
        if pos + count * stride > n:
            raise LMError("display list primitive overruns its packet")
        out.append((op & 0xF8, np.frombuffer(dl, vdt, count, pos)))
        pos += count * stride
    return out


def decode_texture(t: Texture) -> np.ndarray:
    return gx_texture.decode(t.fmt, t.width, t.height, t.data)
