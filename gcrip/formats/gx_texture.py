"""GameCube (GX) texture format decoders -> RGBA8 numpy arrays (H, W, 4).

All formats are stored in tiles ("blocks"); tiles are laid out row-major across
the image, and pixels are row-major inside a tile.

  fmt  name    tile   bpp
  0    I4      8x8    4
  1    I8      8x4    8
  2    IA4     8x4    8
  3    IA8     4x4    16
  4    RGB565  4x4    16
  5    RGB5A3  4x4    16
  6    RGBA8   4x4    32   (two 32-byte halves per tile: AR..., then GB...)
  8    C4      8x8    4    palette index
  9    C8      8x4    8    palette index
  10   C14X2   4x4    16   palette index (14 bits)
  14   CMPR    8x8    4    DXT1-like: 4 sub-blocks of 4x4, GC bit ordering

Palette formats: 0 IA8, 1 RGB565, 2 RGB5A3.
"""

from __future__ import annotations

import numpy as np

FORMAT_NAMES = {
    0: "I4",
    1: "I8",
    2: "IA4",
    3: "IA8",
    4: "RGB565",
    5: "RGB5A3",
    6: "RGBA8",
    8: "C4",
    9: "C8",
    10: "C14X2",
    14: "CMPR",
}

TILE_DIMS = {
    0: (8, 8),
    1: (8, 4),
    2: (8, 4),
    3: (4, 4),
    4: (4, 4),
    5: (4, 4),
    6: (4, 4),
    8: (8, 8),
    9: (8, 4),
    10: (4, 4),
    14: (8, 8),
}
BITS_PER_PIXEL = {0: 4, 1: 8, 2: 8, 3: 16, 4: 16, 5: 16, 6: 32, 8: 4, 9: 8, 10: 16, 14: 4}


def has_alpha(fmt: int, palette_fmt: int | None = None) -> bool:
    if fmt in (2, 3, 5, 6, 14):
        return True
    if fmt in (8, 9, 10):
        return palette_fmt in (0, 2)
    return False


def encoded_size(fmt: int, width: int, height: int) -> int:
    tw, th = TILE_DIMS[fmt]
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    return bw * bh * tw * th * BITS_PER_PIXEL[fmt] // 8


def _untile(tiles: np.ndarray, width: int, height: int, tw: int, th: int) -> np.ndarray:
    """tiles: (bh, bw, th, tw, C) -> (height, width, C) cropped."""
    bh, bw = tiles.shape[0], tiles.shape[1]
    img = tiles.transpose(0, 2, 1, 3, 4).reshape(bh * th, bw * tw, -1)
    return img[:height, :width]


def _rgb565_to_rgba(v: np.ndarray) -> np.ndarray:
    r = ((v >> 11) & 0x1F).astype(np.uint16)
    g = ((v >> 5) & 0x3F).astype(np.uint16)
    b = (v & 0x1F).astype(np.uint16)
    out = np.empty(v.shape + (4,), np.uint8)
    out[..., 0] = (r << 3) | (r >> 2)
    out[..., 1] = (g << 2) | (g >> 4)
    out[..., 2] = (b << 3) | (b >> 2)
    out[..., 3] = 255
    return out


def _rgb5a3_to_rgba(v: np.ndarray) -> np.ndarray:
    out = np.empty(v.shape + (4,), np.uint8)
    opaque = (v & 0x8000) != 0
    # RGB555
    r = ((v >> 10) & 0x1F).astype(np.uint16)
    g = ((v >> 5) & 0x1F).astype(np.uint16)
    b = (v & 0x1F).astype(np.uint16)
    out[..., 0] = (r << 3) | (r >> 2)
    out[..., 1] = (g << 3) | (g >> 2)
    out[..., 2] = (b << 3) | (b >> 2)
    out[..., 3] = 255
    # ARGB3444
    a = ((v >> 12) & 0x7).astype(np.uint16)
    r4 = ((v >> 8) & 0xF).astype(np.uint16)
    g4 = ((v >> 4) & 0xF).astype(np.uint16)
    b4 = (v & 0xF).astype(np.uint16)
    t = ~opaque
    out[..., 0][t] = ((r4 << 4) | r4)[t]
    out[..., 1][t] = ((g4 << 4) | g4)[t]
    out[..., 2][t] = ((b4 << 4) | b4)[t]
    out[..., 3][t] = ((a << 5) | (a << 2) | (a >> 1))[t]
    return out


