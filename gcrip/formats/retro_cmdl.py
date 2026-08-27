"""Retro CMDL models and the material/geometry blocks they share with MREA world models
(Metroid Prime = version 2, Echoes = version 4). Layout checked against the discs.

CMDL header: u32 0xDEADBABE, u32 version, u32 flags (1 skinned, 2 short normals, 4 short
UV array present), f32[6] AABB, u32 section count, u32 material set count, u32[count]
section sizes; sections start at the next 32-byte boundary and are each 32-byte aligned.
Sections: one per material set, positions (f32 xyz), normals (f32 xyz or s16 xyz /
0x8000), colors (RGBA8), float UVs (f32 uv), [short UVs (s16 uv / 0x8000) if flags & 4],
surface offsets (u32 count, u32[count] end offsets), then one section per surface.

Material set: u32 texture count, u32[] TXTR ids, u32 material count, u32[] material end
offsets (relative to the first material). Material: u32 flags, u32 texture count, u32[]
indices into the set's texture list, u32 vertex attribute flags (2 bits per attribute:
pos, nrm, col0, col1, tex0..tex6 in the low 22 bits; 3 = u16 index, 2 = u8 index; Echoes:
top byte bit 0 = position matrix index, bits 1-7 = tex0-6 matrix index, u8 each),
[Echoes: 2 x u32 unknown], u32 group index, [flags & 8: u32 konst count, u32[] RGBA],
u16 blend dst, u16 blend src, [flags & 0x400: u32 indirect slot], u32 color channel count,
u32[] channel flags (bit 0 lighting), u32 TEV stage count, 0x14 bytes per stage (color in,
alpha in, color op, alpha op, pad, kalpha sel, kcolor sel, ras channel), per stage
(u16 pad, u8 texture index into the material's list, u8 texgen index), u32 texgen count,
u32[] texgen flags (bits 0-3 type, 4-8 source: 4 + n = UV set n), UV animations (u32 size,
u32 count, ...).

Surface: f32[3] center, u32 material, u32 display list size (top bit = normal hint),
u32 parent, u32 next, u32 extra size, f32[3] normal, [Echoes: u16, u16], extra bytes; the
GX display list follows at the next 32-byte boundary. Display list: u8 opcode (top 5 bits
primitive type, low 3 bits vertex format - 2 means UV0 comes from the short UV array),
u16 vertex count, then per vertex the indices selected by the material's attribute flags.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = 0xDEADBABE

FLAG_SKINNED = 0x1
FLAG_SHORT_NORMALS = 0x2
FLAG_SHORT_UVS = 0x4

MAT_KONST = 0x8
MAT_TRANSPARENT = 0x10
MAT_MASKED = 0x20
MAT_ZWRITE = 0x80
MAT_INDIRECT = 0x400
MAT_LIGHTMAP_UVS = 0x2000

# vertex attribute stream order (GX): matrix indices (u8) first, then indexed attributes
_MTX_ATTRS = [("pmtx", 0x01), ("t0mtx", 0x02), ("t1mtx", 0x04), ("t2mtx", 0x08),
              ("t3mtx", 0x10), ("t4mtx", 0x20), ("t5mtx", 0x40), ("t6mtx", 0x80)]  # fmt: skip
_IDX_ATTRS = ["pos", "nrm", "col0", "col1", "tex0", "tex1", "tex2", "tex3", "tex4", "tex5",
              "tex6"]  # fmt: skip


class CmdlError(ValueError):
    pass


@dataclass
class TevStage:
    color_in: int
    alpha_in: int
    color_op: int
    alpha_op: int
    texture: int | None = None  # index into Material.textures
    texgen: int | None = None

    @property
    def uses_texture(self) -> bool:
        ins = [(self.color_in >> s) & 0x1F for s in (0, 5, 10, 15)]
        return any(i in (8, 9) for i in ins) or any(
            ((self.alpha_in >> s) & 0x1F) == 4 for s in (0, 5, 10)
        )


@dataclass
class Material:
    flags: int
    textures: list[int]  # indices into MaterialSet.texture_ids
    vtx_flags: int
    group: int = 0
    konst: list[int] = field(default_factory=list)
    blend_dst: int = 0
    blend_src: int = 1
    lit: bool = True
    tev: list[TevStage] = field(default_factory=list)
    texgens: list[int] = field(default_factory=list)

    @property
    def transparent(self) -> bool:
        return bool(self.flags & (MAT_TRANSPARENT | MAT_MASKED))

    def uv_set_of_texgen(self, g: int) -> int | None:
        """UV set index if texgen `g` samples a vertex UV set (source TEX0..TEX7)."""
        if g < 0 or g >= len(self.texgens):
            return None
        src = (self.texgens[g] >> 4) & 0x1F
        return src - 4 if 4 <= src <= 11 else None

    def diffuse(self) -> tuple[int, int] | None:
        """(texture index into the set, UV set) for the stage to show as the base color:
        the first TEV stage that samples a UV-mapped texture, preferring non-lightmaps."""
        cands = []
        for st in self.tev:
            if st.texture is None or st.texture >= len(self.textures) or st.texgen is None:
                continue
            uv = self.uv_set_of_texgen(st.texgen)
            if uv is None:
                continue
            lightmap = bool(self.flags & MAT_LIGHTMAP_UVS) and uv == 0
            cands.append((lightmap, self.textures[st.texture], uv))
        if not cands:
            return None
        cands.sort(key=lambda c: c[0])
        return cands[0][1], cands[0][2]


@dataclass
class MaterialSet:
    texture_ids: list[int]
    materials: list[Material]


@dataclass
class Surface:
    material: int
    center: tuple[float, float, float]
    normal: tuple[float, float, float]
    dl: bytes
    extra: bytes = b""


@dataclass
class Model:
    version: int
    flags: int
    aabb: tuple[float, ...]
    material_sets: list[MaterialSet]
    positions: np.ndarray  # (N,3) f32
    normals: np.ndarray  # (N,3) f32
    colors: np.ndarray  # (N,4) f32
    uvs: np.ndarray  # (N,2) f32
    short_uvs: np.ndarray  # (N,2) f32
    surfaces: list[Surface]
    warnings: list[str] = field(default_factory=list)


def _sections(data: bytes, start: int, sizes: list[int]) -> list[bytes]:
    out = []
    pos = start
    for s in sizes:
        out.append(data[pos : pos + s])
        pos += s
    return out


def parse_material_set(sec: bytes, version: int) -> MaterialSet:
    (tc,) = struct.unpack_from(">I", sec, 0)
    tex_ids = list(struct.unpack_from(f">{tc}I", sec, 4))
    pos = 4 + 4 * tc
    (mc,) = struct.unpack_from(">I", sec, pos)
    pos += 4
    ends = struct.unpack_from(f">{mc}I", sec, pos)
    pos += 4 * mc
    base = pos
    mats = []
    for i in range(mc):
        mats.append(parse_material(sec, base, version))
        base = pos + ends[i]
    return MaterialSet(tex_ids, mats)


def parse_material(sec: bytes, pos: int, version: int) -> Material:
    flags, tc = struct.unpack_from(">II", sec, pos)
    pos += 8
    tex = list(struct.unpack_from(f">{tc}I", sec, pos))
    pos += 4 * tc
    (vtx,) = struct.unpack_from(">I", sec, pos)
    pos += 4
    if version >= 3:
        pos += 8
    (group,) = struct.unpack_from(">I", sec, pos)
    pos += 4
    m = Material(flags, tex, vtx, group)
    if flags & MAT_KONST:
        (kc,) = struct.unpack_from(">I", sec, pos)
        pos += 4
        m.konst = list(struct.unpack_from(f">{kc}I", sec, pos))
        pos += 4 * kc
    m.blend_dst, m.blend_src = struct.unpack_from(">HH", sec, pos)
    pos += 4
    if flags & MAT_INDIRECT:
        pos += 4
    (cc,) = struct.unpack_from(">I", sec, pos)
    pos += 4
    if cc:
        (chan,) = struct.unpack_from(">I", sec, pos)
        m.lit = bool(chan & 1)
    else:
        m.lit = False
    pos += 4 * cc
    (tsc,) = struct.unpack_from(">I", sec, pos)
    pos += 4
    for _ in range(tsc):
        ci, ai, co, ao = struct.unpack_from(">IIII", sec, pos)
        m.tev.append(TevStage(ci, ai, co, ao))
        pos += 0x14
    for st in m.tev:
        _pad, t, g = struct.unpack_from(">HBB", sec, pos)
        pos += 4
        st.texture = t if t != 0xFF else None
        st.texgen = g if g != 0xFF else None
    (tgc,) = struct.unpack_from(">I", sec, pos)
    pos += 4
    m.texgens = list(struct.unpack_from(f">{tgc}I", sec, pos))
    return m


def vertex_dtype(m: Material) -> tuple[np.dtype, list[str]]:
    """numpy dtype of one display-list vertex for a material's attribute flags."""
    fields = []
    top = m.vtx_flags >> 24
    for name, bit in _MTX_ATTRS:
        if top & bit:
            fields.append((name, ">u1"))
    for i, name in enumerate(_IDX_ATTRS):
        v = (m.vtx_flags >> (2 * i)) & 3
        if v == 0:
            continue
        if v == 3:
            fields.append((name, ">u2"))
        elif v == 2:
            fields.append((name, ">u1"))
        else:
            raise CmdlError(f"direct vertex data for {name} not supported")
    return np.dtype(fields), [f for f, _ in fields]


