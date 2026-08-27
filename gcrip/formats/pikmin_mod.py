"""Pikmin 1 ``.mod`` models (sysCommon/shapeBase.cpp `BaseShape::read` in the decompilation)
and the sibling ``.txe`` textures.

A .mod is a list of chunks, each `u32 id, u32 length` (the length covers everything up to
the next chunk, which always starts 32-byte aligned).  Every data chunk reads its count
right after the header and then aligns to 32 before the payload:

    0x0000 header      date + shape flags (payload itself aligned to 32 first)
    0x0010 positions   Vec3f        0x0011 normals  Vec3f     0x0012 NBT  3 x Vec3f
    0x0013 colours     RGBA8        0x0018..0x001F texcoord 0..7  Vec2f
    0x0020 textures    TexImg (w, h, Pikmin format, mip count, 4 x pad, size, data)
    0x0022 tex attrs   (image index, pad, tiling flags, use mips, lod bias)
    0x0030 materials   tev-info count first, then materials (PVW blocks when flag 1 set)
    0x0040 vtx matrix  s16: >= 0 joint index, < 0 -> envelope (-v - 1)
    0x0041 envelopes   u16 count, then (u16 joint, f32 weight) pairs
    0x0050 meshes      parent joint, feature flags, matrix groups (dep list + display lists)
    0x0060 joints      parent, flags, bbox, radius, scale, rotation (rad, ZYX), translation,
                       (material, mesh) "matpoly" pairs
    0x0061 joint names u32 length + chars
    0x0100 / 0x0110    collision (skipped)        0xFFFF end

Display lists are plain GX with the game's fixed vertex descriptor: PNMTXIDX (direct u8,
feature flag 1), TEX1MTXIDX (u8, flag 2), POS u16, NRM/NBT u16, CLR0 u16 (flag 4),
TEX0..7 u16 (flags 8..0x400).  Normals are always indexed even when a model has none.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture
from gcrip.formats.j3d import PRIM_QUADS, PRIM_TRIANGLES, PRIM_TRIFAN, PRIM_TRISTRIP

CHUNK_HEADER = 0x0000
CHUNK_POS = 0x0010
CHUNK_NRM = 0x0011
CHUNK_NBT = 0x0012
CHUNK_CLR = 0x0013
CHUNK_TEX0 = 0x0018
CHUNK_TEXTURE = 0x0020
CHUNK_TEXATTR = 0x0022
CHUNK_MATERIAL = 0x0030
CHUNK_VTXMTX = 0x0040
CHUNK_ENVELOPE = 0x0041
CHUNK_MESH = 0x0050
CHUNK_JOINT = 0x0060
CHUNK_JOINT_NAME = 0x0061
CHUNK_END = 0xFFFF

MATFLAG_PVW = 1 << 0
MATFLAG_OPAQUE = 1 << 8
MATFLAG_ALPHA_TEST = 1 << 9
MATFLAG_ALPHA_BLEND = 1 << 10
MATFLAG_SKIP = 1 << 16

MESH_PNMTX = 1 << 0
MESH_TEX1MTX = 1 << 1
MESH_COLOR = 1 << 2
MESH_TEX0 = 1 << 3
MESH_NBT = 1 << 16

# Pikmin's TexImgFormat -> GX texture format (Texture.h)
PIKMIN_TO_GX = {0: 4, 1: 14, 2: 5, 3: 0, 4: 1, 5: 2, 6: 3, 7: 6, 8: 1}

# tiling flags (Texture::TexFlags)
TILE_CLAMP_S = 1 << 0
TILE_MIRROR_S = 1 << 1
TILE_CLAMP_T = 1 << 8
TILE_MIRROR_T = 1 << 9

_PRIMS = {PRIM_TRIANGLES, PRIM_TRISTRIP, PRIM_TRIFAN, PRIM_QUADS}


class PikminError(Exception):
    pass


@dataclass
class TexImg:
    width: int
    height: int
    fmt: int  # Pikmin numbering
    mips: int
    data: bytes


@dataclass
class TexAttr:
    image: int
    tiling: int
    use_mips: int
    lod_bias: float


@dataclass
class Material:
    flags: int
    texture_index: int  # TexAttr index, or -1
    colour: tuple[int, int, int, int]
    tev_index: int = -1
    pvw_textures: list[int] = field(default_factory=list)  # TexAttr indices (PVW block)
    pvw_colour: tuple[int, int, int, int] | None = None
    lighting_flags: int = 0
    pe_flags: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def tex_attr(self) -> int:
        if self.texture_index >= 0:
            return self.texture_index
        for t in self.pvw_textures:
            if t >= 0:
                return t
        return -1


@dataclass
class DispList:
    flags: int
    face_count: int
    data: bytes

    @property
    def cull(self) -> int:
        """0 back-face culled, 1 front-face culled, 2 no culling (DGXGraphics::setCullFront)."""
        return self.flags & 3


@dataclass
class MtxGroup:
    deps: list[int]
    lists: list[DispList]


@dataclass
class Mesh:
    parent_joint: int
    flags: int
    groups: list[MtxGroup]


@dataclass
class Joint:
    parent: int
    flags: int
    bmin: tuple[float, float, float]
    bmax: tuple[float, float, float]
    radius: float
    scale: tuple[float, float, float]
    rotation: tuple[float, float, float]  # radians, applied Z * Y * X (Matrix4f::makeSRT)
    translation: tuple[float, float, float]
    matpolys: list[tuple[int, int]]  # (material index, mesh index)
    name: str = ""


@dataclass
class Model:
    positions: np.ndarray  # (N,3) f32
    normals: np.ndarray  # (N,3) f32
    nbt: np.ndarray  # (N,3,3) f32
    colours: np.ndarray  # (N,4) u8
    texcoords: list[np.ndarray]  # 8 x (N,2) f32
    textures: list[TexImg]
    tex_attrs: list[TexAttr]
    materials: list[Material]
    vtx_matrices: list[int]  # >= 0 joint, < 0 envelope index (-v - 1)
    envelopes: list[list[tuple[int, float]]]
    meshes: list[Mesh]
    joints: list[Joint]
    date: tuple[int, int, int] = (0, 0, 0)
    shape_flags: int = 0
    warnings: list[str] = field(default_factory=list)


class _Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def align(self, n: int = 0x20) -> None:
        self.pos = (self.pos + n - 1) & ~(n - 1)

    def u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        (v,) = struct.unpack_from(">H", self.data, self.pos)
        self.pos += 2
        return v

    def s16(self) -> int:
        (v,) = struct.unpack_from(">h", self.data, self.pos)
        self.pos += 2
        return v

    def u32(self) -> int:
        (v,) = struct.unpack_from(">I", self.data, self.pos)
        self.pos += 4
        return v

    def s32(self) -> int:
        (v,) = struct.unpack_from(">i", self.data, self.pos)
        self.pos += 4
        return v

    def f32(self) -> float:
        (v,) = struct.unpack_from(">f", self.data, self.pos)
        self.pos += 4
        return v

    def vec3(self) -> tuple[float, float, float]:
        v = struct.unpack_from(">3f", self.data, self.pos)
        self.pos += 12
        return v

    def raw(self, n: int) -> bytes:
        b = self.data[self.pos : self.pos + n]
        if len(b) != n:
            raise PikminError("truncated file")
        self.pos += n
        return b

    def skip(self, n: int) -> None:
        self.pos += n


def _array(r: _Reader, dtype: str, shape: int) -> np.ndarray:
    count = r.u32()
    r.align()
    n = count * shape
    arr = np.frombuffer(r.data, dtype=dtype, count=n, offset=r.pos).astype(np.float32)
    r.pos += n * 4
    return arr.reshape(count, shape)


# --- materials ----------------------------------------------------------------------------


def _skip_anim_info(r: _Reader, key_size: int, per_key: int) -> None:
    """PVWAnimInfo1/3<Key>: u32 count, then count x (u32 time + per_key x key_size)."""
    count = r.u32()
    if count > 100000:
        raise PikminError(f"implausible animation key count {count}")
    r.skip(count * (4 + per_key * key_size))


def _read_tev_info(r: _Reader) -> None:
    for _ in range(3):  # PVWTevColReg
        r.skip(8)  # ShortColour
        r.u32()  # frame count
        r.f32()  # speed
        _skip_anim_info(r, 12, 3)  # colour keys (S10)
        _skip_anim_info(r, 12, 1)  # alpha keys
    r.skip(16)  # 4 konst colours
    stages = r.u32()
    if stages > 16:
        raise PikminError(f"implausible tev stage count {stages}")
    r.skip(stages * 32)


def _read_material(r: _Reader) -> Material:
    flags = r.u32()
    tex_index = r.s32()
    colour = tuple(r.raw(4))
    m = Material(flags, tex_index, colour)  # type: ignore[arg-type]
    if flags & MATFLAG_PVW:
        m.tev_index = r.s32()
        # PVWPolygonColourInfo
        m.pvw_colour = tuple(r.raw(4))  # type: ignore[assignment]
        r.u32()
        r.f32()
        _skip_anim_info(r, 12, 3)
        _skip_anim_info(r, 12, 1)
        # PVWLightingInfo
        m.lighting_flags = r.u32()
        r.f32()
        # PVWPeInfo
        m.pe_flags = (r.u32(), r.u32(), r.u32(), r.u32())
        # PVWTextureInfo
        r.u32()  # use scale
        r.vec3()
        n_gen = r.u32()
        if n_gen > 8:
            raise PikminError(f"implausible texgen count {n_gen}")
        r.skip(n_gen * 4)
        n_tex = r.u32()
        if n_tex > 8:
            raise PikminError(f"implausible texture data count {n_tex}")
        for _ in range(n_tex):
            m.pvw_textures.append(r.s32())
            r.skip(2 + 2 + 4)  # unused shorts + 4 bytes
            r.u32()  # animation factor
            r.u32()  # frame count
            r.skip(4 * 8)  # speed, scale xy, rot, trans xy, pivot xy
            for _ in range(3):
                _skip_anim_info(r, 12, 3)
    return m


# --- parse --------------------------------------------------------------------------------


def parse(data: bytes) -> Model:
    if len(data) < 0x40:
        raise PikminError("too short")
    m = Model(
        positions=np.zeros((0, 3), np.float32),
        normals=np.zeros((0, 3), np.float32),
        nbt=np.zeros((0, 3, 3), np.float32),
        colours=np.zeros((0, 4), np.uint8),
        texcoords=[np.zeros((0, 2), np.float32) for _ in range(8)],
        textures=[],
        tex_attrs=[],
        materials=[],
        vtx_matrices=[],
        envelopes=[],
        meshes=[],
        joints=[],
    )
    names: list[str] = []
    pos = 0
    n = len(data)
    seen_end = False
    while pos + 8 <= n:
        cid, length = struct.unpack_from(">II", data, pos)
        if cid == CHUNK_END:
            seen_end = True
            break
        r = _Reader(data, pos + 8)
        end = pos + 8 + length
        if end > n or (pos & 0x1F):
            raise PikminError(f"bad chunk {cid:#x} at {pos:#x} (length {length:#x})")
        try:
            _parse_chunk(m, names, cid, r, end)
        except (struct.error, IndexError) as ex:
            raise PikminError(f"chunk {cid:#x} truncated: {ex}") from ex
        pos = end
    if not seen_end and not m.joints:
        raise PikminError("no end chunk and no joints: not a .mod")
    for i, name in enumerate(names):
        if i < len(m.joints):
            m.joints[i].name = name
    return m


def _parse_chunk(m: Model, names: list[str], cid: int, r: _Reader, end: int) -> None:
    if cid == CHUNK_HEADER:
        r.align()
        year, month, day = r.u16(), r.u8(), r.u8()
        m.date = (year, month, day)
        m.shape_flags = r.u32()
    elif cid == CHUNK_POS:
        m.positions = _array(r, ">f4", 3)
    elif cid == CHUNK_NRM:
        m.normals = _array(r, ">f4", 3)
    elif cid == CHUNK_NBT:
        m.nbt = _array(r, ">f4", 9).reshape(-1, 3, 3)
    elif cid == CHUNK_CLR:
        count = r.u32()
        r.align()
        m.colours = np.frombuffer(r.data, np.uint8, count * 4, r.pos).reshape(count, 4).copy()
    elif CHUNK_TEX0 <= cid < CHUNK_TEX0 + 8:
        m.texcoords[cid - CHUNK_TEX0] = _array(r, ">f4", 2)
    elif cid == CHUNK_TEXTURE:
        count = r.u32()
        r.align()
        for _ in range(count):
            w, h = r.u16(), r.u16()
            fmt = r.u32()
            mips = r.u32()
            r.skip(16)
            size = r.u32()
            m.textures.append(TexImg(w, h, fmt, mips, r.raw(size)))
    elif cid == CHUNK_TEXATTR:
        count = r.u32()
        r.align()
        for _ in range(count):
            idx = r.u16()
            r.u16()
            tiling = r.u16()
            use_mips = r.u16()
            m.tex_attrs.append(TexAttr(idx, tiling, use_mips, r.f32()))
    elif cid == CHUNK_MATERIAL:
        n_mat = r.u32()
        n_tev = r.u32()
        r.align()
        for _ in range(n_tev):
            _read_tev_info(r)
        for _ in range(n_mat):
            m.materials.append(_read_material(r))
        if r.pos > end:
            raise PikminError("material chunk overrun")
    elif cid == CHUNK_VTXMTX:
        count = r.u32()
        r.align()
        m.vtx_matrices = [r.s16() for _ in range(count)]
    elif cid == CHUNK_ENVELOPE:
        count = r.u32()
        r.align()
        for _ in range(count):
            k = r.u16()
            m.envelopes.append([(r.u16(), r.f32()) for _ in range(k)])
    elif cid == CHUNK_MESH:
        count = r.u32()
        r.align()
        for _ in range(count):
            parent = r.s32()
            flags = r.u32()
            n_groups = r.u32()
            groups = []
            for _ in range(n_groups):
                n_dep = r.u32()
                deps = [r.s16() for _ in range(n_dep)]
                n_dl = r.u32()
                lists = []
                for _ in range(n_dl):
                    dflags = r.u32()
                    faces = r.u32()
                    size = r.u32()
                    r.align()
                    lists.append(DispList(dflags, faces, r.raw(size)))
                groups.append(MtxGroup(deps, lists))
            m.meshes.append(Mesh(parent, flags, groups))
    elif cid == CHUNK_JOINT:
        count = r.u32()
        r.align()
        for _ in range(count):
            parent = r.s32()
            flags = r.u32()
            bmin, bmax = r.vec3(), r.vec3()
            radius = r.f32()
            scale, rot, trans = r.vec3(), r.vec3(), r.vec3()
            n_mp = r.u32()
            mps = [(r.u16(), r.u16()) for _ in range(n_mp)]
            m.joints.append(Joint(parent, flags, bmin, bmax, radius, scale, rot, trans, mps))
    elif cid == CHUNK_JOINT_NAME:
        count = r.u32()
        r.align()
        for _ in range(count):
            k = r.u32()
            names.append(r.raw(k).decode("ascii", "replace"))
    # collision (0x100, 0x110) and unknown chunks are skipped


# --- display lists ------------------------------------------------------------------------


def vertex_fields(flags: int) -> list[tuple[str, str]]:
    """numpy dtype fields of one display-list vertex for a mesh's feature flags."""
    fields: list[tuple[str, str]] = []
    if flags & MESH_PNMTX:
        fields.append(("mtx", ">u1"))
    if flags & MESH_TEX1MTX:
        fields.append(("tmtx", ">u1"))
    fields.append(("pos", ">u2"))
    fields.append(("nrm", ">u2"))
    if flags & MESH_COLOR:
        fields.append(("clr", ">u2"))
    for i in range(8):
        if flags & (MESH_TEX0 << i):
            fields.append((f"tex{i}", ">u2"))
    return fields