def _ia8_to_rgba(v: np.ndarray) -> np.ndarray:
    out = np.empty(v.shape + (4,), np.uint8)
    i = (v & 0xFF).astype(np.uint8)
    out[..., 0] = i
    out[..., 1] = i
    out[..., 2] = i
    out[..., 3] = (v >> 8).astype(np.uint8)
    return out


def decode_palette(pal_fmt: int, data: bytes, count: int) -> np.ndarray:
    v = np.frombuffer(data[: count * 2], dtype=">u2").astype(np.uint16)
    if pal_fmt == 0:
        return _ia8_to_rgba(v)
    if pal_fmt == 1:
        return _rgb565_to_rgba(v)
    if pal_fmt == 2:
        return _rgb5a3_to_rgba(v)
    raise ValueError(f"unknown palette format {pal_fmt}")


def decode(
    fmt: int,
    width: int,
    height: int,
    data: bytes,
    palette: np.ndarray | None = None,
) -> np.ndarray:
    """Decode one mip level to an (H, W, 4) uint8 RGBA array."""
    if fmt not in TILE_DIMS:
        raise ValueError(f"unsupported texture format {fmt}")
    tw, th = TILE_DIMS[fmt]
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    need = encoded_size(fmt, width, height)
    if len(data) < need:
        data = bytes(data) + b"\x00" * (need - len(data))
    buf = np.frombuffer(data, dtype=np.uint8, count=need)

    if fmt == 0:  # I4
        b = buf.reshape(bh, bw, th, tw // 2)
        hi = (b >> 4) & 0xF
        lo = b & 0xF
        px = np.stack([hi, lo], axis=-1).reshape(bh, bw, th, tw)
        i = ((px << 4) | px).astype(np.uint8)
        rgba = np.stack([i, i, i, np.full_like(i, 255)], axis=-1)
        return _untile(rgba, width, height, tw, th)
    if fmt == 1:  # I8
        i = buf.reshape(bh, bw, th, tw)
        rgba = np.stack([i, i, i, np.full_like(i, 255)], axis=-1)
        return _untile(rgba, width, height, tw, th)
    if fmt == 2:  # IA4
        b = buf.reshape(bh, bw, th, tw)
        i = (b & 0xF).astype(np.uint8)
        a = ((b >> 4) & 0xF).astype(np.uint8)
        i = (i << 4) | i
        a = (a << 4) | a
        rgba = np.stack([i, i, i, a], axis=-1)
        return _untile(rgba, width, height, tw, th)
    if fmt in (3, 4, 5, 10):  # 16-bit formats
        v = buf.view(">u2").astype(np.uint16).reshape(bh, bw, th, tw)
        if fmt == 3:
            rgba = _ia8_to_rgba(v)
        elif fmt == 4:
            rgba = _rgb565_to_rgba(v)
        elif fmt == 5:
            rgba = _rgb5a3_to_rgba(v)
        else:
            if palette is None:
                raise ValueError("C14X2 needs a palette")
            idx = np.minimum(v & 0x3FFF, len(palette) - 1)
            rgba = palette[idx]
        return _untile(rgba, width, height, tw, th)
    if fmt == 6:  # RGBA8: per tile 32 bytes AR pairs then 32 bytes GB pairs
        t = buf.reshape(bh, bw, 2, th * tw, 2)
        a = t[:, :, 0, :, 0].reshape(bh, bw, th, tw)
        r = t[:, :, 0, :, 1].reshape(bh, bw, th, tw)
        g = t[:, :, 1, :, 0].reshape(bh, bw, th, tw)
        b = t[:, :, 1, :, 1].reshape(bh, bw, th, tw)
        rgba = np.stack([r, g, b, a], axis=-1)
        return _untile(rgba, width, height, tw, th)
    if fmt == 8:  # C4
        if palette is None:
            raise ValueError("C4 needs a palette")
        b = buf.reshape(bh, bw, th, tw // 2)
        px = np.stack([(b >> 4) & 0xF, b & 0xF], axis=-1).reshape(bh, bw, th, tw)
        rgba = palette[np.minimum(px, len(palette) - 1)]
        return _untile(rgba, width, height, tw, th)
    if fmt == 9:  # C8
        if palette is None:
            raise ValueError("C8 needs a palette")
        px = buf.reshape(bh, bw, th, tw)
        rgba = palette[np.minimum(px, len(palette) - 1)]
        return _untile(rgba, width, height, tw, th)
    if fmt == 14:
        return _decode_cmpr(buf, width, height, bw, bh)
    raise ValueError(f"unsupported texture format {fmt}")


def _decode_cmpr(buf: np.ndarray, width: int, height: int, bw: int, bh: int) -> np.ndarray:
    """CMPR: 8x8 tiles, each = 4 DXT1 sub-blocks (2x2 arrangement, row-major),
    each sub-block 8 bytes: c0 (u16 BE), c1 (u16 BE), 4 index bytes where the
    top 2 bits of each byte are the LEFTMOST pixel (opposite of PC DXT1)."""
    # (bh, bw, 2, 2, 8) : sub-block rows, sub-block cols, 8 bytes
    sb = buf.reshape(bh, bw, 2, 2, 8)
    c0 = (sb[..., 0].astype(np.uint16) << 8) | sb[..., 1]
    c1 = (sb[..., 2].astype(np.uint16) << 8) | sb[..., 3]
    idx_bytes = sb[..., 4:8]  # (bh,bw,2,2,4) one byte per pixel row
    # 2-bit indices, MSB first: pixel x=0 is bits 7-6
    shifts = np.array([6, 4, 2, 0], dtype=np.uint8)
    idx = (idx_bytes[..., :, None] >> shifts) & 0x3  # (bh,bw,2,2,4rows,4cols)

    rgb0 = _rgb565_to_rgba(c0)[..., :3].astype(np.int32)  # (bh,bw,2,2,3)
    rgb1 = _rgb565_to_rgba(c1)[..., :3].astype(np.int32)
    gt = (c0 > c1)[..., None]  # (bh,bw,2,2,1)
    # third/fourth colors
    rgb2_a = (2 * rgb0 + rgb1) // 3
    rgb3_a = (rgb0 + 2 * rgb1) // 3
    rgb2_b = (rgb0 + rgb1) // 2
    rgb3_b = np.zeros_like(rgb0)
    rgb2 = np.where(gt, rgb2_a, rgb2_b)
    rgb3 = np.where(gt, rgb3_a, rgb3_b)
    a3 = np.where(gt[..., 0], 255, 0).astype(np.uint8)  # (bh,bw,2,2)

    pal = np.stack([rgb0, rgb1, rgb2, rgb3], axis=-2).astype(np.uint8)  # (bh,bw,2,2,4,3)
    alpha = np.stack(
        [np.full_like(a3, 255), np.full_like(a3, 255), np.full_like(a3, 255), a3], axis=-1
    )  # (bh,bw,2,2,4)

    # gather: for each pixel, pick pal[idx]
    b_i, w_i, sy_i, sx_i, y_i, x_i = np.indices(idx.shape, sparse=True)
    rgb = pal[b_i, w_i, sy_i, sx_i, idx]  # (bh,bw,2,2,4,4,3)
    a = alpha[b_i, w_i, sy_i, sx_i, idx]  # (bh,bw,2,2,4,4)
    rgba = np.concatenate([rgb, a[..., None]], axis=-1)  # (bh,bw,2,2,4,4,4)
    # assemble tile: sub-block (sy,sx) covers rows sy*4.., cols sx*4..
    tiles = rgba.transpose(0, 1, 2, 4, 3, 5, 6).reshape(bh, bw, 8, 8, 4)
    return _untile(tiles, width, height, 8, 8)