def parse_display_list(dl: bytes, m: Material) -> list[tuple[int, int, np.ndarray]]:
    """[(primitive opcode, vertex format, structured index array)]"""
    vdt, _ = vertex_dtype(m)
    stride = vdt.itemsize
    prims = []
    pos = 0
    n = len(dl)
    while pos + 3 <= n:
        op = dl[pos]
        if op == 0:
            break
        count = (dl[pos + 1] << 8) | dl[pos + 2]
        pos += 3
        end = pos + count * stride
        if end > n:
            break
        arr = np.frombuffer(dl, dtype=vdt, count=count, offset=pos)
        pos = end
        prims.append((op & 0xF8, op & 7, arr))
    return prims


def parse_surface(sec: bytes, version: int) -> Surface:
    cx, cy, cz, mat, dl_size, _parent, _next, extra = struct.unpack_from(">3fIIIII", sec, 0)
    nx, ny, nz = struct.unpack_from(">3f", sec, 0x20)
    hdr = (0x2C if version < 4 else 0x30) + extra
    extra_bytes = sec[hdr - extra : hdr]
    start = (hdr + 31) & ~31
    dl_size &= 0x7FFFFFFF
    return Surface(mat, (cx, cy, cz), (nx, ny, nz), sec[start : start + dl_size], extra_bytes)


