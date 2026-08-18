"""J3D BMD/BDL model parser (Nintendo's GameCube/Wii model format).

Sections used: INF1 (scene graph), VTX1 (vertex arrays), EVP1 (envelopes /
skin weights), DRW1 (draw matrix table), JNT1 (joints), SHP1 (shapes = draw
batches with GX display lists), MAT3 (materials), TEX1 (textures).
BDL additionally has MDL3 (precompiled display lists) which we ignore since
SHP1 carries the same geometry.

Layout references: SuperBMD, noclip.website's j3d loader, and the JSystem
decompilation. All integers big-endian.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import bti

# GX vertex attributes
VA_PNMTXIDX = 0
VA_TEX0MTXIDX = 1
VA_TEX7MTXIDX = 8
VA_POS = 9
VA_NRM = 10
VA_CLR0 = 11
VA_CLR1 = 12
VA_TEX0 = 13
VA_TEX7 = 20
VA_NBT = 25
VA_NULL = 0xFF

# GX primitive opcodes
PRIM_QUADS = 0x80
PRIM_TRIANGLES = 0x90
PRIM_TRISTRIP = 0x98
PRIM_TRIFAN = 0xA0
PRIM_LINES = 0xA8
PRIM_LINESTRIP = 0xB0
PRIM_POINTS = 0xB8

_COMP_TYPE_DTYPE = {0: ">u1", 1: ">i1", 2: ">u2", 3: ">i2", 4: ">f4"}


class J3DError(Exception):
    pass


def _read_string_table(data: bytes, off: int) -> list[str]:
    (count,) = struct.unpack_from(">H", data, off)
    names = []
    for i in range(count):
        _h, s_off = struct.unpack_from(">HH", data, off + 4 + i * 4)
        start = off + s_off
        end = data.find(b"\x00", start)
        raw = data[start : end if end >= 0 else start]
        try:
            names.append(raw.decode("shift_jis"))
        except UnicodeDecodeError:
            names.append(raw.decode("latin-1"))
    return names


@dataclass
class Joint:
    index: int
    name: str
    parent: int | None
    scale: tuple[float, float, float]
    rotation: tuple[float, float, float]  # radians, applied X then Y then Z (R = Rz*Ry*Rx)
    translation: tuple[float, float, float]
    kind: int
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    children: list[int] = field(default_factory=list)
    local: np.ndarray | None = None  # 4x4
    world: np.ndarray | None = None  # 4x4 bind pose


@dataclass
class Envelope:
    joints: list[int]
    weights: list[float]


@dataclass
class DrawMatrix:
    weighted: bool
    index: int  # joint index, or envelope index if weighted


@dataclass
class Primitive:
    opcode: int
    # attribute -> array of indices (or direct values for matrix index attribs), len = vertex count
    attrs: dict[int, np.ndarray]


@dataclass
class Packet:
    matrix_table: list[int]  # DRW1 indices (0xFFFF = inherit from previous packet)
    primitives: list[Primitive]


@dataclass
class Shape:
    index: int
    matrix_type: int
    attributes: list[tuple[int, int]]  # (attribute, index type: 1 direct, 2 idx8, 3 idx16)
    packets: list[Packet]
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    material: int | None = None  # filled from INF1
    joint: int | None = None  # joint in scope when the shape appears in INF1


@dataclass
class TevOrder:
    texcoord: int
    texmap: int
    color_chan: int


@dataclass
class TexGen:
    type: int
    source: int  # 0 POS, 1 NRM, 2 BINRM, 3 TANGENT, 4..11 TEX0..7, 12.. TEXCOORDn, 19/20 COLORn
    matrix: int

    @property
    def uv_set(self) -> int | None:
        """The vertex UV set this texgen reads, or None if it's generated (normals etc.)."""
        return self.source - 4 if 4 <= self.source <= 11 else None


