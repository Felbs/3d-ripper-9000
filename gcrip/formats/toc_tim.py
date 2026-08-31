"""``TIM`` textures - the members of Spawn: Armageddon's ``TOC`` archives
(:mod:`gcrip.formats.toc_wad`).  5,919 of the disc's 12,034 members are these.

Big-endian, sixteen bytes and then the pixels::

    +0   u32 mip levels          1 or 2
    +4   u16 format              a **real GX code** - 0x0e is CMPR
    +6   u16 width
    +8   u16 height
    +10  u16 0x0020
    +12  u32 pixel bytes
    +16  the pixels

The name is Sony's but the contents are not: the format word holds an ordinary GX code, so no
mapping table is needed, and ``pixel bytes == encoded_size(format, width, height)`` has to hold
- it does on every one of the 82 textures in `global.wad`, which is what confirms the header is
being read right rather than merely producing a picture.

A member is a little larger than its pixels (32,864 bytes for 32,768 of `CMPR`); the tail is
left alone, since the size field says exactly where the image ends.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

HEADER = 16
MAX_DIM = 4096
MAX_LEVELS = 16


@dataclass
class Texture:
    width: int
    height: int
    format: int
    levels: int
    size: int


def header(data: bytes) -> Texture | None:
    if len(data) < HEADER:
        return None
    levels = struct.unpack_from(">I", data, 0)[0]
    fmt, width, height, _flag = struct.unpack_from(">4H", data, 4)
    size = struct.unpack_from(">I", data, 12)[0]
    if not 0 < levels <= MAX_LEVELS or not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None
    if fmt not in gx.TILE_DIMS or size != gx.encoded_size(fmt, width, height):
        return None
    return Texture(width, height, fmt, levels, size)


def is_tim(data: bytes) -> bool:
    return header(data) is not None


def decode(data: bytes) -> np.ndarray | None:
    """RGBA of the top mip level."""
    tex = header(data)
    if tex is None or HEADER + tex.size > len(data):
        return None
    return gx.decode(tex.format, tex.width, tex.height, data[HEADER : HEADER + tex.size])
