"""Amusement Vision GMA model archives (F-Zero GX, Super Monkey Ball 1/2). Big-endian.
Layout checked byte-by-byte against the three games' discs and cross-read with
RaphaelTetreault's GameCube.GFZ library.

GMA header: u32 model count, u32 base offset (start of GCMF data), then count entries of
(u32 GCMF offset relative to base, u32 name offset relative to the name table) - an entry
of 0xFFFFFFFF/0xFFFFFFFF is an empty slot - and the C-string name table right after the
entry table (base offset is 32-byte aligned past it).

GCMF (0x40 bytes, then 32-byte aligned sections):
  0x00 "GCMF"         0x04 u32 attributes  (0x01 16-bit vertices, 0x04 stitching,
                                            0x08 skin, 0x10 effective/physics)
  0x08 f32[3] origin  0x14 f32 radius      (bounding sphere)
  0x18 u16 texture layer count   0x1A u16 opaque mesh count  0x1C u16 translucent count
  0x1E u8 transform matrix count 0x1F u8 0   0x20 u32 offset from the GCMF to the meshes
  0x24 u32 0          0x28 u8[8] transform matrix per GX matrix slot 1..8 (0xFF = none),
  0x30 pad to 0x40
  then texture layers (0x20 each): u16 flags, u8 mipmap flags, u8 wrap flags (0x04 repeat
  U, 0x08 mirror U, 0x10 repeat V, 0x20 mirror V), u16 TPL texture index, u8 lod bias,
  u8 anisotropy, u32 0 (runtime GXTexObj pointer), u16 unk, u16 layer index, u32 0,
  u32 unk (0x30), pad to 0x20
  then transform matrices (3x4 f32, row-major, 0x30 each)
  then, for skin/effective models only, a 0x20 skinned-vertex descriptor (those models keep
  their geometry in engine-private vertex pools without display lists - not decoded here).
Mesh (0x60 bytes): u32 render flags (bit0 unlit, bit1 double sided, bit5 screen blend,
  bit6 additive), u32 material RGBA8, u32 ambient RGBA8, u32 specular RGBA8, u8 unk,
  u8 alpha, u8 texture layer count, u8 destination (bit0 front-cull DL, bit1 back-cull DL,
  bits 2/3 the same for a secondary pair), u8 unk, u8 unk, s16[3] texture layer slots
  (-1 = none), u32 GX vertex attribute mask, u8[8] matrix indices, u32 size of display
  list A, u32 size of display list B, f32[3] origin, f32 unk, u32 blend factors, pad.
  The display lists follow (each 32-byte aligned, 0x00 NOP bytes as padding); when a
  secondary pair is flagged another 0x20 descriptor (u8[8] matrix indices, two u32 sizes,
  pad) and two more lists follow.
Display lists: GX primitives - u8 opcode (0x98 strip, 0xA0 fan, 0x90 triangles, 0x80
  quads; low 3 bits = vertex format index), u16 vertex count, vertices in GX attribute
  order: [u8 pn matrix index: 3 * GX slot] pos, normal (or 9-float NBT when bit 25 is
  set), RGBA8 colours, UV sets. Floats for plain models; "16-bit" models (format index 1) store
  positions and UVs as s16 / 8192 and normals as s16 / 16384 (the position scale is the
  one that makes every model's vertices fit its bounding sphere exactly).
Stitching models (attribute 0x04: characters) store each part in its bone's space; the
  vertex's GX slot picks the matrix through the mesh's slot table, falling back to the
  GCMF's, and multiplying by that 3x4 matrix assembles the figure.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats.j3d import triangulate

GCMF_MAGIC = b"GCMF"

ATTR_16BIT = 0x01
ATTR_STITCHING = 0x04
ATTR_SKIN = 0x08
ATTR_EFFECTIVE = 0x10

VA_PNMTXIDX = 0
VA_POS = 9
VA_NRM = 10
VA_CLR0 = 11
VA_CLR1 = 12
VA_TEX0 = 13
VA_NBT = 25

RENDER_UNLIT = 0x01
RENDER_DOUBLE_SIDED = 0x02
RENDER_SCREEN_BLEND = 0x20
RENDER_ADDITIVE = 0x40

WRAP_REPEAT_U = 0x04
WRAP_MIRROR_U = 0x08
WRAP_REPEAT_V = 0x10
WRAP_MIRROR_V = 0x20

POS_SCALE_16 = 1.0 / 8192.0
NRM_SCALE_16 = 1.0 / 16384.0
UV_SCALE_16 = 1.0 / 8192.0

_PRIM_OPS = {0x80, 0x88, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8}


class GmaError(Exception):
    pass


@dataclass
class TexLayer:
    flags: int
    mipmap: int
    wrap: int
    tpl_index: int
    lod_bias: int
    anisotropy: int
    index: int

    @property
    def repeat_u(self) -> bool:
        return bool(self.wrap & WRAP_REPEAT_U)

    @property
    def mirror_u(self) -> bool:
        return bool(self.wrap & WRAP_MIRROR_U)

    @property
    def repeat_v(self) -> bool:
        return bool(self.wrap & WRAP_REPEAT_V)

    @property
    def mirror_v(self) -> bool:
        return bool(self.wrap & WRAP_MIRROR_V)


@dataclass
class Strip:
    opcode: int  # GX primitive opcode with the format index masked off
    positions: np.ndarray  # (N,3) f32
    normals: np.ndarray | None = None  # (N,3) f32
    colors: np.ndarray | None = None  # (N,4) f32 0..1 (CLR0)
    uvs: dict[int, np.ndarray] = field(default_factory=dict)  # tex coord set -> (N,2)
    pn_index: np.ndarray | None = None  # (N,) GX matrix slot (PNMTXIDX / 3) when present

    @property
    def count(self) -> int:
        return len(self.positions)


@dataclass
class Mesh:
    render_flags: int
    color: tuple[float, float, float, float]
    ambient: tuple[float, float, float, float]
    specular: tuple[float, float, float, float]
    alpha: int
    tex_count: int
    destination: int
    tex_slots: tuple[int, int, int]
    vflags: int
    matrix_indices: bytes
    origin: tuple[float, float, float]
    blend_factors: int
    translucent: bool
    strips: list[Strip] = field(default_factory=list)  # display list A
    strips_b: list[Strip] = field(default_factory=list)  # display list B (other cull mode)

    @property
    def unlit(self) -> bool:
        return bool(self.render_flags & RENDER_UNLIT)

    @property
    def double_sided(self) -> bool:
        return bool(self.render_flags & RENDER_DOUBLE_SIDED)

    @property
    def blended(self) -> bool:
        return bool(self.render_flags & (RENDER_SCREEN_BLEND | RENDER_ADDITIVE))


@dataclass
class Gcmf:
    name: str
    attrs: int
    origin: tuple[float, float, float]
    radius: float
    matrix_indices: bytes = bytes([0xFF] * 8)  # GX matrix slot -> matrix (0xFF none)
    layers: list[TexLayer] = field(default_factory=list)
    matrices: list[np.ndarray] = field(default_factory=list)  # (3,4) f32 each
    meshes: list[Mesh] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_16bit(self) -> bool:
        return bool(self.attrs & ATTR_16BIT)

    @property
    def skinned(self) -> bool:
        """Skin / effective models keep their geometry in vertex pools, not display lists."""
        return bool(self.attrs & (ATTR_SKIN | ATTR_EFFECTIVE))


@dataclass
class Gma:
    models: list[Gcmf] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def looks_like(data: bytes, size: int | None = None) -> bool:
    """Cheap header sniff (works on the first 8 bytes): plausible count and base offset."""
    if len(data) < 8:
        return False
    count, base = struct.unpack_from(">II", data, 0)
    if not 0 < count <= 8192 or base % 0x20 or base < 8 + count * 8:
        return False
    if size is not None and base > size:
        return False
    if len(data) >= base + 4:
        # the first non-empty entry must point at a GCMF
        for i in range(count):
            if 8 + i * 8 + 8 > len(data):
                return True
            off, _ = struct.unpack_from(">II", data, 8 + i * 8)
            if off == 0xFFFFFFFF:
                continue
            return data[base + off : base + off + 4] == GCMF_MAGIC
    return True


def _cstr(data: bytes, off: int) -> str:
    end = data.find(b"\0", off)
    if end < 0:
        end = len(data)
    return data[off:end].decode("ascii", "replace")


def _rgba(v: int) -> tuple[float, float, float, float]:
    return (
        (v >> 24) / 255.0,
        (v >> 16 & 0xFF) / 255.0,
        (v >> 8 & 0xFF) / 255.0,
        (v & 0xFF) / 255.0,
    )


def vertex_dtype(vflags: int, is16: bool) -> np.dtype:
    fields: list[tuple] = []
    if vflags & (1 << VA_PNMTXIDX):
        fields.append(("pn", ">u1"))
    for t in range(8):
        if vflags & (1 << (1 + t)):
            fields.append((f"tm{t}", ">u1"))
    real = ">i2" if is16 else ">f4"
    if vflags & (1 << VA_POS):
        fields.append(("pos", real, (3,)))
    if vflags & (1 << VA_NRM):
        fields.append(("nrm", real, (3,)))
    if vflags & (1 << VA_NBT):
        fields.append(("nbt", real, (9,)))
    if vflags & (1 << VA_CLR0):
        fields.append(("clr0", ">u1", (4,)))
    if vflags & (1 << VA_CLR1):
        fields.append(("clr1", ">u1", (4,)))
    for t in range(8):
        if vflags & (1 << (VA_TEX0 + t)):
            fields.append((f"tex{t}", real, (2,)))
    if not fields:
        raise GmaError(f"vertex attribute mask {vflags:#x} has no attributes")
    return np.dtype(fields)


def parse_display_list(dl: bytes, vflags: int, is16: bool) -> tuple[list[Strip], str | None]:
    """Decode one GX display list into strips. Returns (strips, warning)."""
    vdt = vertex_dtype(vflags, is16)
    names = vdt.names or ()
    stride = vdt.itemsize
    strips: list[Strip] = []
    pos = 0
    n = len(dl)
    warn = None
    while pos < n:
        op = dl[pos]
        if op == 0:
            pos += 1
            continue
        if op & 0xF8 not in _PRIM_OPS or pos + 3 > n:
            warn = f"unknown display list opcode {op:#x} at {pos}"
            break
        count = dl[pos + 1] << 8 | dl[pos + 2]
        pos += 3
        end = pos + count * stride
        if end > n:
            warn = f"display list primitive overruns its list ({end} > {n})"
            break
        arr = np.frombuffer(dl, dtype=vdt, count=count, offset=pos)
        pos = end
        if "pos" not in names:
            continue
        s = Strip(op & 0xF8, arr["pos"].astype(np.float32))
        if is16:
            s.positions *= np.float32(POS_SCALE_16)
        if "nrm" in names:
            s.normals = arr["nrm"].astype(np.float32)
            if is16:
                s.normals *= np.float32(NRM_SCALE_16)
        elif "nbt" in names:
            s.normals = arr["nbt"][:, :3].astype(np.float32)
            if is16:
                s.normals *= np.float32(NRM_SCALE_16)
        if "clr0" in names:
            s.colors = arr["clr0"].astype(np.float32) / np.float32(255.0)
        for t in range(8):
            key = f"tex{t}"
            if key in names:
                uv = arr[key].astype(np.float32)
                if is16:
                    uv *= np.float32(UV_SCALE_16)
                s.uvs[t] = uv
        if "pn" in names:
            s.pn_index = arr["pn"].astype(np.int64) // 3
        strips.append(s)
    return strips, warn


def _parse_mesh(data: bytes, off: int, translucent: bool) -> tuple[Mesh, int, int]:
    """Parse a 0x60 mesh header; returns (mesh, size of DL A, size of DL B)."""
    (rflags, col, amb, spec) = struct.unpack_from(">IIII", data, off)
    unk10, alpha, texcount, dest, _unk14, _unk15 = struct.unpack_from(">BBBBBB", data, off + 0x10)
    t0, t1, t2 = struct.unpack_from(">hhh", data, off + 0x16)
    (vflags,) = struct.unpack_from(">I", data, off + 0x1C)
    mtx = data[off + 0x20 : off + 0x28]
    size_a, size_b = struct.unpack_from(">II", data, off + 0x28)
    ox, oy, oz, _unk3c, blend = struct.unpack_from(">ffffI", data, off + 0x30)
    mesh = Mesh(
        render_flags=rflags,
        color=_rgba(col),
        ambient=_rgba(amb),
        specular=_rgba(spec),
        alpha=alpha,
        tex_count=texcount,
        destination=dest,
        tex_slots=(t0, t1, t2),
        vflags=vflags,
        matrix_indices=mtx,
        origin=(ox, oy, oz),
        blend_factors=blend,
        translucent=translucent,
    )
    return mesh, size_a, size_b


def _align32(x: int) -> int:
    return (x + 31) & ~31


def parse_gcmf(data: bytes, off: int, name: str) -> Gcmf:
    if data[off : off + 4] != GCMF_MAGIC:
        raise GmaError(f"no GCMF magic at {off:#x}")
    attrs, ox, oy, oz, radius = struct.unpack_from(">Iffff", data, off + 4)
    ntex, nopaque, ntrans, nmtx = struct.unpack_from(">HHHB", data, off + 0x18)
    (mesh_off,) = struct.unpack_from(">I", data, off + 0x20)
    g = Gcmf(
        name=name,
        attrs=attrs,
        origin=(ox, oy, oz),
        radius=radius,
        matrix_indices=bytes(data[off + 0x28 : off + 0x30]),
    )
    p = off + 0x40
    for _ in range(ntex):
        flags, mip, wrap, tpl, lod, aniso = struct.unpack_from(">HBBHBB", data, p)
        (index,) = struct.unpack_from(">H", data, p + 0x0E)
        g.layers.append(TexLayer(flags, mip, wrap, tpl, lod, aniso, index))
        p += 0x20
    for _ in range(nmtx):
        m = np.frombuffer(data, dtype=">f4", count=12, offset=p).reshape(3, 4).astype(np.float32)
        g.matrices.append(m)
        p += 0x30
    expected = _align32(p - off)
    if mesh_off != expected:
        g.warnings.append(f"mesh data offset {mesh_off:#x} (header says {expected:#x})")
    p = off + mesh_off
    if g.skinned:
        # 0x20 skinned-vertex descriptor, then the mesh headers without display lists
        p += 0x20
    is16 = g.is_16bit
    total = nopaque + ntrans
    for mi in range(total):
        if p + 0x60 > len(data):
            g.warnings.append(f"mesh {mi} header past end of file")
            break
        mesh, size_a, size_b = _parse_mesh(data, p, mi >= nopaque)
        p += 0x60
        if g.skinned:
            g.meshes.append(mesh)
            continue
        dest = mesh.destination
        for slot, size in ((0, size_a), (1, size_b)):
            if not dest & (1 << slot):
                continue
            dl = data[p : p + size]
            strips, warn = parse_display_list(dl, mesh.vflags, is16)
            if warn:
                g.warnings.append(f"mesh {mi} list {slot}: {warn}")
            if slot == 0:
                mesh.strips = strips
            else:
                mesh.strips_b = strips
            p += size
        if dest & 0x0C:
            sec_a, sec_b = struct.unpack_from(">II", data, p + 8)
            p += 0x20
            for slot, size in ((2, sec_a), (3, sec_b)):
                if not dest & (1 << slot):
                    continue
                dl = data[p : p + size]
                strips, warn = parse_display_list(dl, mesh.vflags, is16)
                if warn:
                    g.warnings.append(f"mesh {mi} secondary list {slot - 2}: {warn}")
                (mesh.strips if slot == 2 else mesh.strips_b).extend(strips)
                p += size
        g.meshes.append(mesh)
    return g


def parse(data: bytes) -> Gma:
    if len(data) < 8:
        raise GmaError("file too small")
    count, base = struct.unpack_from(">II", data, 0)
    if not 0 < count <= 8192 or base > len(data) or base < 8 + count * 8:
        raise GmaError(f"implausible header: {count} models, base {base:#x}")
    names_off = 8 + count * 8
    out = Gma()
    for i in range(count):
        off, noff = struct.unpack_from(">II", data, 8 + i * 8)
        if off == 0xFFFFFFFF:
            continue
        name = _cstr(data, names_off + noff) if noff != 0xFFFFFFFF else ""
        if not name:
            name = f"gcmf{i:03d}"
        g = base + off
        if g + 0x40 > len(data) or data[g : g + 4] != GCMF_MAGIC:
            out.warnings.append(f"entry {i} ({name}): no GCMF at {g:#x}")
            continue
        try:
            out.models.append(parse_gcmf(data, g, name))
        except (GmaError, struct.error, ValueError) as e:
            out.warnings.append(f"entry {i} ({name}): {e}")
    return out


def strip_triangles(strip: Strip) -> np.ndarray:
    """(T,3) local vertex indices for one strip."""
    return triangulate(strip.opcode, strip.count)