def parse_display_list(dl: bytes, flags: int) -> list[tuple[int, np.ndarray]]:
    """-> [(opcode, structured array of indices)] for every primitive in the list."""
    vdt = np.dtype(vertex_fields(flags))
    stride = vdt.itemsize
    out = []
    pos = 0
    n = len(dl)
    while pos + 3 <= n:
        op = dl[pos]
        if op == 0:
            break
        if op & 0xF8 not in _PRIMS:
            raise PikminError(f"unknown display list opcode {op:#x} at {pos}")
        count = dl[pos + 1] << 8 | dl[pos + 2]
        pos += 3
        if pos + count * stride > n:
            raise PikminError("display list primitive overruns its data")
        out.append((op & 0xF8, np.frombuffer(dl, vdt, count, pos)))
        pos += count * stride
    return out


# --- textures -----------------------------------------------------------------------------


def decode_texture(tex: TexImg) -> np.ndarray:
    gx_fmt = PIKMIN_TO_GX.get(tex.fmt)
    if gx_fmt is None:
        raise PikminError(f"unknown Pikmin texture format {tex.fmt}")
    return gx_texture.decode(gx_fmt, tex.width, tex.height, tex.data)


def parse_txe(data: bytes) -> tuple[TexImg, int]:
    """A .txe file (TexImg::importTxe): 32-byte header, then the image.
    Returns (image, tiling flags)."""
    if len(data) < 0x20:
        raise PikminError("txe too short")
    w, h, fmt = struct.unpack_from(">HHH", data, 0)
    flags = fmt >> 8
    fmt &= 0xFF
    if fmt not in PIKMIN_TO_GX or w == 0 or h == 0:
        raise PikminError(f"not a txe (format {fmt}, {w}x{h})")
    size = gx_texture.encoded_size(PIKMIN_TO_GX[fmt], w, h)
    return TexImg(w, h, fmt, 1, data[0x20 : 0x20 + size]), flags


def looks_like_txe(data: bytes) -> bool:
    if len(data) < 0x20:
        return False
    w, h, fmt = struct.unpack_from(">HHH", data, 0)
    fmt &= 0xFF
    if fmt not in PIKMIN_TO_GX or not (0 < w <= 1024 and 0 < h <= 1024):
        return False
    return len(data) >= 0x20 + gx_texture.encoded_size(PIKMIN_TO_GX[fmt], w, h)


def looks_like_mod(head: bytes) -> bool:
    """Chunk 0 (header) of 0x38 bytes, then a known chunk id at 0x40."""
    if len(head) < 0x10:
        return False
    cid, length = struct.unpack_from(">II", head, 0)
    if cid != CHUNK_HEADER or length & 0x1F != 0x18 or length > 0x1000:
        return False
    if len(head) >= 8 + length + 4:
        nxt = struct.unpack_from(">I", head, 8 + length)[0]
        return nxt in (CHUNK_POS, CHUNK_NRM, CHUNK_MATERIAL, CHUNK_MESH, CHUNK_JOINT, CHUNK_END)
    return True
