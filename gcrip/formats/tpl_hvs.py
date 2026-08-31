"""High Voltage Software's ``TPL`` variant, as found in the ``FSTA`` ``.jam`` archives of
The Grim Adventures of Billy & Mandy and Codename: Kids Next Door.

It carries Nintendo's magic (``00 20 AF 30``) and nothing else about it is stock, which is the
trap: handing one to :func:`gcrip.formats.tpl.parse` raises rather than returning noise, but
only because the numbers happen to be wild - matching magic does not mean matching layout.

Stock TPL is ``magic | u32 count | u32 table offset``, and the table holds a pair of pointers
per image.  This variant inserts an extra ``u32`` (always zero) so the table offset sits at
**+12**, and the table holds the image headers **inline** rather than pointers to them::

    +0   u32 magic 0x0020AF30
    +4   u32 image count
    +8   u32 0
    +12  u32 table offset            (0x14 on every file seen)
    ...  image headers, 0x2c apart:
             u16 height | u16 width | u32 GX format | u32 data offset
             then wrap, filter and lod fields

Data offsets are relative to the start of the TPL, not to the containing archive - an early
read assuming otherwise had a 4 KB member pointing at byte 2,142,000 of the ``.jam``.

The 0x2c stride is confirmed by the pixels rather than assumed: in ``ZOMBIEG1`` the two image
headers sit at 0x14 and 0x40, and the first image (64x64 ``CMPR``, 2,048 bytes) starts at 0x6c
and ends exactly where the second one's data begins at 0x86c.  Over 41 members of Billy &
Mandy's smallest 20 archives this reads 50 images with no failures, all ``CMPR``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx
from gcrip.formats.tpl import MAGIC

TABLE_AT = 12
STRIDE = 0x2C
MAX_IMAGES = 4096
MAX_DIM = 2048


@dataclass
class Image:
    width: int
    height: int
    format: int
    offset: int


def images(data: bytes) -> list[Image]:
    """Every image, or [] if this is not a High Voltage TPL."""
    if len(data) < 0x20 or data[:4] != MAGIC:
        return []
    count, spare, table = struct.unpack_from(">3I", data, 4)
    if spare or not 0 < count <= MAX_IMAGES or not TABLE_AT <= table < len(data):
        return []
    out: list[Image] = []
    for i in range(count):
        p = table + i * STRIDE
        if p + 12 > len(data):
            return []
        height, width, fmt, offset = struct.unpack_from(">HHII", data, p)
        if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM) or fmt not in gx.TILE_DIMS:
            return []
        if offset + gx.encoded_size(fmt, width, height) > len(data):
            return []
        out.append(Image(width, height, fmt, offset))
    return out


def is_hvs(data: bytes) -> bool:
    return bool(images(data))


def decode(data: bytes, image: Image) -> np.ndarray:
    need = gx.encoded_size(image.format, image.width, image.height)
    pixels = data[image.offset : image.offset + need]
    return gx.decode(image.format, image.width, image.height, pixels)