@dataclass
class TexMtx:
    """J3D texture matrix (SRT form). uv' = S*R*(uv - center) + center + trans."""

    center: tuple[float, float]
    scale: tuple[float, float]
    rotation: float  # degrees
    translation: tuple[float, float]

    @property
    def identity(self) -> bool:
        return (
            abs(self.scale[0] - 1) < 1e-6
            and abs(self.scale[1] - 1) < 1e-6
            and abs(self.rotation) < 1e-6
            and abs(self.translation[0]) < 1e-6
            and abs(self.translation[1]) < 1e-6
        )

    def apply(self, uv: np.ndarray) -> np.ndarray:
        c = np.array(self.center, np.float64)
        r = np.radians(self.rotation)
        cs, sn = np.cos(r), np.sin(r)
        m = np.array([[cs, -sn], [sn, cs]]) * np.array(self.scale)[None, :]
        return (uv - c) @ m.T + c + np.array(self.translation)


@dataclass
class Material:
    index: int
    name: str
    tex_slots: list[int]  # 8 entries: TEX1 texture index or -1
    tev_orders: list[TevOrder]
    texgens: list[TexGen]
    cull_mode: int  # 0 none, 1 front, 2 back, 3 all
    blend_type: int  # 0 none, 1 blend, 2 logic, 3 subtract
    blend_src: int
    blend_dst: int
    alpha_comp0: int  # GX compare: 7 = ALWAYS
    alpha_ref0: int
    alpha_op: int
    alpha_comp1: int
    alpha_ref1: int
    zwrite: bool
    material_color: tuple[float, float, float, float]
    tex_matrices: list = field(default_factory=lambda: [None] * 10)  # TexMtx per slot

    def texgen_matrix(self, g: TexGen) -> TexMtx | None:
        """The SRT matrix a texgen uses (None for identity / non-SRT matrices)."""
        if 30 <= g.matrix < 60 and (g.matrix - 30) % 3 == 0:
            k = (g.matrix - 30) // 3
            if k < len(self.tex_matrices):
                return self.tex_matrices[k]
        return None

    def detail(self, textures: list | None = None) -> tuple[int, int, TexMtx | None] | None:
        """A second texture layer multiplied over the base color in the same UV space
        (Wind Waker eyes: eye-white shape x pupil): (TEX1 index, uv set, texmatrix)."""
        d = self.diffuse(textures)
        if d is None:
            return None
        base_tex, base_uv = d
        for o in self.tev_orders:
            if not (0 <= o.texmap < 8) or self.tex_slots[o.texmap] < 0:
                continue
            tex = self.tex_slots[o.texmap]
            if tex == base_tex or not (0 <= o.texcoord < len(self.texgens)):
                continue
            g = self.texgens[o.texcoord]
            if g.uv_set != base_uv:
                continue
            if g.matrix != 60 and self.texgen_matrix(g) is None:
                continue  # projection / non-SRT matrix: can't bake
            return tex, base_uv, self.texgen_matrix(g)
        return None

    def diffuse(self, textures: list | None = None) -> tuple[int, int] | None:
        """(TEX1 texture index, uv set) for the best "base color" texture: a TEV
        stage sampling a texture through a real vertex-UV texgen, preferring an
        identity texture matrix (animated/scrolling layers like pupils use a
        matrix), then colour over intensity-only formats (highlight/shade layers),
        then TEV stage order. Falls back to the first bound texture."""
        best: tuple[tuple[int, int, int], int, int] | None = None  # (rank, tex, uv)
        for stage, o in enumerate(self.tev_orders):
            if not (0 <= o.texmap < 8) or self.tex_slots[o.texmap] < 0:
                continue
            if 0 <= o.texcoord < len(self.texgens):
                g = self.texgens[o.texcoord]
                uv = g.uv_set
                if uv is None:
                    continue
                tm = self.texgen_matrix(g)
                ident = g.matrix == 60 or (tm is not None and tm.identity)
                tex = self.tex_slots[o.texmap]
                gray = 1
                if textures is not None and tex < len(textures):
                    gray = 1 if textures[tex].fmt in (0, 1, 2, 3) else 0
                rank = (0 if ident else 1, gray, stage)
                if best is None or rank < best[0]:
                    best = (rank, tex, uv)
        if best is not None:
            return best[1], best[2]
        for o in self.tev_orders:
            if 0 <= o.texmap < 8 and self.tex_slots[o.texmap] >= 0:
                return self.tex_slots[o.texmap], 0
        for t in self.tex_slots:
            if t >= 0:
                return t, 0
        return None


