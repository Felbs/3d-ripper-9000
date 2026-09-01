"""THQ ``g4rc`` textures - Avatar: The Last Airbender, Jimmy Neutron: Attack of the Twonkies.

:mod:`gcrip.formats.thq_pack` already opens these discs' archives - all nine of Avatar's, 245
members and 699 of its 700 MB - but every member is a ``.rad`` object and nothing read them,
so the disc reported nothing.  A ``.rad`` turns out to be **another pack**, and its leaves are
``.rcb`` files that are plain zlib streams.  Inflated, 28 of 32 in ``boot.rad`` carry one of
three tags: ``g4rc`` (24, the ``tex_*`` and ``tx8_*`` files), ``bats`` (3) and ``0lmg`` (1).

``g4rc`` is a texture.  Big-endian, 32-byte header::

    +0   char magic[4]   "g4rc"
    +4   u32 version     7
    +8   u32 hash
    +12  u32 payload bytes   (the file is 32 + this)
    +16  u32 packed size     see below
    +20  u32 mip levels
    +24  u32 0
    +28  u32 pixel bytes
    +32  the pixels, GX CMPR, level 0 first

**The dimensions are packed into the word at +16: ``width - 1`` in bits 0-7 and ``height - 1``
in bits 10-17.**  Nothing in the header states them plainly, and the three-bit gap between the
fields is what makes the packing hard to see - read as two bytes it gives 16 and 60 for a
16x16 image rather than 16 and 16.

That reading is not a fit, it is checked: the CMPR mip chain for those dimensions has to equal
the ``pixel bytes`` at +28, and it does on **18 of the 24** ``g4rc`` objects in ``boot.rad`` -
160 bytes for 16x16 over two levels, 16,384 for 256x128, 32,768 for 256x256.  The six that do
not match are not textures at all: four are fonts and a string table carrying zero mip levels,
and two declare zero pixel bytes.  They are declined.

Decoded against a shuffled copy of their own blocks the images score **3.5x to 10.9x** smoother,
which is where every texture genuinely cracked in this project sits.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

MAGIC = b"g4rc"
HEADER = 32
PACKED_AT = 16
LEVELS_AT = 20
PIXELS_AT = 28
WIDTH_SHIFT = 0
HEIGHT_SHIFT = 10
DIM_MASK = 0xFF
FORMAT = 14  # GX CMPR
MAX_LEVELS = 16
MAX_DIM = 256
ZLIB_CMF = 0x78


@dataclass
class Texture:
    width: int
    height: int
    levels: int
    rgba: np.ndarray


def is_g4rc(head: bytes) -> bool:
    return head[:4] == MAGIC


def is_rcb(head: bytes) -> bool:
    """The leaves of a ``.rad`` are raw zlib."""
    return len(head) >= 2 and head[0] == ZLIB_CMF and head[1] in (0x01, 0x5E, 0x9C, 0xDA)


def inflate(data: bytes, limit: int = 64 << 20) -> bytes | None:
    if not is_rcb(data[:2]):
        return None
    try:
        out = zlib.decompressobj().decompress(data, limit)
    except zlib.error:
        return None
    return out or None


def _chain(width: int, height: int, levels: int) -> int:
    total = 0
    w, h = width, height
    for _ in range(levels):
        total += gx.encoded_size(FORMAT, max(w, 1), max(h, 1))
        w, h = max(w // 2, 1), max(h // 2, 1)
    return total


def texture(data: bytes) -> Texture | None:
    """One image, or None when the object is not a texture at all."""
    if len(data) < HEADER or not is_g4rc(data[:4]):
        return None
    packed, levels, _zero, pixels = struct.unpack_from(">4I", data, PACKED_AT)
    if not (1 <= levels <= MAX_LEVELS) or pixels <= 0:
        return None
    width = ((packed >> WIDTH_SHIFT) & DIM_MASK) + 1
    height = ((packed >> HEIGHT_SHIFT) & DIM_MASK) + 1
    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None
    # the declared pixel count has to be exactly the mip chain for those dimensions
    if _chain(width, height, levels) != pixels:
        return None
    need = gx.encoded_size(FORMAT, width, height)
    if len(data) < HEADER + need:
        return None
    rgba = gx.decode(FORMAT, width, height, data[HEADER : HEADER + need])
    return Texture(width, height, levels, rgba)
