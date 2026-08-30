"""EA "shape" texture files: FSH (SHPI, PC), SSH (SHPS, PS2), XSH (SHPX, Xbox),
GSH (SHPG, GameCube), PSH (SHPP, PSP).

Header: magic, u32 file size, u32 entry count, char[4] directory id; then entries of
char[4] name + u32 offset. An entry is a chain of blocks: u8 code, u24 next block size
(0 = last), u16 width, u16 height, u16 centre x, u16 centre y, u16 x pos, u16 y pos (top
nibble = mip levels). Bit 0x80 of the code marks a RefPack-compressed body. Image codes:
  0x7B 8-bit paletted   0x7D 32-bit BGRA   0x7F 24-bit BGR   0x7E ARGB1555
  0x78 RGB565           0x6D ARGB4444      0x60 DXT1          0x61 DXT3
  0x01 4-bit paletted   0x02 8-bit paletted (PS2 numbering)   0x05 32-bit RGBA (PS2)
Palette codes: 0x2A 32-bit BGRA, 0x21 32-bit RGBA (PS2 alpha 0..0x80), 0x24/0x22 24-bit BGR,
0x29 RGB565, 0x2D ARGB1555. Metadata blocks (0x69, 0x6F, 0x70, 0x7C) are skipped.
GameCube shapes (SHPG) store paletted/32-bit/compressed images as GX tiles; those are
decoded through gx_texture with the palette as RGB5A3 - marked as a guess in warnings
since no disc in the library ships them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture, refpack


@dataclass
class ShapeImage:
    name: str
    width: int
    height: int
    code: int
    rgba: np.ndarray | None
    warnings: list[str] = field(default_factory=list)


def is_shape(head: bytes) -> bool:
    """``SHPI`` / ``SHPS`` / ``SHPX`` / ``SHPG`` / ``SHPP`` / ``SHPM``; the NHL and NBA Live
    discs write the tag in mixed case (``ShpG``)."""
    return len(head) >= 16 and head[:3].upper() == b"SHP" and head[3:4].upper() in b"ISXGPM"


def shape_names(data: bytes) -> list[str]:
    """Entry names of a shape file from its header only (no image decoding)."""
    if len(data) < 16 or data[:3].upper() != b"SHP":
        return []
    if _is_nhl_variant(data):
        return [data[0x18:0x28].split(b"\x00")[0].decode("latin-1", "replace") or "image"]
    e = _endian(data)
    count = struct.unpack_from(e + "I", data, 8)[0]
    if count > 0x4000 or 16 + count * 8 > len(data):
        return []
    return [data[16 + i * 8 : 20 + i * 8].decode("latin-1").rstrip("\0 ") for i in range(count)]


def _endian(data: bytes) -> str:
    count_le = struct.unpack_from("<I", data, 8)[0]
    count_be = struct.unpack_from(">I", data, 8)[0]
    if 0 < count_le <= 0x4000 and 16 + count_le * 8 <= len(data):
        return "<"
    if 0 < count_be <= 0x4000 and 16 + count_be * 8 <= len(data):
        return ">"
    return "<"


def _dxt_colors(c0: np.ndarray, c1: np.ndarray, has_alpha_mode: bool) -> np.ndarray:
    """(N,4,4) RGBA lookup tables for N DXT blocks."""
    n = len(c0)

    def unpack(v):
        r = ((v >> 11) & 0x1F) * 255 // 31
        g = ((v >> 5) & 0x3F) * 255 // 63
        b = (v & 0x1F) * 255 // 31
        return np.stack([r, g, b], -1).astype(np.int32)

    p0, p1 = unpack(c0.astype(np.int32)), unpack(c1.astype(np.int32))
    lut = np.zeros((n, 4, 4), np.int32)
    lut[:, 0, :3], lut[:, 1, :3] = p0, p1
    lut[:, :, 3] = 255
    four = (c0 > c1) | ~has_alpha_mode
    lut[:, 2, :3] = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    lut[:, 3, :3] = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    lut[:, 3, 3] = np.where(four, 255, 0)
    return lut.astype(np.uint8)


def decode_dxt(data: bytes, width: int, height: int, dxt3: bool = False) -> np.ndarray:
    bw, bh = (width + 3) // 4, (height + 3) // 4
    bs = 16 if dxt3 else 8
    need = bw * bh * bs
    buf = np.frombuffer(bytes(data[:need]) + b"\0" * max(0, need - len(data)), np.uint8)
    blocks = buf.reshape(bw * bh, bs)
    color = blocks[:, 8:] if dxt3 else blocks
    c0 = color[:, 0].astype(np.uint16) | (color[:, 1].astype(np.uint16) << 8)
    c1 = color[:, 2].astype(np.uint16) | (color[:, 3].astype(np.uint16) << 8)
    lut = _dxt_colors(c0, c1, np.full(len(c0), not dxt3))
    idx = color[:, 4:8]  # 4 rows, 2 bits per pixel, LSB first
    sel = np.stack([(idx >> (2 * i)) & 3 for i in range(4)], -1)  # (N,4rows,4cols)
    px = lut[np.arange(len(lut))[:, None, None], sel]  # (N,4,4,4)
    if dxt3:
        a = blocks[:, :8]
        av = a[:, 0::2].astype(np.uint16) | (a[:, 1::2].astype(np.uint16) << 8)  # (N,4 rows)
        alpha = np.stack([((av >> (4 * i)) & 0xF) * 17 for i in range(4)], -1)  # (N,4,4)
        px[..., 3] = alpha.astype(np.uint8)
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.ascontiguousarray(img[:height, :width])


def _palette(code: int, body: bytes, count: int) -> np.ndarray | None:
    code &= 0x7F
    if code in (0x2A, 0x21):
        v = np.frombuffer(body[: count * 4], np.uint8).reshape(-1, 4).astype(np.int32)
        if code == 0x21:  # PS2: RGBA, alpha 0..0x80
            a = np.minimum(v[:, 3] * 2, 255)
            return np.stack([v[:, 0], v[:, 1], v[:, 2], a], -1).astype(np.uint8)
        return np.stack([v[:, 2], v[:, 1], v[:, 0], v[:, 3]], -1).astype(np.uint8)
    if code in (0x24, 0x22):
        v = np.frombuffer(body[: count * 3], np.uint8).reshape(-1, 3).astype(np.int32)
        if code == 0x22:
            v = v * 4
        return np.stack([v[:, 2], v[:, 1], v[:, 0], np.full(len(v), 255)], -1).astype(np.uint8)
    if code == 0x29:
        v = np.frombuffer(body[: count * 2], "<u2").astype(np.uint16)
        return _rgb565(v)
    if code == 0x2D:
        v = np.frombuffer(body[: count * 2], "<u2").astype(np.uint16)
        return _argb1555(v)
    return None


def _rgb565(v: np.ndarray) -> np.ndarray:
    r = ((v >> 11) & 0x1F) * 255 // 31
    g = ((v >> 5) & 0x3F) * 255 // 63
    b = (v & 0x1F) * 255 // 31
    return np.stack([r, g, b, np.full(v.shape, 255)], -1).astype(np.uint8)


def _argb1555(v: np.ndarray) -> np.ndarray:
    a = ((v >> 15) & 1) * 255
    r = ((v >> 10) & 0x1F) * 255 // 31
    g = ((v >> 5) & 0x1F) * 255 // 31
    b = (v & 0x1F) * 255 // 31
    return np.stack([r, g, b, a], -1).astype(np.uint8)


def _argb4444(v: np.ndarray) -> np.ndarray:
    a = ((v >> 12) & 0xF) * 17
    r = ((v >> 8) & 0xF) * 17
    g = ((v >> 4) & 0xF) * 17
    b = (v & 0xF) * 17
    return np.stack([r, g, b, a], -1).astype(np.uint8)


def _pad(body: bytes, need: int) -> bytes:
    return body if len(body) >= need else bytes(body) + b"\0" * (need - len(body))


_GC_MIP_CODES = {0x16: 6, 0x1E: 14, 0x19: 1}


def _decode_image(code: int, w: int, h: int, body: bytes, palette, gc: bool, warn: list[str]):
    n = w * h
    if code == 0x7D:
        v = np.frombuffer(_pad(body, n * 4), np.uint8, n * 4).reshape(h, w, 4)
        return np.ascontiguousarray(v[..., [2, 1, 0, 3]])
    if code == 0x7F:
        v = np.frombuffer(_pad(body, n * 3), np.uint8, n * 3).reshape(h, w, 3)
        return np.concatenate([v[..., ::-1], np.full((h, w, 1), 255, np.uint8)], -1)
    if code in (0x7E, 0x78, 0x6D):
        v = np.frombuffer(_pad(body, n * 2), "<u2", n).astype(np.uint16)
        conv = {0x7E: _argb1555, 0x78: _rgb565, 0x6D: _argb4444}[code]
        return conv(v).reshape(h, w, 4)
    if code == 0x60:
        return decode_dxt(body, w, h)
    if code == 0x61:
        return decode_dxt(body, w, h, dxt3=True)
    if code == 0x05:
        if gc:
            warn.append("GameCube 32-bit shape decoded as GX RGBA8 tiles (guess)")
            return gx_texture.decode(6, w, h, body)
        v = np.frombuffer(_pad(body, n * 4), np.uint8, n * 4).reshape(h, w, 4).astype(np.int32)
        v[..., 3] = np.minimum(v[..., 3] * 2, 255)
        return v.astype(np.uint8)
    if code in (0x7B, 0x02, 0x01):
        bits4 = code == 0x01
        if palette is None:
            warn.append("paletted image without a palette block")
            palette = np.stack([np.arange(256)] * 3 + [np.full(256, 255)], -1).astype(np.uint8)
        if gc:
            warn.append("GameCube paletted shape decoded as GX tiles (guess)")
            return gx_texture.decode(8 if bits4 else 9, w, h, body, palette)
        if bits4:
            b = np.frombuffer(_pad(body, (n + 1) // 2), np.uint8, (n + 1) // 2)
            idx = np.stack([b & 0xF, b >> 4], -1).reshape(-1)[:n]
        else:
            idx = np.frombuffer(_pad(body, n), np.uint8, n)
        return palette[np.minimum(idx, len(palette) - 1)].reshape(h, w, 4)
    if gc and code in (0x5B, 0x5C):
        warn.append(f"GameCube shape code {code:#x} decoded as GX CMPR (guess)")
        return gx_texture.decode(14, w, h, body)
    if gc and code in _GC_MIP_CODES:
        # EA Canada SHPG (FIFA 2004 ...): native GX tiles with the whole mip chain in the
        # body; sizes identify the format (0x16: 32 bpp RGBA8, 0x1e: 4 bpp CMPR, 0x19: 8 bpp,
        # which decodes as I8 - FIFA's button icons look right that way)
        fmt = _GC_MIP_CODES[code]
        if fmt == 1:
            warn.append("GameCube shape code 0x19 decoded as GX I8 (guess between I8/IA4)")
        return gx_texture.decode(fmt, w, h, body)
    warn.append(f"unsupported shape image code {code:#x}")
    return None


def _is_nhl_variant(data: bytes) -> bool:
    """NHL / NBA Live GameCube shapes: one image described by the header itself
    (``u32 data offset | u32 data size`` at 0x10) instead of a name / offset table."""
    if len(data) < 0x60 or data[:3].upper() != b"SHP":
        return False
    off, size = struct.unpack_from(">2I", data, 0x10)
    return off == 0x40 and size > 0x30 and off + size == len(data)


def _nhl_image(data: bytes) -> ShapeImage:
    """``u8 code | ... | u32 width (+0x18) | u32 height (+0x1c) | ... | pixels (+0x30)``;
    the GX format follows from the bytes per pixel (0.5 CMPR, 1 I8, 2 RGB5A3, 4 RGBA8)."""
    off = struct.unpack_from(">I", data, 0x10)[0]
    name = data[0x18:0x28].split(b"\x00")[0].decode("latin-1", "replace") or "image"
    w, h = struct.unpack_from(">2I", data, off + 0x18)
    img = ShapeImage(name, w, h, data[off], None)
    body = data[off + 0x30 :]
    if not (0 < w <= 4096 and 0 < h <= 4096) or not body:
        img.warnings.append("implausible image size")
        return img
    per = len(body) / (w * h)
    fmt = 14 if per < 1 else (1 if per < 2 else (5 if per < 4 else 6))
    try:
        img.rgba = gx_texture.decode(fmt, w, h, body)
    except ValueError as ex:
        img.warnings.append(f"{name}: {ex}")
    return img


def parse(data: bytes) -> list[ShapeImage]:
    if not is_shape(data):
        raise ValueError("not an EA shape file")
    if _is_nhl_variant(data):
        return [_nhl_image(data)]
    e = _endian(data)
    gc = data[3:4].upper() == b"G"
    count = struct.unpack_from(e + "I", data, 8)[0]
    out = []
    for i in range(count):
        name = data[16 + i * 8 : 20 + i * 8].decode("latin-1").rstrip("\0 ")
        off = struct.unpack_from(e + "I", data, 20 + i * 8)[0]
        img = ShapeImage(name or f"img{i}", 0, 0, 0, None)
        try:
            _parse_entry(data, off, e, gc, img)
        except (ValueError, struct.error, IndexError) as ex:
            img.warnings.append(f"{name}: {ex}")
        out.append(img)
    return out


def _parse_entry(data: bytes, off: int, e: str, gc: bool, img: ShapeImage) -> None:
    blocks = []
    p = off
    while p + 16 <= len(data):
        code = data[p]
        nxt = int.from_bytes(data[p + 1 : p + 4], "little" if e == "<" else "big")
        w, h, _cx, _cy, _xp, yp = struct.unpack_from(e + "6H", data, p + 4)
        body_end = p + nxt if nxt else len(data)
        body = data[p + 16 : body_end]
        if code & 0x80 and refpack.is_refpack(body):
            body = refpack.decompress(body)
        blocks.append((code & 0x7F, w, h, yp >> 12, body))
        if not nxt:
            break
        p += nxt
    if not blocks:
        raise ValueError("empty entry")
    code, w, h, _mips, body = blocks[0]
    img.width, img.height, img.code = w, h, code
    palette = None
    for pcode, pw, ph, _m, pbody in blocks[1:]:
        if 0x20 <= pcode < 0x30:
            palette = _palette(pcode, pbody, max(1, pw * max(ph, 1)))
            if palette is not None and gc and pcode in (0x29, 0x2D):
                # GameCube palettes are RGB5A3 words unless they are 32-bit
                palette = gx_texture.decode_palette(2, pbody, max(1, pw * max(ph, 1)))
            break
    if w == 0 or h == 0:
        raise ValueError("zero-sized image")
    img.rgba = _decode_image(code, w, h, body, palette, gc, img.warnings)
