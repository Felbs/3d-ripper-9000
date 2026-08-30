"""``GCT`` textures (Darkened Skye, 4,340 files).

A 32-byte big-endian header and then a GX mip chain::

    +0   u16 magic 0xDEAD
    +2   u16 width
    +4   u16 height
    +6   u8  mip levels minus one
    +7   u8
    +8   u32 0x00CCCCCC   fill
    +12  u32 GX format    14 = CMPR, 5 = RGB5A3, 1 = I8 - the real GX code, not a private one
    +16  16 zero bytes
    +32  pixels

Two fields had to be told apart.  Byte +6 looks like a format at a glance and is not - it is the
level count less one, and reading it as a format leaves every file unexplained.  The **format is
the `u32` at +12**, and it holds ordinary GX codes, so nothing has to be mapped.

The check is the arithmetic: with levels taken from +6 and the format from +12, the mip chain
plus the 32-byte header accounts for the file size **exactly** on 149 of 150 sampled files.
That is also what distinguishes formats the size alone cannot - `I8` and `C8` are both 8 bits
per pixel, so only the header separates them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

MAGIC = 0xDEAD
HEADER = 32
MAX_DIM = 4096
MAX_LEVELS = 16


@dataclass
class Texture:
    width: int
    height: int
    format: int
    levels: int


def header(data: bytes) -> Texture | None:
    if len(data) < HEADER:
        return None
    magic, width, height = struct.unpack_from(">3H", data, 0)
    if magic != MAGIC or not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None
    levels = data[6] + 1
    fmt = struct.unpack_from(">I", data, 12)[0]
    if levels > MAX_LEVELS or fmt not in gx.TILE_DIMS:
        return None
    return Texture(width, height, fmt, levels)


def is_gct(data: bytes) -> bool:
    return header(data) is not None


def chain(tex: Texture) -> int:
    """Bytes of the whole mip chain - the value that has to match the file size."""
    total = 0
    w, h = tex.width, tex.height
    for _ in range(tex.levels):
        total += gx.encoded_size(tex.format, max(1, w), max(1, h))
        w, h = max(1, w // 2), max(1, h // 2)
    return total


def decode(data: bytes) -> np.ndarray | None:
    """RGBA of the top mip level."""
    tex = header(data)
    if tex is None:
        return None
    need = gx.encoded_size(tex.format, tex.width, tex.height)
    if HEADER + need > len(data):
        return None
    return gx.decode(tex.format, tex.width, tex.height, data[HEADER : HEADER + need])
