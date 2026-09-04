"""Climax ``.bog`` textures (``BOG 1.01`` on ATV: Quad Power Racing 2 and The Italian Job,
``BOG 1.02`` on Hot Wheels World Race) - ``cBogFile::Load`` and ``cTexture::LoadTextureBog``
in the Hot Wheels ``main.dol`` (its ``HotwheelsFCDntsc.map`` names them).

A header, big-endian, then the GX image as the hardware wants it::

    +0    char magic[12]    "BOG 1.01   " / "BOG 1.02   "
    +12   u32 format        Blimey eImageFormat, mapped by BlimeyToGX (below)
    +16   u32 width
    +20   u32 height
    +24   u32 mip levels
    +28   u32 1
    +32   u32 image bytes
    +40   (1.01) / +56 (1.02): palette, then the tiles - 256 x ARGB8888 for C8 (format
          0x40), 16 x for C4 (0x80)

Version 1.02's ``cBogFile`` is 56 bytes (Hot Wheels copies exactly that many); 1.01's
files (ATV, The Italian Job) start their tiles 40 bytes in.

BlimeyToGX: 2, 8 -> RGB5A3; 4 -> RGB565; 0x10, 0x20, 0x200, 0x8000 -> RGBA8; 0x40 -> C8;
0x80 -> C4; 0x100, 0x800, 0x2000, 0x4000 -> CMPR.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

MAGIC = b"BOG 1.0"
HEADER = 56
HEADERS = {b"BOG 1.01": 40, b"BOG 1.02": 56}
GX_FOR = {
    2: 5,
    8: 5,
    4: 4,
    0x10: 6,
    0x20: 6,
    0x200: 6,
    0x8000: 6,
    0x40: 9,
    0x80: 8,
    0x100: 0xE,
    0x800: 0xE,
    0x2000: 0xE,
    0x4000: 0xE,
}
PALETTE_ENTRIES = {9: 256, 8: 16}
MAX_DIM = 4096


@dataclass
class Bog:
    format: int
    width: int
    height: int
    levels: int
    image_bytes: int
    data_at: int


def header(head: bytes) -> Bog | None:
    if len(head) < 40 or head[:8] not in HEADERS:
        return None
    fmt, width, height, levels = struct.unpack_from(">4I", head, 12)
    size = struct.unpack_from(">I", head, 32)[0]
    if fmt not in GX_FOR or not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None
    return Bog(GX_FOR[fmt], width, height, levels, size, HEADERS[head[:8]])


def is_bog(head: bytes) -> bool:
    return header(head) is not None


def _palette(raw: bytes, entries: int) -> np.ndarray:
    argb = np.frombuffer(raw, np.uint8, entries * 4).reshape(entries, 4)
    return np.ascontiguousarray(argb[:, [1, 2, 3, 0]])  # ARGB -> RGBA


def decode(data: bytes) -> np.ndarray | None:
    h = header(data[:HEADER])
    if h is None:
        return None
    at = h.data_at
    palette = None
    if h.format in PALETTE_ENTRIES:
        n = PALETTE_ENTRIES[h.format]
        if at + 4 * n > len(data):
            return None
        palette = _palette(data[at : at + 4 * n], n)
        at += 4 * n
    need = gx.encoded_size(h.format, h.width, h.height)
    if at + need > len(data):
        return None
    return gx.decode(h.format, h.width, h.height, data[at : at + need], palette)