def parse_geometry(
    secs: list[bytes], flags: int, version: int, n_sets: int, warnings: list[str]
) -> tuple[list[MaterialSet], dict[str, np.ndarray], list[Surface]]:
    """Material sets + vertex arrays + surfaces from a section list laid out like a CMDL
    (material sets first). MREA world models reuse this with their own section slice."""
    sets = [parse_material_set(secs[i], version) for i in range(n_sets)]
    pos = n_sets
    n_vertex = 5 if flags & FLAG_SHORT_UVS else 4
    if len(secs) < pos + n_vertex + 1:
        raise CmdlError("too few data sections")
    arrays = {}
    p = np.frombuffer(secs[pos], dtype=">f4").astype(np.float32)
    arrays["positions"] = p[: len(p) - len(p) % 3].reshape(-1, 3)
    if flags & FLAG_SHORT_NORMALS:
        n = np.frombuffer(secs[pos + 1], dtype=">i2").astype(np.float32) / 32768.0
        n = n[: len(n) - len(n) % 3]
    else:
        n = np.frombuffer(secs[pos + 1], dtype=">f4").astype(np.float32)
        n = n[: len(n) - len(n) % 3]
    arrays["normals"] = n.reshape(-1, 3)
    col = np.frombuffer(secs[pos + 2], dtype=np.uint8).astype(np.float32) / 255.0
    arrays["colors"] = col.reshape(-1, 4)
    uv = np.frombuffer(secs[pos + 3], dtype=">f4").astype(np.float32)
    arrays["uvs"] = uv[: len(uv) - len(uv) % 2].reshape(-1, 2)
    if flags & FLAG_SHORT_UVS:
        suv = np.frombuffer(secs[pos + 4], dtype=">i2").astype(np.float32) / 32768.0
        arrays["short_uvs"] = suv[: len(suv) - len(suv) % 2].reshape(-1, 2)
    else:
        arrays["short_uvs"] = np.zeros((0, 2), np.float32)
    pos += n_vertex
    (n_surf,) = struct.unpack_from(">I", secs[pos], 0)
    pos += 1
    surfaces = []
    for i in range(n_surf):
        if pos + i >= len(secs):
            warnings.append(f"surface {i}: section missing")
            break
        try:
            surfaces.append(parse_surface(secs[pos + i], version))
        except struct.error:
            warnings.append(f"surface {i}: truncated header")
    return sets, arrays, surfaces


def parse(data: bytes) -> Model:
    if len(data) < 0x2C:
        raise CmdlError("too short")
    magic, version, flags = struct.unpack_from(">III", data, 0)
    if magic != MAGIC:
        raise CmdlError("bad magic")
    if version not in (2, 3, 4):
        raise CmdlError(f"unsupported CMDL version {version}")
    aabb = struct.unpack_from(">6f", data, 0xC)
    n_sec, n_sets = struct.unpack_from(">II", data, 0x24)
    sizes = list(struct.unpack_from(f">{n_sec}I", data, 0x2C))
    start = (0x2C + 4 * n_sec + 31) & ~31
    secs = _sections(data, start, sizes)
    warnings: list[str] = []
    sets, arrays, surfaces = parse_geometry(secs, flags, version, n_sets, warnings)
    return Model(
        version,
        flags,
        aabb,
        sets,
        arrays["positions"],
        arrays["normals"],
        arrays["colors"],
        arrays["uvs"],
        arrays["short_uvs"],
        surfaces,
        warnings,
    )
