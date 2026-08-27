"""Resident Evil 4 (GameCube, G4BE08 / G4BJ08 / Wii RB4E08): the DAS/DRS/UDAS
containers, the DAT tables inside them and the big-endian BIN model format.

Containers (all big-endian):
  DAS / DRS / UDAS
    0x000  32 bytes of filler (repeated 0xCAB6BE20, or a Shift-JIS comment)
    0x020  up to two 32-byte slots: u32 type, u32 size, u32 unused, u32 offset
           (type 0 = the DAT table, 4 = sound bank, 0xFFFFFFFF = end)
    0x400  first slot's data
    Stage files (St?/r???.das) wrap the DAT in "YZ2" compression: the slot data
    starts with two ASCII hex sizes ("<packed>\\t<unpacked>\\n"), is padded to
    0x20 and then a range-coded stream tagged 0xCE2843DD begins.  That codec is
    Yamazaki Satoshi's yz2 (source in JADERLINK/RE4_DASYZ2_TOOL); we leave those
    slots packed and report them.
  DAT
    u32 count, 12 bytes zero, then count u32 offsets, then count 4-byte
    extensions ("BIN\\0", "TPL\\0", "SMD\\0", "ESL\\0", ...).  In a DRS the
    second u32 is the offset of a trailing REL (enemy code) that ends the table.
    Zero extensions are unused slots.

BIN model (documented by JADERLINK/RE4-GCWII-BIN-TOOL):
  0x00 u32 bone offset (0x40 old / 0x60 new header)   0x0C u32 vertex colour offset
  0x10 u32 uv offset   0x14 u32 weight map offset      0x18 u8 weight maps, u8 bones,
  u16 materials   0x1C u32 material offset   0x20 u32 flags (0x80000000 "modern":
  colour index in faces and byte UVs; 0x40000000 vertex colours; 0x20000000 byte
  normals)   0x24 u32 texture count   0x28 u8 vertex scale (power of two)
  0x2A u16 weight maps (16-bit)   0x2C u32 morph offset   0x30 u32 position offset
  0x34 u32 normal offset   0x38 u16 positions, u16 normals
  Positions: i16 x y z, u8 pad, u8 weight map (8 bytes) / 2^scale / 100.
  Normals: i16 x y z pad, or i8 x y z + u8 with the byte-normals flag.
  UVs: i16 u v (/32767, or /255 in modern files).  Colours: BGRA.
  Materials: 24 bytes (byte 12 = diffuse texture index into the sibling TPL)
  then u32 buffer size, u32 pad and GX-style packets: u8 primitive (0x98 strip,
  0x90 triangles, 0x80 quads, 0xA0 fan), u16 count, count x (u16 position, u16
  normal, [u16 colour], u16 uv).
  Bones: u8 id, u8 parent, u16 pad, f32 x y z (local offset).
  Weight maps: u8 bone x3, u8 count, u8 weight x3, u8 pad.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

YZ2_TAG = b"\xce\x28\x43\xdd"
FILLER = b"\xca\xb6\xbe\x20"
POSITION_SCALE = 100.0

FLAG_MODERN = 0x80000000
FLAG_VERTEX_COLORS = 0x40000000
FLAG_BYTE_NORMALS = 0x20000000


class Re4Error(ValueError):
    pass


# ---------------------------------------------------------------------------
# containers
# ---------------------------------------------------------------------------


def is_das(data: bytes) -> bool:
    if len(data) < 0x420:
        return False
    second = data[0x40:0x44]
    if data[:4] != FILLER and not (
        data[0x1C:0x20] == b"\0\0\0\0"
        and second in (b"\0\0\0\4", b"\xff\xff\xff\xff", b"\xff\xff\xff\xfe")
    ):
        return False
    typ, size, _unused, off = struct.unpack_from(">IIII", data, 0x20)
    return typ in (0, 4) and off == 0x400 and 0 < size <= len(data) - 0x400


def is_yz2(data: bytes) -> bool:
    return YZ2_TAG in data[:0x40]


def das_slots(data: bytes) -> list[tuple[int, int, int]]:
    """(type, offset, size) for each used slot of a DAS/DRS/UDAS."""
    out = []
    pos = 0x20
    for _ in range(2):
        if pos + 16 > len(data):
            break
        typ, size, _u, off = struct.unpack_from(">IIII", data, pos)
        if typ == 0xFFFFFFFF:
            break
        if off < len(data):
            out.append((typ, off, min(size, len(data) - off)))
        pos += 0x20
    return out


def is_dat(data: bytes) -> bool:
    if len(data) < 0x20:
        return False
    count = struct.unpack_from(">I", data, 0)[0]
    if not 0 < count < 0x10000 or 0x10 + count * 8 > len(data):
        return False
    first = struct.unpack_from(">I", data, 0x10)[0]
    return first >= 0x10 + count * 8 and first <= len(data)


def _clean_ext(raw: bytes) -> str:
    return "".join(chr(c) for c in raw if 48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122)


def dat_entries(data: bytes, base: str) -> list[tuple[str, bytes]]:
    """Members of a DAT table as (name, bytes); names are <base>_NNN.<EXT>."""
    count, rel_off, u3, u4 = struct.unpack_from(">IIII", data, 0)
    end = len(data)
    extra_rel = None
    if u3 == 0 and u4 == 0 and rel_off and rel_off < end:
        extra_rel = rel_off  # DRS: the enemy REL sits after the table members
        end = rel_off
    offs = struct.unpack_from(f">{count}I", data, 0x10)
    ext_base = 0x10 + count * 4
    exts = [_clean_ext(data[ext_base + i * 4 : ext_base + i * 4 + 4]) for i in range(count)]
    out = []
    for i, (off, ext) in enumerate(zip(offs, exts, strict=True)):
        nxt = offs[i + 1] if i + 1 < count else end
        if not ext or off >= len(data) or nxt < off:
            continue
        nxt = min(nxt, len(data))
        out.append((f"{base}_{i:03d}.{ext.upper()}", data[off:nxt]))
    if extra_rel is not None:
        out.append((f"{base}_EXTRA.REL", data[extra_rel:]))
    return out


def expand_das(data: bytes, base: str) -> list[tuple[str, bytes]]:
    out = []
    for typ, off, size in das_slots(data):
        blob = data[off : off + size]
        if typ == 0:
            if is_yz2(blob):
                out.append((f"{base}.yz2", blob))
            elif is_dat(blob):
                out.extend(dat_entries(blob, base))
            else:
                out.append((f"{base}_slot0.bin", blob))
        elif size:
            out.append((f"{base}_snd.dat", blob))
    return out


# ---------------------------------------------------------------------------
# BIN models
# ---------------------------------------------------------------------------


@dataclass
class Material:
    params: bytes  # 24 raw bytes
    texture: int  # diffuse map index into the TPL
    faces: np.ndarray  # (T, 3, 4) int: [position, normal, colour, uv] per corner


@dataclass
class Bone:
    id: int
    parent: int
    position: tuple[float, float, float]


@dataclass
class BinModel:
    flags: int
    positions: np.ndarray  # (N,3) f32 metres
    weight_index: np.ndarray  # (N,) u8
    normals: np.ndarray  # (M,3) f32
    uvs: np.ndarray  # (K,2) f32
    colors: np.ndarray | None  # (C,4) u8 RGBA
    materials: list[Material]
    bones: list[Bone]
    weight_maps: np.ndarray  # (W, 8) u8: bone x3, count, weight x3, pad
    warnings: list[str] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return sum(len(m.faces) for m in self.materials)


def is_bin(data: bytes, size: int | None = None) -> bool:
    """Sniff on the header; `size` is the whole file's length when only the head
    is available."""
    if len(data) < 0x40:
        return False
    total = size if size is not None else len(data)
    bone_off = struct.unpack_from(">I", data, 0)[0]
    if bone_off not in (0x40, 0x60):
        return False
    mat_off = struct.unpack_from(">I", data, 0x1C)[0]
    pos_off = struct.unpack_from(">I", data, 0x30)[0]
    mat_count = struct.unpack_from(">H", data, 0x1A)[0]
    return 0 < mat_off < total and 0 < pos_off < total and 0 < mat_count < 4096


def _packets(buf: bytes, modern: bool) -> list[tuple[int, np.ndarray]]:
    """GX-style index packets: (primitive, (count, 4) [pos, nrm, col, uv])."""
    out = []
    pos = 0
    n = len(buf)
    stride = 8 if modern else 6
    while pos + 3 <= n:
        prim = buf[pos]
        if prim not in (0x98, 0x90, 0x80, 0xA0):
            break
        count = struct.unpack_from(">H", buf, pos + 1)[0]
        pos += 3
        if pos + count * stride > n:
            break
        raw = np.frombuffer(buf, ">u2", count * (stride // 2), pos).reshape(count, stride // 2)
        pos += count * stride
        idx = np.zeros((count, 4), np.int64)
        idx[:, 0] = raw[:, 0]
        idx[:, 1] = raw[:, 1]
        if modern:
            idx[:, 2] = raw[:, 2]
            idx[:, 3] = raw[:, 3]
        else:
            idx[:, 3] = raw[:, 2]
        out.append((prim, idx))
    return out


def _triangles(prim: int, idx: np.ndarray) -> np.ndarray:
    n = len(idx)
    if prim == 0x98 and n >= 3:
        i = np.arange(n - 2)
        a = i
        b = np.where(i % 2 == 0, i + 1, i + 2)
        c = np.where(i % 2 == 0, i + 2, i + 1)
        tri = np.stack([a, b, c], axis=1)
    elif prim == 0x90:
        tri = np.arange(n - n % 3).reshape(-1, 3)
    elif prim == 0x80:
        q = np.arange(n // 4) * 4
        tri = np.concatenate([np.stack([q, q + 1, q + 2], 1), np.stack([q, q + 2, q + 3], 1)])
    elif prim == 0xA0 and n >= 3:
        i = np.arange(1, n - 1)
        tri = np.stack([np.zeros_like(i), i, i + 1], axis=1)
    else:
        return np.zeros((0, 3, 4), np.int64)
    faces = idx[tri]  # (T,3,4)
    p = faces[:, :, 0]
    keep = (p[:, 0] != p[:, 1]) & (p[:, 0] != p[:, 2]) & (p[:, 1] != p[:, 2])
    return faces[keep]


def parse(data: bytes) -> BinModel:
    if not is_bin(data):
        raise Re4Error("not a RE4 GC BIN model")
    (
        bone_off,
        _u04,
        _u08,
        color_off,
        uv_off,
        wmap_off,
        wmap_count,
        bone_count,
        mat_count,
        mat_off,
        flags,
        _tex_count,
        vscale,
        _u29,
        wmap2_count,
        _morph_off,
        pos_off,
        nrm_off,
        _pos_count,
        _nrm_count,
    ) = struct.unpack_from(">IIIIIIBBHIIIBBHIIIHH", data, 0)
    modern = bool(flags & FLAG_MODERN)
    warnings: list[str] = []
    materials: list[Material] = []
    p = mat_off
    max_pos = max_nrm = max_col = max_uv = 0
    for _ in range(mat_count):
        if p + 32 > len(data):
            warnings.append("material table truncated")
            break
        params = data[p : p + 24]
        buf_size = struct.unpack_from(">I", data, p + 24)[0]
        p += 32
        buf = data[p : p + buf_size]
        p += buf_size
        tris = [_triangles(prim, idx) for prim, idx in _packets(buf, modern)]
        faces = np.concatenate(tris) if tris else np.zeros((0, 3, 4), np.int64)
        if len(faces):
            max_pos = max(max_pos, int(faces[:, :, 0].max()) + 1)
            max_nrm = max(max_nrm, int(faces[:, :, 1].max()) + 1)
            max_col = max(max_col, int(faces[:, :, 2].max()) + 1)
            max_uv = max(max_uv, int(faces[:, :, 3].max()) + 1)
        materials.append(Material(params, params[12], faces))
    scale = POSITION_SCALE * float(2**vscale)

    def block(off: int, count: int, size: int) -> bytes:
        end = off + count * size
        if off <= 0 or end > len(data):
            return data[off : min(end, len(data))] if 0 < off < len(data) else b""
        return data[off:end]

    raw = block(pos_off, max_pos, 8)
    n = len(raw) // 8
    pr = np.frombuffer(raw[: n * 8], ">i2").reshape(n, 4)
    positions = np.zeros((n, 3), np.float32)
    positions[:, 0] = pr[:, 0] / scale
    positions[:, 1] = pr[:, 1] / scale
    positions[:, 2] = pr[:, 2] / scale
    weight_index = np.frombuffer(raw[: n * 8], np.uint8).reshape(n, 8)[:, 7].copy()
    if flags & FLAG_BYTE_NORMALS:
        raw = block(nrm_off, max_nrm, 4)
        m = len(raw) // 4
        nr = np.frombuffer(raw[: m * 4], np.int8).reshape(m, 4)[:, :3].astype(np.float32)
    else:
        raw = block(nrm_off, max_nrm, 8)
        m = len(raw) // 8
        nr = np.frombuffer(raw[: m * 8], ">i2").reshape(m, 4)[:, :3].astype(np.float32)
    ln = np.linalg.norm(nr, axis=1)
    ln[ln == 0] = 1
    normals = nr / ln[:, None]
    raw = block(uv_off, max_uv, 4)
    k = len(raw) // 4
    ur = np.frombuffer(raw[: k * 4], ">i2").reshape(k, 2).astype(np.float32)
    uvs = ur / (255.0 if modern else 32767.0)
    colors = None
    if color_off and flags & FLAG_VERTEX_COLORS and max_col:
        raw = block(color_off, max_col, 4)
        c = len(raw) // 4
        bgra = np.frombuffer(raw[: c * 4], np.uint8).reshape(c, 4)
        colors = np.concatenate([bgra[:, 2::-1], bgra[:, 3:4]], axis=1)
    bones = []
    for i in range(bone_count):
        o = bone_off + i * 16
        if o + 16 > len(data):
            break
        bid, parent = data[o], data[o + 1]
        x, y, z = struct.unpack_from(">3f", data, o + 4)
        s = POSITION_SCALE
        bones.append(Bone(bid, parent, (x / s, y / s, z / s)))
    wcount = wmap2_count if wmap2_count > 255 else wmap_count
    weight_maps = np.zeros((0, 8), np.uint8)
    if wmap_off and wcount:
        raw = block(wmap_off, wcount, 8)
        weight_maps = np.frombuffer(raw[: len(raw) // 8 * 8], np.uint8).reshape(-1, 8).copy()
    return BinModel(
        flags,
        positions,
        weight_index,
        normals,
        uvs,
        colors,
        materials,
        bones,
        weight_maps,
        warnings,
    )
