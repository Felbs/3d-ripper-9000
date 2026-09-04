"""Neversoft (Tony Hawk's Underground, GameCube GTDE52): PRE archives (.prg) and
the GameCube texture files (.tex.ngc / .img.ngc).

PRE (.prg on GameCube, .pre/.prx elsewhere) - big-endian on GameCube:
  u32 total size, u32 version (0xABCD0003), u32 file count, then per file:
  u32 size, u32 packed size (0 = stored), u16 name length, u16 pad, u32 name
  checksum, name (NUL padded to the length), data, padding to 4.  Packed data
  is Okumura LZSS (4 KiB window, 3..18 byte matches, flag bits LSB first, a
  set bit is a literal) - the PC PRE format documented by the THPS modding
  tools, byte-swapped for GameCube.

TEX (.tex.ngc) - big-endian:
  u32 version (1), u32 texture count, then per texture: u32 name checksum,
  u32 width, u32 height, u32 mip levels, u32 flag a, u32 flag b, then per level
  u32 size + data.  Pixels are GX CMPR (size == w*h/2) - the only format seen on
  the disc - and a texture may be followed by extra level chains (same sizes,
  no header) that we skip.  A level count of 0 is an empty placeholder.

IMG (.img.ngc) - big-endian:
  u32 version (2), u32 flags, u32 width, u32 height, u32 bits per pixel, u32 pad,
  u32 width, u32 height, u32 pad, then w*h*bpp/8 bytes of GX RGBA8 tiles.

Models (.scn.ngc levels, .mdl.ngc props, .skin.ngc skinned peds/skaters) -
big-endian, GX display lists; the GameCube port of the PC format io_thps_scene
reads (same materials, passes and checksums, different geometry packing):
  0x00 u32 positions, u32 normals (levels: fewer than positions), u16 colours,
       u16 uvs, u32 section size, u16 objects, u16 materials, u32 0, u32
       colour tables (0 in props), u16, u16 passes (the sum of the materials'
       pass counts; that sum is what the parser uses).  Normal and position
       counts are independent (vehicles have more normals than positions).
  0x20 materials x 24: u32 GX register block size (not always exact), u32 0,
       u16 0, u16, 6 x u16 (0xFFFF or small ids), then the register blocks
       (BP/CP/XF loads: TEV, texture samplers, blend mode) at the next 32-byte
       boundary
  big levels: colour tables (u32 n, n x (u32 key, RGBA8), 32-byte padded; the
       header's u32 at 0x1C counts them)
  materials x 32 (4-byte aligned): u32 checksum, u8 pass count, u8 flags, u16
       flags, f32 draw distance, u16 first pass, u16 index, u32 0, u32 alpha,
       u32 name checksum, u32 0
  big levels: a block of float parameters (fog / water?), then
  passes x 32: u32 texture checksum (a .tex.ngc entry), u32 flags, u32 -1 / 0,
       RGBA8 colour, u16 0, u16 wrap, u16 wrap, u16 0, u32 1 << 16, u32 0
  vertex arrays, packed in order: f32 xyz positions, RGBA8 colours, s16 uv
       (10 fraction bits), s16 xyz normals (14 fraction bits); the next 32-byte
       boundary starts the objects
  objects: 64-byte header (u16 meshes, u16, u32 skin block size, u16 skinned
       vertices, u16 bones, u16, u16 0xFFFF or 0, 32 bytes, f32 bounding
       sphere xyzr), the skin block (groups of u32 count, u32 bone, count x s16
       xyz position + s16 xyz normal in bone space; only the single-bone groups
       are understood), then the meshes
  mesh: 64-byte header (u32 display list size, u32 material checksum, u32
       flags, u32, f32 bounding sphere, u32 0, u16 0x15, u16, u16 vertices,
       u16, u32 display list size, f32, 12 bytes) and the display list: CP
       VCD_LO / VCD_HI loads, XF 0x1008, then GX draw commands (0x98 | VAT 7
       strips ...) whose vertices are 8/16-bit indices into the arrays above.
Collision (.col.ngc) is not decoded.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

PRE_VERSION = 0xABCD0003
PRE_VERSION_2 = 0xABCD0002  # Tony Hawk's Pro Skater 4: 12-byte entries, no checksum


class NeversoftError(ValueError):
    pass


# ---------------------------------------------------------------------------
# PRE
# ---------------------------------------------------------------------------


def _pre_order(data: bytes) -> str | None:
    """ ">" for the GameCube-native archives, "<" for Tony Hawk's Pro Skater 3's, which kept
    the PC byte order (version 0xabcd0002 little-endian)."""
    for order in (">", "<"):
        total, version, count = struct.unpack_from(order + "III", data, 0)
        if version in (PRE_VERSION, PRE_VERSION_2) and 0 < count < 100000 and total >= 12:
            return order
    return None


def is_pre(data: bytes) -> bool:
    return len(data) >= 12 and _pre_order(data) is not None


def lzss_decompress(src: bytes, out_size: int) -> bytes:
    n_ring = 4096
    ring = bytearray(n_ring)
    r = n_ring - 18
    out = bytearray()
    i = 0
    flags = 0
    n = len(src)
    while len(out) < out_size and i < n:
        flags >>= 1
        if not flags & 0x100:
            flags = src[i] | 0xFF00
            i += 1
        if flags & 1:
            c = src[i]
            i += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) & (n_ring - 1)
        else:
            if i + 1 >= n:
                break
            b0, b1 = src[i], src[i + 1]
            i += 2
            off = b0 | ((b1 & 0xF0) << 4)
            ln = (b1 & 0x0F) + 3
            for k in range(ln):
                c = ring[(off + k) & (n_ring - 1)]
                out.append(c)
                ring[r] = c
                r = (r + 1) & (n_ring - 1)
    return bytes(out[:out_size])


def pre_entries(data: bytes) -> list[tuple[str, bytes]]:
    if not is_pre(data):
        raise NeversoftError("not a PRE archive")
    order = _pre_order(data) or ">"
    _total, version, count = struct.unpack_from(order + "III", data, 0)
    pos = 12
    out = []
    entry = 12 if version == PRE_VERSION_2 else 16
    for _ in range(count):
        if pos + entry > len(data):
            break
        size, packed, name_len, _pad = struct.unpack_from(order + "IIHH", data, pos)
        pos += entry  # THUG's entry ends with a u32 checksum; THPS4's has none
        name = data[pos : pos + name_len].split(b"\0", 1)[0].decode("latin-1")
        pos += name_len
        stored = packed or size
        blob = data[pos : pos + stored]
        pos = (pos + stored + 3) & ~3
        if packed:
            blob = lzss_decompress(blob, size)
        out.append((name.replace("\\", "/"), blob))
    return out


# ---------------------------------------------------------------------------
# textures
# ---------------------------------------------------------------------------


@dataclass
class Texture:
    checksum: int
    width: int
    height: int
    levels: list[bytes]
    flag_a: int = 0
    flag_b: int = 0

    def decode(self) -> np.ndarray | None:
        if not self.levels or self.width == 0 or self.height == 0:
            return None
        blob = self.levels[0]
        fmt = 14 if len(blob) * 8 == self.width * self.height * 4 else None
        if fmt is None and len(blob) == self.width * self.height * 4:
            fmt = 6
        if fmt is None and len(blob) == self.width * self.height * 2:
            fmt = 5
        if fmt is None:
            return None
        # stored bottom-up
        return np.ascontiguousarray(gx_texture.decode(fmt, self.width, self.height, blob)[::-1])


def is_tex(data: bytes) -> bool:
    if len(data) < 32:
        return False
    version, count = struct.unpack_from(">II", data, 0)
    if version != 1 or not 0 < count < 4096:
        return False
    _crc, w, h, lv = struct.unpack_from(">IIII", data, 8)
    return w <= 4096 and h <= 4096 and lv <= 16


def parse_tex(data: bytes) -> list[Texture]:
    if not is_tex(data):
        raise NeversoftError("not a THUG .tex.ngc")
    _version, count = struct.unpack_from(">II", data, 0)
    pos = 8
    out = []
    n = len(data)
    for _ in range(count):
        if pos + 24 > n:
            break
        crc, w, h, lv, a, b = struct.unpack_from(">6I", data, pos)
        pos += 24
        levels = []
        for _ in range(lv):
            if pos + 4 > n:
                break
            size = struct.unpack_from(">I", data, pos)[0]
            pos += 4
            levels.append(data[pos : pos + size])
            pos += size
        # extra chains (same level sizes, no header) follow some textures
        first = len(levels[0]) if levels else -1
        while levels and pos + 4 <= n and struct.unpack_from(">I", data, pos)[0] == first:
            for _ in range(lv):
                if pos + 4 > n:
                    break
                size = struct.unpack_from(">I", data, pos)[0]
                pos += 4 + size
        out.append(Texture(crc, w, h, levels, a, b))
    return out


def is_img(data: bytes) -> bool:
    if len(data) < 36:
        return False
    version, _flags, w, h, bpp = struct.unpack_from(">IIIII", data, 0)
    return version == 2 and 0 < w <= 4096 and 0 < h <= 4096 and bpp in (4, 8, 16, 32)


def parse_img(data: bytes) -> Texture:
    if not is_img(data):
        raise NeversoftError("not a THUG .img.ngc")
    _version, _flags, w, h, bpp = struct.unpack_from(">IIIII", data, 0)
    return Texture(0, w, h, [data[36 : 36 + w * h * bpp // 8]])


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

_MODEL_HEADER = struct.Struct(">IIHHIHHIII")
_MATERIAL = struct.Struct(">IBBHfHHIIII")
_PASS = struct.Struct(">IIII")
_OBJECT = struct.Struct(">HHIHHHH")
_DRAW_OPS = (0x80, 0x90, 0x98, 0xA0)

UV_FRAC = 10
NRM_FRAC = 14


@dataclass
class ModelMaterial:
    checksum: int
    name_checksum: int
    textures: list[int]  # texture checksums of the passes
    flags: int
    alpha: int


@dataclass
class Mesh:
    material: int  # checksum
    flags: int
    corners: dict[str, np.ndarray]  # attr -> (N,) int index per corner
    triangles: np.ndarray  # (T,3) into the corner arrays


@dataclass
class SkinGroup:
    bone: int
    positions: np.ndarray  # (N,3) f32 bone space
    normals: np.ndarray  # (N,3) f32


@dataclass
class ModelObject:
    meshes: list[Mesh]
    sphere: tuple[float, float, float, float]
    skin: list[SkinGroup] = field(default_factory=list)


@dataclass
class Model:
    positions: np.ndarray  # (P,3) f32
    normals: np.ndarray  # (N,3) f32
    colors: np.ndarray  # (C,4) u8 RGBA
    uvs: np.ndarray  # (U,2) f32
    materials: list[ModelMaterial]
    objects: list[ModelObject]
    warnings: list[str] = field(default_factory=list)

    @property
    def skinned(self) -> bool:
        return any(o.skin for o in self.objects)

    @property
    def triangle_count(self) -> int:
        return sum(len(m.triangles) for o in self.objects for m in o.meshes)


def is_model(data: bytes, size: int | None = None) -> bool:
    if len(data) < 0x20:
        return False
    total = size if size is not None else len(data)
    npos, nnrm, _ncol, _nuv, sec, nobj, nmat, z1, _u, _npass = _MODEL_HEADER.unpack_from(data, 0)
    if z1 or nmat == 0 or nmat > 8192 or nobj == 0 or sec == 0:
        return False
    if nnrm > 0x400000 or npos > 0x400000 or sec > total:
        return False
    return 0x20 + nmat * 24 <= total


def _vcd_fields(lo: int, hi: int) -> list[tuple[str, int]]:
    """(attribute, bytes) per corner from the CP VCD_LO/VCD_HI registers; only
    indexed attributes appear (direct data is not used by these files)."""
    fields = []
    if lo & 1:
        fields.append(("pnmtx", 1))
    for i in range(8):
        if (lo >> (1 + i)) & 1:
            fields.append((f"tmtx{i}", 1))
    sizes = {0: 0, 1: 0, 2: 1, 3: 2}
    for name, shift in (("pos", 9), ("nrm", 11), ("col0", 13), ("col1", 15)):
        n = sizes[(lo >> shift) & 3]
        if n:
            fields.append((name, n))
    for i in range(8):
        n = sizes[(hi >> (2 * i)) & 3]
        if n:
            fields.append((f"tex{i}", n))
    return fields


def _triangulate(op: int, n: int) -> np.ndarray:
    if n < 3:
        return np.zeros((0, 3), np.int64)
    if op == 0x98:
        i = np.arange(n - 2)
        b = np.where(i % 2 == 0, i + 1, i + 2)
        c = np.where(i % 2 == 0, i + 2, i + 1)
        return np.stack([i, b, c], axis=1)
    if op == 0x90:
        return np.arange(n - n % 3).reshape(-1, 3)
    if op == 0xA0:
        i = np.arange(1, n - 1)
        return np.stack([np.zeros_like(i), i, i + 1], axis=1)
    q = np.arange(n // 4) * 4
    return np.concatenate([np.stack([q, q + 1, q + 2], 1), np.stack([q, q + 2, q + 3], 1)])


def _parse_mesh_dl(dl: bytes, material: int, flags: int) -> Mesh | None:
    pos = 0
    lo = hi = None
    n = len(dl)
    while pos < n:
        op = dl[pos]
        if op == 0x08 and pos + 6 <= n:
            reg = dl[pos + 1]
            val = struct.unpack_from(">I", dl, pos + 2)[0]
            if reg == 0x50:
                lo = val
            elif reg == 0x60:
                hi = val
            pos += 6
        elif op == 0x10 and pos + 5 <= n:
            cnt = struct.unpack_from(">H", dl, pos + 1)[0] + 1
            pos += 5 + 4 * cnt
        elif op == 0x61:
            pos += 5
        else:
            break
    if lo is None or hi is None:
        return None
    fields = _vcd_fields(lo, hi)
    if not fields:
        return None
    vdt = np.dtype([(name, ">u1" if size == 1 else ">u2") for name, size in fields])
    stride = vdt.itemsize
    corners: dict[str, list[np.ndarray]] = {name: [] for name, _ in fields}
    tris = []
    base = 0
    while pos + 3 <= n:
        op = dl[pos] & 0xF8
        if op not in _DRAW_OPS:
            break
        count = struct.unpack_from(">H", dl, pos + 1)[0]
        pos += 3
        if pos + count * stride > n:
            break
        arr = np.frombuffer(dl, vdt, count, pos)
        pos += count * stride
        for name, _ in fields:
            corners[name].append(arr[name].astype(np.int64))
        tris.append(_triangulate(op, count) + base)
        base += count
    if not tris:
        return None
    return Mesh(
        material,
        flags,
        {k: np.concatenate(v) for k, v in corners.items()},
        np.concatenate(tris),
    )


def _material_table(data: bytes, nmat: int) -> int | None:
    """Offset of the 32-byte material records: the first 4-byte boundary after
    the register blocks (and the colour tables big levels put there) where the
    records' index fields count 0, 1, 2, ... (the block sizes in the 24-byte
    records overstate some blocks, so they are not summed)."""
    start = (0x20 + nmat * 24 + 31) & ~31
    probe = min(nmat, 4)
    for p in range(start, len(data) - 32 * probe, 4):
        ok = True
        for i in range(probe):
            q = p + 32 * i
            if (
                struct.unpack_from(">H", data, q + 14)[0] != i
                or data[q + 16 : q + 23] != bytes(7)  # u32 0, then the alpha's high bytes
                or data[q + 23] == 0  # alpha itself
                or not 1 <= data[q + 4] <= 16  # pass count
            ):
                ok = False
                break
        if ok:
            return p
    return None


def _pass_table(data: bytes, start: int, npass: int) -> int | None:
    """Offset of the 32-byte pass records at or after `start` (big levels put a
    block of float parameters between the materials and the passes): records
    end with u32 1 << 16, u32 0 and have zero bytes around the wrap fields."""
    probe = min(npass, 3)
    if probe == 0:
        return start
    for p in range(start, len(data) - 32 * probe, 4):
        ok = True
        for i in range(probe):
            q = p + 32 * i
            if data[q + 24 : q + 32] != b"\0\1\0\0\0\0\0\0" or data[q + 21 : q + 24] != bytes(3):
                ok = False
                break
        if ok:
            return p
    return None


def parse_model(data: bytes) -> Model:
    if not is_model(data):
        raise NeversoftError("not a THUG GameCube model")
    npos, nnrm, ncol, nuv, _sec, nobj, nmat, _z1, _z2, _npass = _MODEL_HEADER.unpack_from(data, 0)
    warnings: list[str] = []
    p = _material_table(data, nmat)
    if p is None:
        raise NeversoftError("material table not found")
    materials: list[ModelMaterial] = []
    raw_mats = []
    for _ in range(nmat):
        if p + 32 > len(data):
            raise NeversoftError("material table truncated")
        raw_mats.append(_MATERIAL.unpack_from(data, p))
        p += 32
    npass = sum(m[1] for m in raw_mats)
    p = _pass_table(data, p, npass)
    if p is None:
        raise NeversoftError("pass table not found")
    passes = []
    for _ in range(npass):
        if p + 32 > len(data):
            raise NeversoftError("pass table truncated")
        passes.append(_PASS.unpack_from(data, p))
        p += 32
    for crc, count, f1, f2, _dist, first, _idx, _z, alpha, name, _z2 in raw_mats:
        texs = [passes[j][0] for j in range(first, min(first + count, npass))]
        materials.append(ModelMaterial(crc, name, texs, f1 | (f2 << 8), alpha))

    def block(count: int, size: int) -> bytes:
        nonlocal p
        raw = data[p : p + count * size]
        p += count * size
        return raw

    raw = block(npos, 12)
    positions = np.frombuffer(raw, ">f4", len(raw) // 12 * 3).reshape(-1, 3).astype(np.float32)
    raw = block(ncol, 4)
    colors = np.frombuffer(raw, np.uint8, len(raw) // 4 * 4).reshape(-1, 4).copy()
    raw = block(nuv, 4)
    uvs = np.frombuffer(raw, ">i2", len(raw) // 4 * 2).reshape(-1, 2).astype(np.float32)
    uvs /= float(1 << UV_FRAC)
    raw = block(nnrm, 6)
    normals = np.frombuffer(raw, ">i2", len(raw) // 6 * 3).reshape(-1, 3).astype(np.float32)
    normals /= float(1 << NRM_FRAC)
    p = (p + 31) & ~31
    objects: list[ModelObject] = []
    for oi in range(nobj):
        if p + 64 > len(data):
            warnings.append(f"object {oi}: header past end")
            break
        nmesh, _u1, skin_size, _nskin, _nbones, _u2, _tag = _OBJECT.unpack_from(data, p)
        if nmesh == 0 or nmesh > 4096 or p + 64 + skin_size > len(data):
            warnings.append(f"object {oi}: bad header at {p:#x}")
            break
        sphere = struct.unpack_from(">4f", data, p + 48)
        p += 64
        skin: list[SkinGroup] = []
        end = p + skin_size
        while p + 8 <= end:
            count, bone = struct.unpack_from(">II", data, p)
            p += 8
            if count == 0 or p + count * 12 > end:
                break
            v = np.frombuffer(data, ">i2", count * 6, p).reshape(count, 6).astype(np.float32)
            skin.append(SkinGroup(bone, v[:, :3].copy(), v[:, 3:] / float(1 << NRM_FRAC)))
            p += count * 12
        p = end
        meshes: list[Mesh] = []
        for mi in range(nmesh):
            if p + 64 > len(data):
                warnings.append(f"object {oi} mesh {mi}: header past end")
                break
            dl_size, material, flags = struct.unpack_from(">III", data, p)
            if dl_size == 0 or p + 64 + dl_size > len(data):
                warnings.append(f"object {oi} mesh {mi}: bad display list size at {p:#x}")
                break
            p += 64
            mesh = _parse_mesh_dl(data[p : p + dl_size], material, flags)
            p += dl_size
            if mesh is not None:
                meshes.append(mesh)
        objects.append(ModelObject(meshes, sphere, skin))
    return Model(positions, normals, colors, uvs, materials, objects, warnings)


# ---------------------------------------------------------------------------
# Tony Hawk's Pro Skater 3: GCTX pictures inside the (little-endian) .pre archives
# ---------------------------------------------------------------------------

GCTX_MAGIC = b"GCTX"
GCTX_HEADER = 0x60
GCTX_NAME_AT = 24


def is_gctx(data: bytes) -> bool:
    if len(data) < GCTX_HEADER or data[:4] != GCTX_MAGIC:
        return False
    w, h, bpp, levels, size = struct.unpack_from(">HHHHI", data, 4)
    return bpp in (4, 8, 16, 32) and 0 < w <= 2048 and 0 < h <= 2048 and size == w * h * bpp // 8


def gctx(data: bytes) -> np.ndarray | None:
    """``GCTX, u16 width, u16 height, u16 bits per pixel, u16 levels, u32 bytes`` and the
    file name at +24; pixels at +0x60 (GX tiled), and for 8- and 4-bit pictures an RGB5A3
    palette straight after them (256 or 16 entries).  16 bits is RGB5A3, 32 RGBA8."""
    from gcrip.formats import gx_texture  # noqa: PLC0415

    if not is_gctx(data):
        return None
    w, h, bpp, _levels, size = struct.unpack_from(">HHHHI", data, 4)
    px = data[GCTX_HEADER : GCTX_HEADER + size]
    if len(px) < size:
        return None
    try:
        if bpp in (8, 4):
            entries = 256 if bpp == 8 else 16
            pal = data[GCTX_HEADER + size : GCTX_HEADER + size + 2 * entries]
            if len(pal) < 2 * entries:
                return None
            fmt = 9 if bpp == 8 else 8
            return gx_texture.decode(fmt, w, h, px, gx_texture.decode_palette(2, pal, entries))
        return gx_texture.decode(5 if bpp == 16 else 6, w, h, px)
    except ValueError:
        return None
