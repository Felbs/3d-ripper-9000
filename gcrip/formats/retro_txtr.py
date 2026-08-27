"""Retro TXTR textures (Metroid Prime 1/2) -> RGBA via the GX decoder.

u32 format (Retro numbering, below), u16 width, u16 height, u32 mip count,
[indexed formats: u32 palette format (0 IA8, 1 RGB565, 2 RGB5A3), u16 w, u16 h,
 w*h u16 entries], then the mip chain, largest first, in GX tiled layout.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import gx_texture

# Retro format id -> GX format id (gx_texture numbering)
FORMATS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 8, 5: 9, 6: 10, 7: 4, 8: 5, 9: 6, 10: 14}
NAMES = {
    0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "C4", 5: "C8", 6: "C14X2",
    7: "RGB565", 8: "RGB5A3", 9: "RGBA8", 10: "CMPR",
}  # fmt: skip


class TxtrError(ValueError):
    pass


def is_txtr(head: bytes) -> bool:
    if len(head) < 12:
        return False
    fmt, w, h, mips = struct.unpack_from(">IHHI", head, 0)
    return fmt in FORMATS and 0 < w <= 4096 and 0 < h <= 4096 and 0 < mips <= 16


def decode(data: bytes) -> np.ndarray:
    """Mip level 0 as an (H, W, 4) uint8 array."""
    if len(data) < 12:
        raise TxtrError("truncated TXTR header")
    fmt, w, h, mips = struct.unpack_from(">IHHI", data, 0)
    if fmt not in FORMATS:
        raise TxtrError(f"unknown TXTR format {fmt}")
    pos = 12
    palette = None
    if fmt in (4, 5, 6):
        pal_fmt, pw, ph = struct.unpack_from(">IHH", data, pos)
        pos += 8
        count = pw * ph
        palette = gx_texture.decode_palette(pal_fmt, data[pos : pos + count * 2], count)
        pos += count * 2
    gx = FORMATS[fmt]
    need = gx_texture.encoded_size(gx, w, h)
    return gx_texture.decode(gx, w, h, data[pos : pos + need], palette)