@dataclass
class VertexData:
    pos: np.ndarray | None = None  # (N,3) f32
    nrm: np.ndarray | None = None  # (N,3) f32
    clr: list[np.ndarray | None] = field(default_factory=lambda: [None, None])  # (N,4) f32 0..1
    tex: list[np.ndarray | None] = field(default_factory=lambda: [None] * 8)  # (N,2) f32


@dataclass
class Model:
    name: str
    magic: str
    joints: list[Joint]
    root_joints: list[int]
    vertices: VertexData
    envelopes: list[Envelope]
    inv_bind: list[np.ndarray]  # from EVP1, indexed by joint (may be missing -> identity)
    draw_matrices: list[DrawMatrix]
    shapes: list[Shape]
    materials: list[Material]
    textures: list[bti.BtiTexture]
    inf1: list[tuple[int, int]]

    @property
    def triangle_count(self) -> int:
        n = 0
        for s in self.shapes:
            for p in s.packets:
                for pr in p.primitives:
                    n += primitive_triangle_count(pr)
        return n


def primitive_triangle_count(pr: Primitive) -> int:
    count = len(next(iter(pr.attrs.values()))) if pr.attrs else 0
    if pr.opcode == PRIM_TRIANGLES:
        return count // 3
    if pr.opcode in (PRIM_TRISTRIP, PRIM_TRIFAN):
        return max(0, count - 2)
    if pr.opcode == PRIM_QUADS:
        return count // 4 * 2
    return 0


