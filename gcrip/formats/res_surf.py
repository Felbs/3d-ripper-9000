"""``surf`` textures inside ``res\\n`` resource files (Samurai Jack: The Shadow of Aku, Digimon
Rumble Arena 2, Lemony Snicket).

A section is a 32-byte header, then the palette, then a GX mip chain::

    +0   u32 0
    +4   u32 id
    +8   u8  format      2 = GX C4 (4 bpp), 3 = GX C8 (8 bpp)
    +9   u8, +10 u8
    +11  u8  mip levels
    +12  u16 width       big-endian
    +14  u16 height      big-endian
    +16  ...
    +32  palette, RGB565, two bytes per entry
    ...  mip chain, level 0 first

Nothing states the palette length, so it is what remains once the mip chain is subtracted from
the section: ``palette = size - 32 - chain(width, height, format, levels)``.  Two things had to
be right before that arithmetic worked, and both were wrong on the first attempt:

* the **levels** byte at +11.  Sections with 8 levels are the majority, and treating everything
  as a single level leaves 300+ sections unexplained;
* **GX tile padding**.  A mip level is not ``w * h * bpp / 8`` - it is padded out to whole
  tiles, so a 1x1 level still costs 32 bytes.  Ignoring that gives palette lengths like 139 and
  341 bytes, which cannot be a palette of two-byte entries; with it, they collapse onto 32, 64,
  128, 192, 256 ... - 387 of 552 sections land exactly on a standard palette size and only 20
  fail to resolve at all.

The palette is **RGB565, not RGB5A3**.  Both decode Samurai Jack's ``cave_armor.res`` to the
same coherent three armour plates, but RGB5A3 renders them nearly black where RGB565 gives the
red and gold they should be.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

HEADER = 32
PALETTE_AT = HEADER
RGB565 = 1
GX_FORMAT = {2: 8, 3: 9}  # header byte -> GX C4 / C8
MAX_DIM = 2048
MAX_LEVELS = 12
MAX_PALETTE = 1024  # bytes


@dataclass
class Surf:
    width: int
    height: int
    format: int  # the GX format, 8 (C4) or 9 (C8)
    levels: int
    palette_bytes: int


def _chain(width: int, height: int, fmt: int, levels: int) -> int:
    total = 0
    for _ in range(levels):
        total += gx.encoded_size(fmt, max(1, width), max(1, height))
        width = max(1, width // 2)
        height = max(1, height // 2)
    return total


def header(data: bytes) -> Surf | None:
    """The description of a surf section, or None if it does not add up."""
    if len(data) < HEADER + 4:
        return None
    fmt, levels = data[8], data[11]
    width, height = struct.unpack_from(">2H", data, 12)
    if fmt not in GX_FORMAT or not 1 <= levels <= MAX_LEVELS:
        return None
    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None
    palette = len(data) - HEADER - _chain(width, height, GX_FORMAT[fmt], levels)
    if not (0 <= palette <= MAX_PALETTE) or palette % 2:
        return None
    return Surf(width, height, GX_FORMAT[fmt], levels, palette)


def is_surf(data: bytes) -> bool:
    return header(data) is not None


def decode(data: bytes) -> np.ndarray | None:
    """RGBA of the top mip level."""
    info = header(data)
    if info is None:
        return None
    pixels_at = PALETTE_AT + info.palette_bytes
    need = gx.encoded_size(info.format, info.width, info.height)
    if pixels_at + need > len(data):
        return None
    entries = info.palette_bytes // 2
    palette = np.zeros((256, 4), np.uint8)
    if entries:
        decoded = gx.decode_palette(RGB565, data[PALETTE_AT:pixels_at], entries)
        palette[: min(entries, 256)] = decoded[: min(entries, 256)]
    pixels = data[pixels_at : pixels_at + need]
    return gx.decode(info.format, info.width, info.height, pixels, palette)
