"""Ubisoft Jade engine binarized data (Beyond Good & Evil, Prince of Persia: The
Sands of Time on GameCube): the contents of a level's ROOT/Bin/ffxxxxxx.bin pack
after LZO decoding (jade_lzo), the TEX_File texture headers and the GEO
geometric objects inside it.

Two dialects share the layout, told apart by the per-file header in the pack:

  Montpellier (BG&E, sally.bf, version 34):
      u32 size, then the file - no key, no marker.  Files come in the order the
      engine's loader resolved references, so a pack is only fully walkable by
      re-implementing the loader.  We walk what we can (texture packs are
      regular) and otherwise find geometry by signature.
  Montreal (PoP SoT, prince.bf, version 37):
      u32 size, u8[4] 99 C0 FF EE, u32 key, then the file.  Keys make the pack a
      flat archive.  A bare u32 with no marker after it is a "size request" and
      is skipped.

All multi-byte values are little-endian, on GameCube too (the engine byte-swaps
at load time).  Structures follow Ray1Map (BinarySerializer/Ray1Map,
Assets/Scripts/Games/Jade/Serializable/{GEO,TEX,GRO}/*.cs).

GEO (GRO_Struct type 1) - what the game calls a GRO / "graphic render object":
  vertices, optional normals, per-vertex colours, a UV pool, and elements
  (one per material slot) holding triangles as (v0 v1 v2 uv0 uv1 uv2).  PoP
  additionally carries a GameCube-optimised copy (GEO_GeoObject_GC): per element
  a list of triangle strips whose points index the vertex/normal/colour/UV pools.

TEX_File header (32 bytes, at the start of the file in binarized packs):
  i32 -1, u16 flags, u8 type, u8 colour format, u16 width, u16 height, u32 colour,
  u32 font descriptor key, u32 0xCAD01234, u32 0xFF00FF, u32 0xC0DEC0DE
  Types: 1 TGA (18-byte TGA header + BGRA rows), 6 Raw (linear 4/8-bit indices
  into a palette), 7 RawPal (12-byte slot: raw key, palette key, 24/32-bit key),
  10 JTX (u32 version, u32 format, u32 w, u32 h, i32 mips, f32 bias, [palette key],
  then the pixels: plain little-endian DXT1 blocks for S3TC, a second DXT1 image
  as the alpha plane for S3TC_A, or 4/8-bit intensity/alpha channels).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

import numpy as np

MARK = b"\x99\xc0\xff\xee"
CODE_2002 = 0xC0DE2002
CODE_0008 = 0xC0DE0008
DEADBABE = 0xDEADBABE

GRO_GEO = 1
GRO_MAT_SIN = 3
GRO_MAT_MSM = 4
GRO_MAT_MTT = 5
GRO_STATIC_LOD = 8

TEX_TGA = 1
TEX_RAW = 6
TEX_RAWPAL = 7
TEX_JTX = 10
TEX_HEADER_SIZE = 0x20


class JadeError(ValueError):
    pass


# ---------------------------------------------------------------------------
# pack walking
# ---------------------------------------------------------------------------


@dataclass
class BinEntry:
    index: int
    key: int | None  # None in Montpellier packs
    offset: int
    data: bytes


def is_montreal(dec: bytes) -> bool:
    return len(dec) >= 12 and dec[4:8] == MARK


def walk_montreal(dec: bytes) -> list[BinEntry]:
    out = []
    pos = 0
    n = len(dec)
    while pos + 4 <= n:
        size = struct.unpack_from("<I", dec, pos)[0]
        if pos + 12 <= n and dec[pos + 4 : pos + 8] == MARK:
            key = struct.unpack_from("<I", dec, pos + 8)[0]
            body = dec[pos + 12 : pos + 12 + size]
            out.append(BinEntry(len(out), key, pos + 12, body))
            pos += 12 + size
        else:
            pos += 4  # size request: a bare u32
    return out


def walk_montpellier(dec: bytes, *, stop_on_bad: bool = True) -> list[BinEntry]:
    """Sequential walk of u32 size + data records.  A bare u32 that is not a
    plausible size is a "size request" (a procedural texture asking for the size
    of its stream) and is skipped; otherwise a size that runs off the end stops
    the walk (map packs with irregular files need gcrip.formats.jade_obj)."""
    out = []
    pos = 0
    n = len(dec)
    while pos + 4 <= n:
        size = struct.unpack_from("<I", dec, pos)[0]
        if pos + 4 + size > n:
            if pos + 8 <= n and pos + 8 + struct.unpack_from("<I", dec, pos + 4)[0] <= n:
                pos += 4  # size request
                continue
            if stop_on_bad:
                break
            size = n - pos - 4
        out.append(BinEntry(len(out), None, pos + 4, dec[pos + 4 : pos + 4 + size]))
        pos += 4 + size
    return out


# ---------------------------------------------------------------------------
# textures
# ---------------------------------------------------------------------------


@dataclass
class TexHeader:
    flags: int
    type: int
    fmt: int
    width: int
    height: int
    body: bytes  # everything after the 32-byte header
    key: int | None = None  # Montreal: key stored in front of the header

    @property
    def bpp(self) -> int:
        return {0x50: 4, 0x40: 8, 0x31: 16, 0x20: 24, 0x10: 32}.get(self.fmt, 0)


def parse_tex_header(data: bytes, *, montreal: bool) -> TexHeader | None:
    off = 4 if montreal else 0
    if len(data) < off + TEX_HEADER_SIZE:
        return None
    if data[off : off + 4] != b"\xff\xff\xff\xff":
        return None
    if data[off + 0x14 : off + 0x20] != b"\x34\x12\xd0\xca\xff\x00\xff\x00\xde\xc0\xde\xc0":
        return None
    flags, typ, fmt, w, h = struct.unpack_from("<HBBHH", data, off + 4)
    if typ == 0 or typ > 13:
        return None
    key = struct.unpack_from("<I", data, 0)[0] if montreal else None
    return TexHeader(flags, typ, fmt, w, h, data[off + TEX_HEADER_SIZE :], key)


def palette_from_bytes(raw: bytes) -> np.ndarray | None:
    """TEX_Palette payload -> (N,4) u8 RGBA. Sizes 0x30/0x300 are BGR, 0x40/0x400 BGRA."""
    n = len(raw)
    if n in (0x30, 0x300):
        a = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        return np.concatenate([a[:, ::-1], np.full((len(a), 1), 255, np.uint8)], axis=1)
    if n in (0x40, 0x400):
        a = np.frombuffer(raw, np.uint8).reshape(-1, 4)
        alpha = a[:, 3:4].astype(np.uint16)
        alpha = np.minimum(alpha * 2, 255).astype(np.uint8)  # Jade uses 0..128 alpha
        return np.concatenate([a[:, 2::-1], alpha], axis=1)
    return None


def decode_raw_indexed(t: TexHeader, palette: np.ndarray) -> np.ndarray | None:
    w, h = t.width, t.height
    if t.bpp == 8:
        need = w * h
        if len(t.body) < need:
            return None
        idx = np.frombuffer(t.body[:need], np.uint8).reshape(h, w)
    elif t.bpp == 4:
        need = (w * h + 1) // 2
        if len(t.body) < need:
            return None
        b = np.frombuffer(t.body[:need], np.uint8)
        idx = np.stack([b >> 4, b & 15], axis=1).reshape(-1)[: w * h].reshape(h, w)
    else:
        return None
    return palette[idx.astype(np.int32) % len(palette)]


def decode_tga(t: TexHeader) -> np.ndarray | None:
    body = t.body
    if len(body) < 18:
        return None
    w, h, bpp, desc = struct.unpack_from("<HHBB", body, 12)
    if w == 0 or h == 0:
        w, h = t.width, t.height
    ch = bpp // 8
    if ch not in (3, 4):
        return None
    need = w * h * ch
    px = body[18 : 18 + need]
    if len(px) < need:
        return None
    a = np.frombuffer(px, np.uint8).reshape(h, w, ch)
    rgb = a[:, :, 2::-1]
    if ch == 4:
        img = np.concatenate([rgb, a[:, :, 3:4]], axis=2)
    else:
        img = np.concatenate([rgb, np.full((h, w, 1), 255, np.uint8)], axis=2)
    if not desc & 0x20:  # origin bottom-left
        img = img[::-1]
    return np.ascontiguousarray(img)


JTX_RAW32 = 0
JTX_PAL8 = 1
JTX_PAL4 = 2
JTX_A8 = 3
JTX_I8 = 4
JTX_S3TC = 5
JTX_A4 = 8
JTX_I4 = 9
JTX_AI8 = 10
JTX_AI4 = 11
JTX_S3TC_A = 12
JTX_BPP = {0: 32, 1: 8, 2: 4, 3: 8, 4: 8, 5: 4, 6: 8, 7: 8, 8: 4, 9: 4, 10: 8, 11: 4, 12: 4}


def decode_dxt1(blocks: bytes, width: int, height: int) -> np.ndarray:
    """Plain little-endian DXT1 (S3TC) blocks, row-major - what PoP SoT keeps in
    its JTX textures on GameCube (converted to CMPR by the engine at load)."""
    bw, bh = max(1, width // 4), max(1, height // 4)
    n = bw * bh
    a = np.frombuffer(blocks[: n * 8], "<u2").reshape(n, 4)
    c0 = a[:, 0].astype(np.int32)
    c1 = a[:, 1].astype(np.int32)
    idx = a[:, 2].astype(np.uint32) | (a[:, 3].astype(np.uint32) << 16)

    def rgb(c: np.ndarray) -> np.ndarray:
        r = ((c >> 11) & 31) * 255 // 31
        g = ((c >> 5) & 63) * 255 // 63
        b = (c & 31) * 255 // 31
        return np.stack([r, g, b], axis=-1)

    p0, p1 = rgb(c0), rgb(c1)
    opaque = (c0 > c1)[:, None]
    p2 = np.where(opaque, (2 * p0 + p1) // 3, (p0 + p1) // 2)
    p3 = np.where(opaque, (p0 + 2 * p1) // 3, 0)
    pal = np.stack([p0, p1, p2, p3], axis=1)  # (n,4,3)
    alpha = np.stack(
        [np.full(n, 255), np.full(n, 255), np.full(n, 255), np.where(opaque[:, 0], 255, 0)], axis=1
    )
    shifts = np.arange(16, dtype=np.uint32) * 2
    sel = ((idx[:, None] >> shifts[None, :]) & 3).astype(np.int64)  # (n,16)
    rows = np.arange(n)[:, None]
    px = pal[rows, sel]  # (n,16,3)
    pa = alpha[rows, sel]  # (n,16)
    img = np.concatenate([px, pa[:, :, None]], axis=2).astype(np.uint8).reshape(bh, bw, 4, 4, 4)
    return img.transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)[:height, :width]


def decode_jtx(t: TexHeader, palettes: dict[int, np.ndarray] | None = None) -> np.ndarray | None:
    """JTX content (Montreal builds): u32 version, u32 format, u32 w, u32 h,
    i32 mips, [f32 bias if version >= 3], [u32 palette key for paletted], then
    the base level and its mips; S3TC_A repeats the whole thing for alpha."""
    body = t.body
    if len(body) < 24:
        return None
    version, fmt, w, h, _mips = struct.unpack_from("<IIIIi", body, 0)
    if version == 0 or w == 0 or h == 0 or w > 4096 or h > 4096 or fmt not in JTX_BPP:
        return None
    pos = 20
    if version >= 3:
        pos += 4
    pal = None
    if fmt in (JTX_PAL4, JTX_PAL8):
        if pos + 4 > len(body):
            return None
        pal_key = struct.unpack_from("<I", body, pos)[0]
        pos += 4
        pal = (palettes or {}).get(pal_key)
    if fmt in (JTX_S3TC, JTX_S3TC_A):
        base = max(1, w // 4) * max(1, h // 4) * 8
        if len(body) < pos + base:
            return None
        img = decode_dxt1(body[pos : pos + base], w, h)
        if fmt == JTX_S3TC_A:
            # the alpha plane follows the colour plane and its mips
            mip = 0
            cw, ch = w, h
            for _ in range(max(0, _mips)):
                if cw > 8:
                    cw >>= 1
                if ch > 8:
                    ch >>= 1
                mip += (cw // 8) * ch * 4
            p2 = pos + base + mip
            if len(body) >= p2 + base:
                a = decode_dxt1(body[p2 : p2 + base], w, h)
                img = img.copy()
                img[:, :, 3] = a[:, :, 0]
        return img
    need = w * h * JTX_BPP[fmt] // 8
    if len(body) < pos + need:
        return None
    raw = np.frombuffer(body[pos : pos + need], np.uint8)
    if fmt == JTX_RAW32:
        a = raw.reshape(h, w, 4)
        return np.concatenate([a[:, :, 2::-1], a[:, :, 3:4]], axis=2)
    if fmt in (JTX_PAL4, JTX_PAL8):
        if pal is None:
            return None
        fake = TexHeader(0, TEX_RAW, 0x50 if fmt == JTX_PAL4 else 0x40, w, h, body[pos:])
        return decode_raw_indexed(fake, pal)
    out = np.empty((h, w, 4), np.uint8)
    if fmt in (JTX_A8, JTX_I8):
        v = raw.reshape(h, w)
        out[:, :, :3] = 255 if fmt == JTX_A8 else v[:, :, None]
        out[:, :, 3] = v if fmt == JTX_A8 else 255
    elif fmt in (JTX_A4, JTX_I4):
        v = np.stack([raw >> 4, raw & 15], axis=1).reshape(-1)[: w * h].reshape(h, w) * 17
        out[:, :, :3] = 255 if fmt == JTX_A4 else v[:, :, None]
        out[:, :, 3] = v if fmt == JTX_A4 else 255
    elif fmt == JTX_AI8:
        v = raw.reshape(h, w)
        out[:, :, :3] = ((v & 15) * 17)[:, :, None]
        out[:, :, 3] = (v >> 4) * 17
    elif fmt == JTX_AI4:
        v = np.stack([raw >> 4, raw & 15], axis=1).reshape(-1)[: w * h].reshape(h, w)
        out[:, :, :3] = ((v & 3) * 85)[:, :, None]
        out[:, :, 3] = (v >> 2) * 85
    else:
        return None
    return out


def textures_montreal(entries: list[BinEntry]) -> dict[str, np.ndarray]:
    """Keyed pack: JTX contents are self-contained, raw+palette pairs go via keys."""
    out: dict[str, np.ndarray] = {}
    palettes: dict[int, np.ndarray] = {}
    raws: dict[int, TexHeader] = {}
    rawpal: list[tuple[int, int, int]] = []
    for e in entries:
        n = len(e.data) - 4
        if e.data[4:8] == b"\xff\xff\xff\xff" or n < 0x30:
            continue
        if n in (0x30, 0x300, 0x40, 0x400):
            pal = palette_from_bytes(e.data[4:])
        elif n > 0x400 and n % 4 == 0:
            pal = palette_from_bytes(e.data[4 : 4 + 0x400])  # JTX palette: 256 BGRA + mips
        else:
            continue
        if pal is not None:
            palettes[e.key] = pal
    for e in entries:
        t = parse_tex_header(e.data, montreal=True)
        if t is None:
            continue
        if t.type == TEX_JTX and len(t.body) > 24:
            img = decode_jtx(t, palettes)
            if img is not None:
                out[f"{t.key:08x}"] = img
        elif t.type == TEX_TGA and len(t.body) > 18:
            img = decode_tga(t)
            if img is not None:
                out[f"{t.key:08x}"] = img
        elif t.type == TEX_RAW and len(t.body) >= t.width * t.height * t.bpp // 8 > 0:
            raws[t.key] = t
        elif t.type == TEX_RAWPAL and len(t.body) >= 8:
            raw_key, pal_key = struct.unpack_from("<II", t.body, 0)
            rawpal.append((t.key, raw_key, pal_key))
    for key, raw_key, pal_key in rawpal:
        t = raws.get(raw_key)
        pal = palettes.get(pal_key)
        if t is not None and pal is not None:
            img = decode_raw_indexed(t, pal)
            if img is not None:
                out[f"{key:08x}"] = img
    return out


def rawpal_slot(body: bytes) -> tuple[int, int, int]:
    """TEX_Content_RawPal: up to four 12-byte slots (raw 4/8-bit key, palette key,
    24/32-bit key); GameCube prefers the second slot when it is filled."""
    slots = [struct.unpack_from("<III", body, i) for i in range(0, len(body) - 11, 12)]
    if not slots:
        return 0, 0, 0
    if len(slots) > 1 and any(k not in (0, 0xFFFFFFFF) for k in slots[1]):
        return slots[1]
    return slots[0]


def align_texture_keys(headers: list[int | None], order: list[int]) -> list[int | None]:
    """Key for each primary texture header of a Montpellier texture pack.

    `headers` holds the raw key of each RawPal header (None for other types) in
    pack order, `order` the texture keys in the order the map referenced them.
    The two sequences line up except where a reference we did not walk (a
    modifier's texture) inserts a header; the editor allocated a RawPal texture
    right after its raw image, so `raw + 1 == key` anchors the shift."""
    n = len(order)
    out: list[int | None] = [None] * len(headers)

    def anchor(i: int, d: int) -> bool:
        raw = headers[i]
        j = i + d
        return raw is not None and 0 <= j < n and order[j] == raw + 1

    delta = 0
    for i, raw in enumerate(headers):
        if raw is not None and not anchor(i, delta):
            later = (k for k in range(i + 1, min(i + 8, len(headers))) if headers[k] is not None)
            nxt = next(later, None)
            for d in (delta - 1, delta + 1, delta - 2, delta + 2, delta - 3, delta + 3):
                if anchor(i, d) and (nxt is None or anchor(nxt, d)):
                    delta = d
                    break
        j = i + delta
        if 0 <= j < n:
            out[i] = order[j]
    return out


def textures_montpellier(
    entries: list[BinEntry], tex_order: list[int] | None = None
) -> dict[str, np.ndarray]:
    """Unkeyed texture pack (BG&E ff8xxxxx.bin).  The loader's order is: every
    referenced texture's header (RawPal ones carry their raw/palette keys), then
    the raw textures' headers in first-reference order, then the palettes in
    first-reference order, then the contents in the same orders.  Images are
    named by texture key when `tex_order` (the map's reference order, see
    jade_obj.World.tex_order) is given, else by raw key / position."""
    heads: list[tuple[TexHeader, int]] = []  # header phase: (header, entry index)
    palettes: list[np.ndarray] = []
    contents: list[TexHeader | np.ndarray] = []
    phase = 0
    for e in entries:
        t = parse_tex_header(e.data, montreal=False)
        if t is None:
            if len(e.data) in (0x30, 0x300, 0x40, 0x400):
                pal = palette_from_bytes(e.data)
                if pal is not None:
                    palettes.append(pal)
                    phase = max(phase, 1)
            continue
        is_content = t.type in (TEX_TGA, TEX_JTX) and len(t.body) > 18 or (
            t.type == TEX_RAW and len(t.body) >= max(1, t.width * t.height * t.bpp // 8)
        )
        if is_content:
            phase = 2
            if t.type == TEX_TGA:
                img = decode_tga(t)
            elif t.type == TEX_JTX:
                img = decode_jtx(t)
            else:
                img = None
            contents.append(img if img is not None else t)
        elif phase == 0:
            heads.append((t, e.index))
    # the raw textures' own headers (appended to the list as the RawPal headers
    # are read, so they may interleave with late references) carry no content
    primaries = [t for t, _ in heads if not (t.type == TEX_RAW and len(t.body) == 0)]
    raw_keys: list[int] = []
    pal_keys: list[int] = []
    slots: list[tuple[int, int, int] | None] = []
    for t in primaries:
        if t.type == TEX_RAWPAL and len(t.body) >= 8:
            raw_key, pal_key, _ = rawpal_slot(t.body)
            slots.append((raw_key, pal_key, 0))
            if raw_key not in (0, 0xFFFFFFFF) and raw_key not in raw_keys:
                raw_keys.append(raw_key)
            if pal_key not in (0, 0xFFFFFFFF) and pal_key not in pal_keys:
                pal_keys.append(pal_key)
        else:
            slots.append(None)
    keys: list[int | None] = [None] * len(primaries)
    if tex_order:
        keys = align_texture_keys([s[0] if s else None for s in slots], tex_order)
    # contents in list order: primaries with content, then the raw textures
    raw_by_key: dict[int, TexHeader] = {}
    ci = 0
    primary_imgs: dict[int, np.ndarray] = {}
    for i, t in enumerate(primaries):
        if t.type in (TEX_TGA, TEX_JTX, TEX_RAW) and ci < len(contents):  # noqa: SIM102
            c = contents[ci]
            ci += 1
            if isinstance(c, np.ndarray):
                primary_imgs[i] = c
    for k in raw_keys:
        if ci < len(contents):
            c = contents[ci]
            ci += 1
            if isinstance(c, TexHeader):
                raw_by_key[k] = c
    pal_by_key = {k: palettes[i] for i, k in enumerate(pal_keys) if i < len(palettes)}
    out: dict[str, np.ndarray] = {}
    for i in range(len(primaries)):
        key = keys[i]
        if i in primary_imgs:
            out[f"{key:08x}" if key is not None else f"tex{i:03d}"] = primary_imgs[i]
        elif slots[i] is not None:
            raw_key, pal_key, _ = slots[i]
            raw = raw_by_key.get(raw_key)
            pal = pal_by_key.get(pal_key)
            if raw is None or pal is None:
                continue
            img = decode_raw_indexed(raw, pal)
            if img is not None:
                out[f"{key:08x}" if key is not None else f"{raw_key:08x}"] = img
    return out


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


class _R:
    __slots__ = ("d", "p", "n")

    def __init__(self, d: bytes, p: int = 0):
        self.d = d
        self.p = p
        self.n = len(d)

    def u32(self) -> int:
        if self.p + 4 > self.n:
            raise JadeError("truncated")
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self) -> int:
        v = self.u32()
        return v - (1 << 32) if v & 0x80000000 else v

    def u16(self) -> int:
        if self.p + 2 > self.n:
            raise JadeError("truncated")
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def u8(self) -> int:
        if self.p + 1 > self.n:
            raise JadeError("truncated")
        v = self.d[self.p]
        self.p += 1
        return v

    def skip(self, n: int) -> None:
        if n < 0 or self.p + n > self.n:
            raise JadeError("truncated")
        self.p += n

    def array(self, dtype, count: int) -> np.ndarray:
        dt = np.dtype(dtype)
        size = dt.itemsize * count
        if count < 0 or self.p + size > self.n:
            raise JadeError("truncated")
        a = np.frombuffer(self.d, dt, count, self.p)
        self.p += size
        return a


@dataclass
class GeoElement:
    material: int
    triangles: np.ndarray  # (T, 6) u16: v0 v1 v2 uv0 uv1 uv2
    strips: list[np.ndarray] = field(default_factory=list)  # GC: (n, 4) [v, n, c, uv]


@dataclass
class Geo:
    vertices: np.ndarray  # (V,3) f32
    normals: np.ndarray | None
    colors: np.ndarray | None  # (C,4) u8
    uvs: np.ndarray  # (U,2) f32
    elements: list[GeoElement]
    bones: list[tuple[int, np.ndarray, np.ndarray]] = field(default_factory=list)
    # (matrix index, (16,) f32 bind matrix, (N,2) [vertex index, weight])
    warnings: list[str] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        n = 0
        for e in self.elements:
            if e.strips:
                n += sum(max(0, len(s) - 2) for s in e.strips)
            else:
                n += len(e.triangles)
        return n


MAX_COUNT = 200_000


def _sane(*counts: int) -> None:
    for c in counts:
        if c > MAX_COUNT:
            raise JadeError("implausible count")


def _ponderation(r: _R) -> list[tuple[int, np.ndarray, np.ndarray]]:
    _flags = r.u16()
    count = r.u16()
    _sane(count)
    out = []
    for _ in range(count):
        idx = r.u16()
        n = r.u16()
        mat = r.array("<f4", 16)
        _type = r.u32()
        pond = r.array("<u4", n)
        v = (pond & 0xFFFF).astype(np.int64)
        w = np.frombuffer((pond & 0xFFFF0000).astype("<u4").tobytes(), "<f4")
        out.append((idx, mat.astype(np.float32), np.stack([v, w], axis=1)))
    return out


def _ok3(r: _R) -> None:
    boxes = r.u32()
    _sane(boxes)
    for _ in range(boxes):
        n = r.u32()
        _sane(n)
        r.skip(24)
        for _ in range(n):
            _el = r.u16()
            t = r.u16()
            r.skip(2 * t)


def parse_geo(data: bytes, *, montreal: bool) -> Geo:
    """Parse a GRO_Struct of type GEO. Raises JadeError unless the whole buffer is
    consumed exactly, which is what makes signature scanning safe."""
    r = _R(data)
    if r.u32() != GRO_GEO:
        raise JadeError("not a GEO")
    warnings: list[str] = []
    ov = r.u32() if montreal else 0
    version = 0
    has_mrm = 0
    has_reorder = 0
    flags_sot = 0
    flags2 = 0
    if montreal:
        if ov >= 4:
            flags_sot = r.u32()
        if ov >= 7:
            flags2 = r.u32()
        nverts = r.u32()
    else:
        code = r.u32()
        if code == CODE_2002:
            version = r.u32()
            nverts = r.u32()
            has_mrm = r.i32()
            if has_mrm:
                has_reorder = r.i32()
        else:
            nverts = code
    ncolors = r.u32()
    has_colors = r.i32() if (montreal and ov >= 3) else 1
    nuvs = r.u32()
    nelems = r.u32()
    _sane(nverts, ncolors, nuvs, nelems)
    mrm_ptr = r.u32() if ov < 2 else 0
    code1 = r.u32()
    bones: list = []
    if (code1 & CODE_2002) == CODE_2002:
        bones = _ponderation(r)
    has_normals = 0
    if montreal:
        if ov != 0:
            has_normals = r.i32()
    elif code1 & 1:
        _ok3(r)
    vertices = r.array("<f4", nverts * 3).reshape(-1, 3)
    normals = None
    if montreal and has_normals and ov >= 3:
        normals = r.array("<f4", nverts * 3).reshape(-1, 3)
    if mrm_ptr:
        r.skip(2 * nverts)
        if mrm_ptr == CODE_0008:
            r.skip(2 * nverts)
        r.u32()
        if version == 0:
            r.skip(32)
    colors = None
    if not montreal or has_colors:
        c = r.array("u1", ncolors * 4).reshape(-1, 4)
        colors = c
    uvs = r.array("<f4", nuvs * 2).reshape(-1, 2)
    heads = []
    for _ in range(nelems):
        ntris = r.u32()
        mat = r.u32()
        el_mrm = 0
        used = 0
        if ov < 2:
            el_mrm = r.u32()
            used = r.u32()
        _sane(ntris, used)
        heads.append((ntris, mat, el_mrm, used))
    elements: list[GeoElement] = []
    tri_stride = 20 if not montreal else 16
    for ntris, mat, el_mrm, used in heads:
        raw = r.array("u1", ntris * tri_stride).reshape(-1, tri_stride)
        tris = raw[:, :12].copy().view("<u2").reshape(-1, 6)
        if not montreal:
            if el_mrm:
                r.skip(12)
            r.skip(2 * used)
        elements.append(GeoElement(mat, tris.astype(np.uint16)))
    strip_flag = r.u32()
    if strip_flag & 1:
        for _ in elements:
            _sflags = r.u32()
            nstrips = r.u32()
            _sane(nstrips)
            for _ in range(nstrips):
                cnt = r.u32() & 0x7FFFFFFF
                _sane(cnt)
                r.skip(4 * cnt)
    if has_mrm:
        if version >= 4:
            r.u32()
        levels = r.u32()
        _sane(levels)
        r.skip(4 * levels)
        r.skip(4 * max(0, levels - 1))
        if has_reorder:
            r.skip(2 * nverts)
        if version >= 3:
            r.u32()
            r.skip(4 * levels)
            r.u32()
            r.skip(4 * levels)
    sprites = r.u32()
    if sprites and (sprites >> 8) == 0:
        raise JadeError("sprite elements unsupported")
    if version >= 2:
        r.u32()
    if montreal and (flags2 & 2):
        _parse_gc(r, elements, flags_sot, warnings)
    if r.p != r.n:
        raise JadeError(f"GEO size mismatch: read {r.p} of {r.n}")
    return Geo(vertices, normals, colors, uvs, elements, bones, warnings)


def _parse_gc(r: _R, elements: list[GeoElement], flags_sot: int, warnings: list[str]) -> None:
    """GEO_GeoObject_GC (+ embedded GEO_GeoObject_GC_Content): the display lists."""
    n = r.u32()
    _sane(n)
    mats = [r.u32() for _ in range(n)]
    if r.p >= r.n:
        return
    # embedded content, may carry its own size / bin-file header in some builds
    save = r.p
    if r.u32() != DEADBABE:
        r.p = save
        if r.u32() == DEADBABE:
            pass
        else:
            r.p = save
            r.u32()  # size
            if r.u32() != DEADBABE:
                raise JadeError("GC content marker not found")
    flags = r.u32()
    use_normals = bool(flags & 1)
    index8 = bool(flags & (1 << 20))
    lightmap = bool(flags & (1 << 21))
    if not elements and n:
        elements.extend(GeoElement(m, np.zeros((0, 6), np.uint16)) for m in mats)
    for i in range(n):
        nstrips = r.u16()
        _pad = r.u16()
        _sane(nstrips)
        strips = []
        for _ in range(nstrips):
            ln = r.u16()
            _sane(ln)
            fields = 3 + (1 if use_normals else 0)
            if index8:
                raw = r.array("u1", ln * fields).reshape(ln, fields).astype(np.int64)
            else:
                raw = r.array("<u2", ln * fields).reshape(ln, fields).astype(np.int64)
            if lightmap:
                r.skip(4 * ln)
            pts = np.zeros((ln, 4), np.int64)
            pts[:, 0] = raw[:, 0]
            k = 1
            if use_normals:
                pts[:, 1] = raw[:, 1]
                k = 2
            pts[:, 2] = raw[:, k]
            pts[:, 3] = raw[:, k + 1]
            strips.append(pts)
        if i < len(elements):
            elements[i].strips = strips
            if i < len(mats):
                elements[i].material = mats[i]


_GEO_SIG = re.compile(rb"\x01\x00\x00\x00")


def find_geos_montpellier(dec: bytes) -> list[tuple[int, Geo]]:
    """Signature scan: a GEO starts with type=1 preceded by its u32 size; only a
    parse that consumes exactly that size is accepted."""
    out = []
    n = len(dec)
    for m in _GEO_SIG.finditer(dec):
        p = m.start()
        if p < 4:
            continue
        size = struct.unpack_from("<I", dec, p - 4)[0]
        if size < 24 or p + size > n:
            continue
        try:
            g = parse_geo(dec[p : p + size], montreal=False)
        except (JadeError, ValueError):
            continue
        if len(g.vertices) == 0:
            continue
        out.append((p, g))
    return out