def triangulate(opcode: int, n: int) -> np.ndarray:
    """Return (T,3) local vertex indices for a primitive of n vertices."""
    if n < 3:
        return np.zeros((0, 3), np.int64)
    if opcode == PRIM_TRIANGLES:
        m = n - n % 3
        return np.arange(m).reshape(-1, 3)
    if opcode == PRIM_TRISTRIP:
        i = np.arange(n - 2)
        a = i
        b = np.where(i % 2 == 0, i + 1, i + 2)
        c = np.where(i % 2 == 0, i + 2, i + 1)
        return np.stack([a, b, c], axis=1)
    if opcode == PRIM_TRIFAN:
        i = np.arange(1, n - 1)
        return np.stack([np.zeros_like(i), i, i + 1], axis=1)
    if opcode == PRIM_QUADS:
        q = np.arange(n // 4) * 4
        t1 = np.stack([q, q + 1, q + 2], axis=1)
        t2 = np.stack([q, q + 2, q + 3], axis=1)
        return np.concatenate([t1, t2], axis=0)
    return np.zeros((0, 3), np.int64)


# ---------------------------------------------------------------------------
# section parsers
# ---------------------------------------------------------------------------


def _sections(data: bytes) -> dict[str, tuple[int, int]]:
    magic = data[:8]
    if magic[:4] not in (b"J3D2", b"J3D1"):
        raise J3DError("not a J3D file")
    (count,) = struct.unpack_from(">I", data, 0x0C)
    out: dict[str, tuple[int, int]] = {}
    off = 0x20
    for _ in range(count):
        if off + 8 > len(data):
            break
        tag = data[off : off + 4].decode("ascii", "replace")
        (size,) = struct.unpack_from(">I", data, off + 4)
        if size < 8:
            break
        out[tag] = (off, size)
        off += size
    return out


def _parse_inf1(data: bytes, off: int) -> list[tuple[int, int]]:
    (hier_off,) = struct.unpack_from(">I", data, off + 0x14)
    p = off + hier_off
    out = []
    while True:
        t, i = struct.unpack_from(">HH", data, p)
        p += 4
        out.append((t, i))
        if t == 0:
            break
    return out


def _parse_vtx1(data: bytes, off: int, size: int) -> VertexData:
    (fmt_off,) = struct.unpack_from(">I", data, off + 0x08)
    offsets = list(struct.unpack_from(">13I", data, off + 0x0C))
    # array order: pos, nrm, nbt, clr0, clr1, tex0..7
    attr_to_slot = {VA_POS: 0, VA_NRM: 1, VA_NBT: 2, VA_CLR0: 3, VA_CLR1: 4}
    for t in range(8):
        attr_to_slot[VA_TEX0 + t] = 5 + t
    fmts = {}
    p = off + fmt_off
    while True:
        attr, comp_count, comp_type, shift = struct.unpack_from(">IIIB", data, p)
        p += 16
        if attr == VA_NULL:
            break
        fmts[attr] = (comp_count, comp_type, shift)

    section_end = off + size
    vd = VertexData()

    def array_bytes(slot: int) -> bytes:
        start = offsets[slot]
        if start == 0:
            return b""
        end = section_end - off
        for o in offsets:
            if start < o < end:
                end = o
        return data[off + start : off + end]

    for attr, (comp_count, comp_type, shift) in fmts.items():
        slot = attr_to_slot.get(attr)
        if slot is None:
            continue
        raw = array_bytes(slot)
        if not raw:
            continue
        if attr in (VA_CLR0, VA_CLR1):
            arr = _decode_colors(raw, comp_type)
            vd.clr[attr - VA_CLR0] = arr
            continue
        if attr == VA_POS:
            ncomp = 2 if comp_count == 0 else 3
        elif attr == VA_NRM:
            ncomp = 3 if comp_count == 0 else 9
        elif attr == VA_NBT:
            ncomp = 9
        else:  # tex
            ncomp = 1 if comp_count == 0 else 2
        dt = _COMP_TYPE_DTYPE.get(comp_type)
        if dt is None:
            raise J3DError(f"bad component type {comp_type}")
        item = np.dtype(dt).itemsize
        n = len(raw) // (item * ncomp)
        arr = np.frombuffer(raw, dtype=dt, count=n * ncomp).reshape(n, ncomp).astype(np.float32)
        if comp_type != 4 and shift:
            arr /= float(1 << shift)
        if attr == VA_POS:
            if ncomp == 2:
                arr = np.concatenate([arr, np.zeros((n, 1), np.float32)], axis=1)
            vd.pos = arr
        elif attr == VA_NRM:
            vd.nrm = arr[:, :3] if ncomp == 9 else arr
        elif attr == VA_NBT:
            if vd.nrm is None:
                vd.nrm = arr[:, :3]
        else:
            if ncomp == 1:
                arr = np.concatenate([arr, np.zeros((n, 1), np.float32)], axis=1)
            vd.tex[attr - VA_TEX0] = arr
    return vd


def _decode_colors(raw: bytes, comp_type: int) -> np.ndarray:
    if comp_type == 0:  # RGB565
        v = np.frombuffer(raw, ">u2").astype(np.uint32)
        r = ((v >> 11) & 0x1F) * 255 // 31
        g = ((v >> 5) & 0x3F) * 255 // 63
        b = (v & 0x1F) * 255 // 31
        a = np.full_like(r, 255)
    elif comp_type == 1:  # RGB8
        n = len(raw) // 3
        v = np.frombuffer(raw, np.uint8, n * 3).reshape(n, 3).astype(np.uint32)
        r, g, b = v[:, 0], v[:, 1], v[:, 2]
        a = np.full_like(r, 255)
    elif comp_type == 2:  # RGBX8
        n = len(raw) // 4
        v = np.frombuffer(raw, np.uint8, n * 4).reshape(n, 4).astype(np.uint32)
        r, g, b = v[:, 0], v[:, 1], v[:, 2]
        a = np.full_like(r, 255)
    elif comp_type == 3:  # RGBA4
        v = np.frombuffer(raw, ">u2").astype(np.uint32)
        r = ((v >> 12) & 0xF) * 17
        g = ((v >> 8) & 0xF) * 17
        b = ((v >> 4) & 0xF) * 17
        a = (v & 0xF) * 17
    elif comp_type == 4:  # RGBA6
        n = len(raw) // 3
        v = np.frombuffer(raw, np.uint8, n * 3).reshape(n, 3).astype(np.uint32)
        packed = (v[:, 0] << 16) | (v[:, 1] << 8) | v[:, 2]
        r = ((packed >> 18) & 0x3F) * 255 // 63
        g = ((packed >> 12) & 0x3F) * 255 // 63
        b = ((packed >> 6) & 0x3F) * 255 // 63
        a = (packed & 0x3F) * 255 // 63
    elif comp_type == 5:  # RGBA8
        n = len(raw) // 4
        v = np.frombuffer(raw, np.uint8, n * 4).reshape(n, 4).astype(np.uint32)
        r, g, b, a = v[:, 0], v[:, 1], v[:, 2], v[:, 3]
    else:
        raise J3DError(f"bad color type {comp_type}")
    return (np.stack([r, g, b, a], axis=1).astype(np.float32) / 255.0).astype(np.float32)


def _parse_evp1(data: bytes, off: int) -> tuple[list[Envelope], dict[int, np.ndarray]]:
    (count,) = struct.unpack_from(">H", data, off + 0x08)
    counts_off, idx_off, w_off, mtx_off = struct.unpack_from(">4I", data, off + 0x0C)
    envs = []
    p_idx = off + idx_off
    p_w = off + w_off
    max_joint = -1
    for i in range(count):
        n = data[off + counts_off + i]
        js = list(struct.unpack_from(f">{n}H", data, p_idx))
        ws = list(struct.unpack_from(f">{n}f", data, p_w))
        p_idx += 2 * n
        p_w += 4 * n
        if js:
            max_joint = max(max_joint, max(js))
        envs.append(Envelope(js, ws))
    inv: dict[int, np.ndarray] = {}
    if mtx_off:
        for j in range(max_joint + 1):
            m = struct.unpack_from(">12f", data, off + mtx_off + j * 48)
            inv[j] = np.array([m[0:4], m[4:8], m[8:12], [0, 0, 0, 1]], dtype=np.float64)
    return envs, inv


def _parse_drw1(data: bytes, off: int) -> list[DrawMatrix]:
    (count,) = struct.unpack_from(">H", data, off + 0x08)
    w_off, i_off = struct.unpack_from(">II", data, off + 0x0C)
    out = []
    for i in range(count):
        weighted = data[off + w_off + i] != 0
        (idx,) = struct.unpack_from(">H", data, off + i_off + i * 2)
        out.append(DrawMatrix(weighted, idx))
    return out


def _parse_jnt1(data: bytes, off: int) -> list[Joint]:
    (count,) = struct.unpack_from(">H", data, off + 0x08)
    j_off, remap_off, str_off = struct.unpack_from(">III", data, off + 0x0C)
    names = _read_string_table(data, off + str_off) if str_off else []
    joints = []
    for i in range(count):
        p = off + j_off + i * 0x40
        kind = struct.unpack_from(">H", data, p)[0]
        sx, sy, sz = struct.unpack_from(">3f", data, p + 0x04)
        rx, ry, rz = struct.unpack_from(">3h", data, p + 0x10)
        tx, ty, tz = struct.unpack_from(">3f", data, p + 0x18)
        bmin = struct.unpack_from(">3f", data, p + 0x28)
        bmax = struct.unpack_from(">3f", data, p + 0x34)
        k = math.pi / 32768.0
        joints.append(
            Joint(
                index=i,
                name=names[i] if i < len(names) else f"joint{i}",
                parent=None,
                scale=(sx, sy, sz),
                rotation=(rx * k, ry * k, rz * k),
                translation=(tx, ty, tz),
                kind=kind,
                bbox_min=bmin,
                bbox_max=bmax,
            )
        )
    return joints


def _parse_shp1(data: bytes, off: int) -> list[Shape]:
    (count,) = struct.unpack_from(">H", data, off + 0x08)
    (
        shp_off,
        _remap_off,
        _unk,
        attr_off,
        mtx_tbl_off,
        prim_off,
        mtx_data_off,
        pkt_loc_off,
    ) = struct.unpack_from(">8I", data, off + 0x0C)
    shapes = []
    for i in range(count):
        p = off + shp_off + i * 0x28
        (
            mtype,
            _pad,
            n_packets,
            a_off,
            first_mtx,
            first_pkt,
        ) = struct.unpack_from(">BBHHHH", data, p)
        bmin = struct.unpack_from(">3f", data, p + 0x10)
        bmax = struct.unpack_from(">3f", data, p + 0x1C)
        # attribute list
        attrs: list[tuple[int, int]] = []
        q = off + attr_off + a_off
        while True:
            a, t = struct.unpack_from(">II", data, q)
            q += 8
            if a == VA_NULL:
                break
            attrs.append((a, t))
        packets = []
        for k in range(n_packets):
            md = off + mtx_data_off + (first_mtx + k) * 8
            _unk2, m_count, m_first = struct.unpack_from(">HHI", data, md)
            mtx_table = list(
                struct.unpack_from(f">{m_count}H", data, off + mtx_tbl_off + m_first * 2)
            )
            pl = off + pkt_loc_off + (first_pkt + k) * 8
            p_size, p_off = struct.unpack_from(">II", data, pl)
            dl = data[off + prim_off + p_off : off + prim_off + p_off + p_size]
            prims = _parse_display_list(dl, attrs)
            packets.append(Packet(mtx_table, prims))
        shapes.append(Shape(i, mtype, attrs, packets, bmin, bmax))
    return shapes


def _parse_display_list(dl: bytes, attrs: list[tuple[int, int]]) -> list[Primitive]:
    # Build a numpy dtype for one vertex
    fields = []
    for a, t in attrs:
        if t == 1:  # direct: only valid for matrix index attributes (u8)
            if a <= VA_TEX7MTXIDX:
                fields.append((f"a{a}", ">u1"))
            else:
                raise J3DError(f"direct vertex data for attribute {a} not supported")
        elif t == 2:
            fields.append((f"a{a}", ">u1"))
        elif t == 3:
            fields.append((f"a{a}", ">u2"))
        elif t == 0:
            continue
        else:
            raise J3DError(f"bad attribute index type {t}")
    vdt = np.dtype(fields)
    stride = vdt.itemsize
    prims = []
    pos = 0
    n = len(dl)
    while pos + 3 <= n:
        op = dl[pos]
        if op == 0:
            break
        count = dl[pos + 1] << 8 | dl[pos + 2]
        pos += 3
        end = pos + count * stride
        if end > n:
            break
        arr = np.frombuffer(dl, dtype=vdt, count=count, offset=pos)
        pos = end
        prims.append(Primitive(op, {a: arr[f"a{a}"].astype(np.int64) for a, t in attrs if t != 0}))
    return prims


def _parse_mat3(data: bytes, off: int) -> list[Material]:
    (count,) = struct.unpack_from(">H", data, off + 0x08)
    offs = struct.unpack_from(">30I", data, off + 0x0C)
    (
        mat_off,
        remap_off,
        str_off,
        _ind_off,
        cull_off,
        matcol_off,
        _nchan_off,
        _chan_off,
        _amb_off,
        _light_off,
        _ntexgen_off,
        texgen_off,
        _posttexgen_off,
        texmtx_off,
        _posttexmtx_off,
        texidx_off,
        tevorder_off,
        _tevcol_off,
        _konst_off,
        _ntev_off,
        _tevstage_off,
        _swap_off,
        _swaptbl_off,
        _fog_off,
        alphacomp_off,
        blend_off,
        zmode_off,
        _zcomp_off,
        _dither_off,
        _nbt_off,
    ) = offs
    names = _read_string_table(data, off + str_off) if str_off else []
    mats = []
    for i in range(count):
        (entry,) = struct.unpack_from(">H", data, off + remap_off + i * 2)
        p = off + mat_off + entry * 0x14C
        cull_idx = data[p + 0x01]
        zmode_idx = data[p + 0x06]
        matcol_idx = struct.unpack_from(">H", data, p + 0x08)[0]
        texgen_idx = struct.unpack_from(">8H", data, p + 0x28)
        tex_idx = struct.unpack_from(">8H", data, p + 0x84)
        tevorder_idx = struct.unpack_from(">16H", data, p + 0xBC)
        # 0x124 tev swap table[4], 0x12C 12 unused u16s, then:
        alpha_idx = struct.unpack_from(">H", data, p + 0x146)[0]
        blend_idx = struct.unpack_from(">H", data, p + 0x148)[0]

        slots = []
        for ti in tex_idx:
            if ti == 0xFFFF or not texidx_off:
                slots.append(-1)
            else:
                slots.append(struct.unpack_from(">H", data, off + texidx_off + ti * 2)[0])
        texgens = []
        for gi in texgen_idx:
            if gi == 0xFFFF or not texgen_off:
                continue
            gt, gs, gm = struct.unpack_from(">BBB", data, off + texgen_off + gi * 4)
            texgens.append(TexGen(gt, gs, gm))
        texmtx_idx = struct.unpack_from(">10H", data, p + 0x48)
        tex_matrices: list = []
        for mi in texmtx_idx:
            if mi == 0xFFFF or not texmtx_off:
                tex_matrices.append(None)
                continue
            q = off + texmtx_off + mi * 0x64
            cx, cy, _cz, sx, sy = struct.unpack_from(">5f", data, q + 4)
            (rot,) = struct.unpack_from(">h", data, q + 24)
            tx, ty = struct.unpack_from(">2f", data, q + 28)
            tex_matrices.append(TexMtx((cx, cy), (sx, sy), rot * 180.0 / 32768.0, (tx, ty)))
        orders = []
        for oi in tevorder_idx:
            if oi == 0xFFFF or not tevorder_off:
                continue
            tc, tm, cc = struct.unpack_from(">BBB", data, off + tevorder_off + oi * 4)
            orders.append(TevOrder(tc, tm, cc))
        cull = struct.unpack_from(">I", data, off + cull_off + cull_idx * 4)[0] if cull_off else 2
        if blend_off and blend_idx != 0xFFFF:
            bt, bs, bd, _bl = struct.unpack_from(">4B", data, off + blend_off + blend_idx * 4)
        else:
            bt, bs, bd = 0, 0, 0
        if alphacomp_off and alpha_idx != 0xFFFF:
            c0, r0, aop, c1, r1 = struct.unpack_from(
                ">5B", data, off + alphacomp_off + alpha_idx * 8
            )
        else:
            c0, r0, aop, c1, r1 = 7, 0, 0, 7, 0
        zwrite = True
        if zmode_off and zmode_idx != 0xFF:
            _zen, _zfunc, zw = struct.unpack_from(">3B", data, off + zmode_off + zmode_idx * 4)
            zwrite = bool(zw)
        mcol = (1.0, 1.0, 1.0, 1.0)
        if matcol_off and matcol_idx != 0xFFFF:
            r, g, b, a = struct.unpack_from(">4B", data, off + matcol_off + matcol_idx * 4)
            mcol = (r / 255, g / 255, b / 255, a / 255)
        mats.append(
            Material(
                index=i,
                name=names[i] if i < len(names) else f"material{i}",
                tex_slots=slots,
                tev_orders=orders,
                texgens=texgens,
                cull_mode=cull,
                blend_type=bt,
                blend_src=bs,
                blend_dst=bd,
                alpha_comp0=c0,
                alpha_ref0=r0,
                alpha_op=aop,
                alpha_comp1=c1,
                alpha_ref1=r1,
                zwrite=zwrite,
                material_color=mcol,
                tex_matrices=tex_matrices,
            )
        )
    return mats


def _parse_mat2_fallback(data: bytes, off: int, n_textures: int) -> list[Material]:
    """Old 'bmd2' files carry a MAT2 section whose entry layout we don't parse.
    Produce placeholder materials (names from its string table when possible,
    texture i -> material i as a guess) so the geometry still exports."""
    (count,) = struct.unpack_from(">H", data, off + 0x08)
    names: list[str] = []
    try:
        str_off = struct.unpack_from(">I", data, off + 0x14)[0]
        if str_off:
            names = _read_string_table(data, off + str_off)
    except Exception:  # noqa: BLE001
        names = []
    mats = []
    for i in range(count):
        slots = [-1] * 8
        if i < n_textures:
            slots[0] = i
        mats.append(
            Material(
                index=i,
                name=names[i] if i < len(names) else f"material{i}",
                tex_slots=slots,
                tev_orders=[TevOrder(0, 0, 0)],
                texgens=[TexGen(1, 4, 60)],
                cull_mode=2,
                blend_type=0,
                blend_src=0,
                blend_dst=0,
                alpha_comp0=7,
                alpha_ref0=0,
                alpha_op=0,
                alpha_comp1=7,
                alpha_ref1=0,
                zwrite=True,
                material_color=(1.0, 1.0, 1.0, 1.0),
            )
        )
    return mats


def _parse_tex1(data: bytes, off: int) -> list[bti.BtiTexture]:
    (count,) = struct.unpack_from(">H", data, off + 0x08)
    hdr_off, str_off = struct.unpack_from(">II", data, off + 0x0C)
    names = _read_string_table(data, off + str_off) if str_off else []
    texs = []
    for i in range(count):
        name = names[i] if i < len(names) else f"texture{i}"
        texs.append(bti.parse(data, off + hdr_off + i * 0x20, name))
    return texs


# ---------------------------------------------------------------------------


def _joint_matrices(joints: list[Joint], root_joints: list[int]) -> None:
    def local_matrix(j: Joint) -> np.ndarray:
        sx, sy, sz = j.scale
        rx, ry, rz = j.rotation
        cx, sxr = math.cos(rx), math.sin(rx)
        cy, syr = math.cos(ry), math.sin(ry)
        cz, szr = math.cos(rz), math.sin(rz)
        Rx = np.array([[1, 0, 0], [0, cx, -sxr], [0, sxr, cx]])
        Ry = np.array([[cy, 0, syr], [0, 1, 0], [-syr, 0, cy]])
        Rz = np.array([[cz, -szr, 0], [szr, cz, 0], [0, 0, 1]])
        R = Rz @ Ry @ Rx
        m = np.eye(4)
        m[:3, :3] = R @ np.diag([sx, sy, sz])
        m[:3, 3] = j.translation
        return m

    for j in joints:
        j.local = local_matrix(j)

    def walk(idx: int, parent_world: np.ndarray) -> None:
        j = joints[idx]
        j.world = parent_world @ j.local
        for c in j.children:
            walk(c, j.world)

    for r in root_joints:
        walk(r, np.eye(4))
    for j in joints:  # orphans (shouldn't happen)
        if j.world is None:
            j.world = j.local


def parse(data: bytes, name: str = "") -> Model:
    secs = _sections(data)
    for req in ("INF1", "VTX1", "JNT1", "SHP1", "TEX1"):
        if req not in secs:
            raise J3DError(f"missing section {req}")
    if "MAT3" not in secs and "MAT2" not in secs:
        raise J3DError("missing section MAT3")
    inf1 = _parse_inf1(data, secs["INF1"][0])
    vtx = _parse_vtx1(data, *secs["VTX1"])
    envs, inv = _parse_evp1(data, secs["EVP1"][0]) if "EVP1" in secs else ([], {})
    drw = _parse_drw1(data, secs["DRW1"][0]) if "DRW1" in secs else []
    joints = _parse_jnt1(data, secs["JNT1"][0])
    shapes = _parse_shp1(data, secs["SHP1"][0])
    texs = _parse_tex1(data, secs["TEX1"][0])
    if "MAT3" in secs:
        mats = _parse_mat3(data, secs["MAT3"][0])
    else:
        mats = _parse_mat2_fallback(data, secs["MAT2"][0], len(texs))

    # scene graph: joint parents, shape->material / joint
    stack: list[tuple[int, int]] = []  # (type, index) of open nodes
    cur_joint: int | None = None
    cur_mat: int | None = None
    root_joints: list[int] = []
    last: tuple[int, int] | None = None
    for t, i in inf1:
        if t == 0:
            break
        if t == 1:  # open child of `last`
            if last is not None:
                stack.append(last)
        elif t == 2:
            if stack:
                stack.pop()
            # restore joint context from the enclosing nodes; materials are
            # "last seen" (shapes may be siblings of their material node)
            cur_joint = next((idx for tt, idx in reversed(stack) if tt == 0x10), cur_joint)
        elif t == 0x10:
            parent = next((idx for tt, idx in reversed(stack) if tt == 0x10), None)
            if i < len(joints):
                joints[i].parent = parent
                if parent is None:
                    root_joints.append(i)
                else:
                    joints[parent].children.append(i)
            cur_joint = i
        elif t == 0x11:
            cur_mat = i
        elif t == 0x12 and i < len(shapes):
            shapes[i].material = cur_mat
            shapes[i].joint = cur_joint
        last = (t, i)
    if not root_joints and joints:
        root_joints = [0]
    _joint_matrices(joints, root_joints)

    inv_list = []
    for j in range(len(joints)):
        try:
            inv_list.append(inv.get(j, np.linalg.inv(joints[j].world)))
        except np.linalg.LinAlgError:
            inv_list.append(inv.get(j, np.linalg.pinv(joints[j].world)))
    if not drw:
        drw = [DrawMatrix(False, 0)]
    return Model(
        name=name,
        magic=data[:8].decode("ascii", "replace"),
        joints=joints,
        root_joints=root_joints,
        vertices=vtx,
        envelopes=envs,
        inv_bind=inv_list,
        draw_matrices=drw,
        shapes=shapes,
        materials=mats,
        textures=texs,
        inf1=inf1,
    )
