"""Star Fox Adventures (GSAE01) character models and textures.

Models live in ``MODELS.bin`` at the byte offsets of ``MODELS.tab`` (u32 entries, high byte
0x10 = present, low 24 bits = offset), each wrapped in a FACEFEED header around a ZLB (zlib)
block.  The unwrapped model (the "final" layout, offsets below) is a bag of arrays plus a
bit-packed render script (LSB-first) that selects shaders, vertex descriptors and matrix
slots and calls GX display lists:

    0x20 -> u32 texture ids (count u8 @0xF2)     0x24 u8 normal flags (8 = NBT)
    0x28 -> s16x3 positions (u16 @0xE4)          0x2C -> s8x3 normals (@0xE6)
    0x30 -> u16 RGBA4 colours (@0xE8)            0x34 -> s16x2 texcoords (@0xEA)
    0x38 -> shaders, 0x44 bytes (u8 @0xF8)       0x3C -> bones, 0x1C bytes (u8 @0xF3)
    0x54 -> coarse blends, 4 bytes (u8 @0xF4)    0xD0 -> display list infos, 0x1C (u8 @0xF5)
    0xD4 -> render script, u16 byte count @0xD8  0xFA u8 texture matrix count

Script opcodes (4 bits): 1 shader (6 bits), 2 call list (8 bits), 3 vertex descriptor (one
bit per attribute present: 16-bit index when set), 4 matrix slots (4-bit count, 8 bits
each), 5 end.  Display lists use VAT 5 (positions / 8, texcoords / 256, RGBA4 colours).

Textures: ``TEX1.tab`` entries `0x80CCOOOOOO`: C = frame count, O = offset / 2 into
``TEX1.bin``; one ZLB per frame (a u32 offset table first when C > 1); each frame is a 0x60
header (u16 w @0xA, h @0xC, u8 GX format @0x16, wrap s/t @0x17/0x18) then GX pixel data.
Reference: Rena Kunisaki's SFA wiki and noclip.website's StarFoxAdventures loader.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture
from gcrip.formats.j3d import PRIM_QUADS, PRIM_TRIANGLES, PRIM_TRIFAN, PRIM_TRISTRIP

_PRIMS = {PRIM_TRIANGLES, PRIM_TRISTRIP, PRIM_TRIFAN, PRIM_QUADS}

SHADER_ATTR_NRM = 0x1
SHADER_ATTR_CLR = 0x2
SHADER_FLAG_HIDDEN = 0x2
SHADER_FLAG_CULL_BACK = 0x8
SHADER_FLAG_ALPHA_COMPARE = 0x400
SHADER_FLAG_UNLIT = 0x80000
SHADER_FLAG_WATER = 0x80000000
NORMAL_FLAG_NBT = 0x8

# VAT entries as (component type, fraction shift): S8 / S16 / F32 / RGBA4 / RGBA8
# The game sets these once at boot (noclip generateVat, final version).
_VAT: dict[int, dict[str, tuple[str, int]]] = {
    0: {"pos": ("s16", 0), "clr": ("rgba8", 0), "tex": ("s16", 7)},
    1: {"pos": ("s16", 2), "clr": ("rgba8", 0), "tex": ("f32", 0)},
    2: {"pos": ("f32", 0), "nrm": ("f32", 0), "clr": ("rgba8", 0), "tex": ("f32", 0)},
    3: {"pos": ("s16", 8), "nrm": ("s8", 0), "clr": ("rgba4", 0), "tex": ("s16", 10)},
    4: {"pos": ("f32", 0), "nrm": ("f32", 0), "clr": ("rgba8", 0), "tex": ("s16", 7)},
    5: {"pos": ("s16", 3), "nrm": ("s8", 0), "clr": ("rgba4", 0), "tex": ("s16", 8)},
    6: {"pos": ("s16", 8), "nrm": ("s8", 0), "clr": ("rgba4", 0), "tex": ("s16", 10)},
    7: {"pos": ("s16", 0), "nrm": ("s8", 0), "clr": ("rgba4", 0), "tex": ("s16", 10)},
}


class SFAError(Exception):
    pass


# --- wrappers -----------------------------------------------------------------------------


def read_tab(tab: bytes) -> list[int]:
    n = len(tab) // 4
    return list(struct.unpack(f">{n}I", tab[: n * 4]))


def unwrap(data: bytes) -> bytes:
    """ZLB / DIRn / FACEFEED / E0E0E0E0 wrapper -> payload bytes."""
    if len(data) < 16:
        raise SFAError("wrapper too short")
    magic = data[:4]
    if magic == b"ZLB\0":
        _ver, usize, csize = struct.unpack_from(">III", data, 4)
        try:
            return zlib.decompress(data[16 : 16 + csize])
        except zlib.error as ex:
            raise SFAError(f"zlib: {ex}") from ex
    if magic[:3] == b"DIR":
        size = struct.unpack_from(">I", data, 8)[0]
        return data[0x20 : 0x20 + size]
    if magic == b"\xfa\xce\xfe\xed":
        words = struct.unpack_from(">I", data, 8)[0]
        off = (words - 3) * 4
        if data[off : off + 4] != b"ZLB\0":
            k = data.find(b"ZLB\0", 0, 0x100)
            if k < 0:
                raise SFAError("FACEFEED without ZLB payload")
            off = k
        return unwrap(data[off:])
    if magic == b"\xe0\xe0\xe0\xe0":
        length, off = struct.unpack_from(">II", data, 4)
        return data[off + 0x18 : off + 0x18 + length]
    raise SFAError(f"unknown wrapper {magic.hex()}")


def looks_like_models_bin(head: bytes) -> bool:
    return head[:4] in (b"\xfa\xce\xfe\xed", b"ZLB\0", b"\xe0\xe0\xe0\xe0")


# --- model --------------------------------------------------------------------------------


@dataclass
class Joint:
    parent: int  # 0xFF = root
    translation: tuple[float, float, float]
    bind_translation: tuple[float, float, float]


@dataclass
class Blend:
    joint0: int
    joint1: int
    weight0: float


@dataclass
class ShaderLayer:
    texture: int  # index into model.texture_ids, -1 = none
    tev_mode: int


@dataclass
class Shader:
    layers: list[ShaderLayer]
    flags: int
    attr_flags: int
    color: tuple[int, int, int]
    hemispheric_probe: bool = False
    reflective_probe: bool = False
    nbt_texture: bool = False


@dataclass
class DisplayListInfo:
    offset: int
    size: int


@dataclass
class Draw:
    shader: int
    vcd: dict[str, int]  # attribute -> 1 (8-bit index) / 2 (16-bit index); "direct" -> byte count
    dl: bytes
    matrix_map: list[int]


@dataclass
class FineSkin:
    """A run of vertices skinned on the CPU: two bones, per-vertex weight pairs (/128)."""

    first_vertex: int
    count: int
    bone0: int
    bone1: int
    weights: np.ndarray  # (count, 2) float


@dataclass
class Model:
    positions: np.ndarray  # raw s16 (N,3)
    normals: np.ndarray  # raw s8 (N,3)
    colors: np.ndarray  # raw u16 (N,)
    texcoords: np.ndarray  # raw s16 (N,2)
    texture_ids: list[int]
    joints: list[Joint]
    blends: list[Blend]
    shaders: list[Shader]
    dl_infos: list[DisplayListInfo]
    draws: list[Draw]
    fine_skins: list[FineSkin] = field(default_factory=list)
    normal_flags: int = 0
    tex_mtx_count: int = 0
    is_map: bool = False
    warnings: list[str] = field(default_factory=list)


class _Bits:
    """LSB-first bit reader (noclip LowBitReader)."""

    def __init__(self, data: bytes, offset: int) -> None:
        self.data = data
        self.pos = offset
        self.buf = 0
        self.num = 0

    def get(self, bits: int) -> int:
        while self.num < bits:
            if self.pos >= len(self.data):
                raise SFAError("render script overruns the file")
            self.buf |= self.data[self.pos] << self.num
            self.pos += 1
            self.num += 8
        v = self.buf & ((1 << bits) - 1)
        self.buf >>= bits
        self.num -= bits
        return v


def _parse_shader(data: bytes, off: int, is_map: bool) -> Shader:
    layers = []
    n_layers = min(data[off + 0x41], 2)
    for i in range(n_layers):
        lo = off + 0x24 + 8 * i
        tex = struct.unpack_from(">i", data, lo)[0]
        layers.append(ShaderLayer(tex, data[lo + 4]))
    flags = struct.unpack_from(">I", data, off + 0x3C)[0]
    attr = data[off + 0x40]
    color = (data[off + 4], data[off + 5], data[off + 6])
    hemi = struct.unpack_from(">I", data, off + 0x8)[0] != 0
    refl = struct.unpack_from(">I", data, off + 0x14)[0] != 0
    nbt = struct.unpack_from(">i", data, off + 0x34)[0] != -1
    return Shader(layers, flags, attr, color, hemi, refl, nbt)


def parse_model(data: bytes, is_map: bool = False) -> Model:
    n = len(data)
    if n < 0x100:
        raise SFAError("model too short")
    if is_map:
        f = {
            "tex": (0x54, 0xA0, 1),
            "pos": (0x58, 0x90, 2),
            "clr": (0x5C, 0x94, 2),
            "tc": (0x60, 0x96, 2),
            "shader": (0x64, 0xA2, 1),
            "dl": (0x68, 0xA1, 1),
            "bits": [(0x78, 0x84), (0x7C, 0x86), (0x80, 0x88)],
        }
        normal_flags = 0
    else:
        f = {
            "tex": (0x20, 0xF2, 1),
            "pos": (0x28, 0xE4, 2),
            "nrm": (0x2C, 0xE6, 2),
            "clr": (0x30, 0xE8, 2),
            "tc": (0x34, 0xEA, 2),
            "shader": (0x38, 0xF8, 1),
            "joint": (0x3C, 0xF3, 1),
            "blend": (0x54, 0xF4, 1),
            "dl": (0xD0, 0xF5, 1),
            "bits": [(0xD4, 0xD8)],
        }
        normal_flags = data[0x24]

    def ptr_count(key: str) -> tuple[int, int]:
        po, co, cw = f[key]
        off = struct.unpack_from(">I", data, po)[0]
        cnt = data[co] if cw == 1 else struct.unpack_from(">H", data, co)[0]
        if off >= n:
            raise SFAError(f"{key} offset {off:#x} beyond file")
        return off, cnt

    def arr(key: str, dtype: str, width: int) -> np.ndarray:
        off, cnt = ptr_count(key)
        item = np.dtype(dtype).itemsize * width
        cnt = min(cnt, (n - off) // item)
        a = np.frombuffer(data, dtype, cnt * width, off)
        return a.reshape(cnt, width) if width > 1 else a

    positions = arr("pos", ">i2", 3)
    if "nrm" in f:
        nw = 9 if normal_flags & NORMAL_FLAG_NBT else 3
        normals = arr("nrm", ">i1", nw)[:, :3]
    else:
        normals = np.zeros((0, 3), np.int8)
    colors = arr("clr", ">u2", 1)
    texcoords = arr("tc", ">i2", 2)

    toff, tcnt = ptr_count("tex")
    texture_ids = list(struct.unpack_from(f">{tcnt}I", data, toff)) if tcnt else []

    joints: list[Joint] = []
    blends: list[Blend] = []
    tex_mtx_count = 0
    if not is_map:
        joff, jcnt = ptr_count("joint")
        for i in range(jcnt):
            o = joff + 0x1C * i
            parent = data[o]
            tr = struct.unpack_from(">3f", data, o + 4)
            bt = struct.unpack_from(">3f", data, o + 0x10)
            joints.append(Joint(parent, tr, bt))
        boff, bcnt = ptr_count("blend")
        for i in range(bcnt):
            o = boff + 4 * i
            blends.append(Blend(data[o], data[o + 1], 0.25 * data[o + 2]))
        tex_mtx_count = data[0xFA]

    soff, scnt = ptr_count("shader")
    shaders = [_parse_shader(data, soff + 0x44 * i, is_map) for i in range(scnt)]

    doff, dcnt = ptr_count("dl")
    dl_infos = []
    for i in range(dcnt):
        o = doff + 0x1C * i
        off, size = struct.unpack_from(">IH", data, o)
        dl_infos.append(DisplayListInfo(off, size))

    model = Model(
        positions,
        normals,
        colors,
        texcoords,
        texture_ids,
        joints,
        blends,
        shaders,
        dl_infos,
        [],
        [],
        normal_flags,
        tex_mtx_count,
        is_map,
    )
    if not is_map:
        model.fine_skins = _parse_fine_skins(data, len(positions))
    for po, _count_off in f["bits"]:
        off = struct.unpack_from(">I", data, po)[0]
        if off and off < n:
            _run_script(model, data, off)
    return model


def _parse_fine_skins(data: bytes, n_positions: int) -> list[FineSkin]:
    """Position fine-skinning config @0x88 (u16 piece count @+2), pieces @ptr 0xA4 (0x74 B),
    weights blob @ptr 0xA8.  Vertices of a piece are consecutive in the position array."""
    n = len(data)
    count = struct.unpack_from(">H", data, 0x8A)[0]
    if count == 0:
        return []
    pieces_off, weights_off = struct.unpack_from(">II", data, 0xA4)
    if not pieces_off or pieces_off + 0x74 * count > n or weights_off >= n:
        return []
    out = []
    for i in range(count):
        o = pieces_off + 0x74 * i
        src_off, wsrc = struct.unpack_from(">II", data, o + 0x60)
        bone0, bone1 = data[o + 0x6C], data[o + 0x6D]
        n_vtx = struct.unpack_from(">H", data, o + 0x70)[0]
        skin_me = data[o + 0x72]
        first = (src_off + skin_me) // 6
        wo = weights_off + wsrc
        if first + n_vtx > n_positions or wo + 2 * n_vtx > n:
            continue
        w = np.frombuffer(data, np.uint8, 2 * n_vtx, wo).reshape(n_vtx, 2).astype(np.float32)
        out.append(FineSkin(first, n_vtx, bone0, bone1, w / 128.0))
    return out


def _vertex_desc(model: Model, bits: _Bits, shader: Shader) -> dict[str, int]:
    vcd: dict[str, int] = {}
    direct = 0
    if not model.is_map and len(model.joints) >= 2:
        direct = 1  # PNMTXIDX
        if shader.hemispheric_probe or shader.reflective_probe:
            direct += 3 if shader.nbt_texture else 1
        direct += model.tex_mtx_count
    vcd["direct"] = direct
    vcd["pos"] = 2 if bits.get(1) else 1
    if not model.is_map and shader.attr_flags & SHADER_ATTR_NRM:
        vcd["nrm"] = 2 if bits.get(1) else 1
    if shader.attr_flags & SHADER_ATTR_CLR:
        vcd["clr"] = 2 if bits.get(1) else 1
    tex16 = bits.get(1)
    for t in range(len(shader.layers)):
        vcd[f"tex{t}"] = 2 if tex16 else 1
    return vcd


def _run_script(model: Model, data: bytes, offset: int) -> None:
    bits = _Bits(data, offset)
    shader_i = 0
    vcd: dict[str, int] = {"direct": 0, "pos": 1}
    matrix_map = [0] * 10
    for _ in range(100000):
        op = bits.get(4)
        if op == 1:
            shader_i = bits.get(6)
        elif op == 2:
            li = bits.get(8)
            if li >= len(model.dl_infos):
                model.warnings.append(f"display list {li} out of range")
                continue
            info = model.dl_infos[li]
            if info.offset + info.size > len(data):
                model.warnings.append(f"display list {li} beyond file")
                continue
            if shader_i < len(model.shaders) and model.shaders[shader_i].flags & SHADER_FLAG_WATER:
                continue  # water surfaces use a special stream; skipped
            dl = data[info.offset : info.offset + info.size]
            model.draws.append(Draw(shader_i, dict(vcd), dl, list(matrix_map)))
        elif op == 3:
            shader = model.shaders[shader_i] if shader_i < len(model.shaders) else None
            if shader is None:
                raise SFAError(f"shader {shader_i} out of range in vertex descriptor")
            vcd = _vertex_desc(model, bits, shader)
        elif op == 4:
            cnt = bits.get(4)
            for i in range(cnt):
                v = bits.get(8)
                if i < 10:
                    matrix_map[i] = v
        elif op == 5:
            return
        elif op == 0:
            continue
        else:
            model.warnings.append(f"unknown render opcode {op}")
            return
    raise SFAError("render script did not terminate")


def _fields(vcd: dict[str, int]) -> list[tuple[str, str]]:
    fields = [(f"d{i}", ">u1") for i in range(vcd.get("direct", 0))]
    for name in ("pos", "nrm", "clr", *[f"tex{t}" for t in range(8)]):
        if name in vcd:
            fields.append((name, ">u2" if vcd[name] == 2 else ">u1"))
    return fields


def parse_display_list(draw: Draw) -> list[tuple[int, int, np.ndarray]]:
    """-> [(opcode, vat, structured index array)] for every primitive of the draw."""
    vdt = np.dtype(_fields(draw.vcd))
    stride = vdt.itemsize
    dl = draw.dl
    out = []
    pos = 0
    n = len(dl)
    while pos + 3 <= n:
        op = dl[pos]
        if op == 0:
            break
        if op & 0xF8 not in _PRIMS:
            raise SFAError(f"unknown display list opcode {op:#x} at {pos}")
        cnt = dl[pos + 1] << 8 | dl[pos + 2]
        pos += 3
        if pos + cnt * stride > n:
            raise SFAError("display list primitive overruns its data")
        out.append((op & 0xF8, op & 7, np.frombuffer(dl, vdt, cnt, pos)))
        pos += cnt * stride
    return out


def scale_positions(raw: np.ndarray, vat: int) -> np.ndarray:
    _t, shift = _VAT.get(vat, _VAT[5])["pos"]
    return raw.astype(np.float32) / float(1 << shift)


def scale_texcoords(raw: np.ndarray, vat: int) -> np.ndarray:
    _t, shift = _VAT.get(vat, _VAT[5])["tex"]
    return raw.astype(np.float32) / float(1 << shift)


def rgba4_to_float(raw: np.ndarray) -> np.ndarray:
    v = raw.astype(np.uint16)
    out = np.empty(v.shape + (4,), np.float32)
    out[..., 0] = ((v >> 12) & 0xF) / 15.0
    out[..., 1] = ((v >> 8) & 0xF) / 15.0
    out[..., 2] = ((v >> 4) & 0xF) / 15.0
    out[..., 3] = (v & 0xF) / 15.0
    return out


# --- textures -----------------------------------------------------------------------------


@dataclass
class Texture:
    width: int
    height: int
    fmt: int
    wrap_s: int
    wrap_t: int
    data: bytes


def texture_entries(tab: bytes, bin_data: bytes, index: int) -> list[bytes]:
    """The wrapped frames of texture `index`, or [] when the table has no such texture."""
    if index < 0 or (index + 1) * 4 > len(tab):
        return []
    v = struct.unpack_from(">I", tab, index * 4)[0]
    if v == 0xFFFFFFFF or not v & 0x80000000:
        return []
    count = (v >> 24) & 0x3F
    off = (v & 0xFFFFFF) * 2
    if off >= len(bin_data):
        return []
    if count <= 1:
        return [bin_data[off:]]
    outs = []
    for i in range(count):
        rel = struct.unpack_from(">I", bin_data, off + 4 * i)[0]
        outs.append(bin_data[off + rel :])
    return outs


def parse_texture(raw: bytes) -> Texture:
    """A texture frame after unwrapping: 0x60 header + GX pixels."""
    if len(raw) < 0x60:
        raise SFAError("texture header too short")
    w, h = struct.unpack_from(">HH", raw, 0xA)
    fmt = raw[0x16]
    if fmt not in gx_texture.TILE_DIMS or fmt in (8, 9, 10) or w == 0 or h == 0:
        raise SFAError(f"unsupported texture format {fmt} ({w}x{h})")
    size = gx_texture.encoded_size(fmt, w, h)
    return Texture(w, h, fmt, raw[0x17], raw[0x18], raw[0x60 : 0x60 + size])


def decode_texture(t: Texture) -> np.ndarray:
    return gx_texture.decode(t.fmt, t.width, t.height, t.data)
