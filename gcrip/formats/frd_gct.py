"""Free Radical ``gct`` textures - the members of the ``P4CK`` / ``P5CK`` / ``P8CK`` archives
(:mod:`gcrip.formats.frd_pak`).  A 149-archive sample across TimeSplitters 2, TimeSplitters:
Future Perfect and Second Sight holds 12,974 of them.

Big-endian, a 32-byte header and then the pixels::

    +0   u32 width
    +4   u32 height
    +8   u32 width again
    +12  u32 height again
    +16  u16 mip levels | u16 format
    +20  12 bytes

The doubled width and height are the cheap check that the header is being read at all; the
mip count sits in the **high half** of the word at +16, which is why one file in the sample
reads 196,613 as a format and turns out to be `0x0003_0005` - three levels of format 5.

The format code is Free Radical's own, not a GX code, and it does not map one-to-one:

| code | what it is |
|---|---|
| 2, 13 | `CMPR` - two codes, one format |
| 6, 8 | `RGB5A3` |
| 4, 5, 7, 10, 12 | 8 bits a pixel, **palette-indexed, and the palette is not in the file** |
| 11 | 4 bits a pixel, likewise |

The confirmed four are the bulk of them.  The palette-indexed codes are left alone rather than
guessed at: at 8 bits a pixel with no palette the only GX candidates are `I8` and `IA4`, and
both give vertical banding on a texture that should be a sniper scope, which is what an index
stream looks like when it is drawn as intensity.  Whatever holds their palettes is somewhere
else in the archive.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

HEADER = 32
MAX_DIM = 4096
MAX_LEVELS = 16
CMPR, RGB5A3 = 0xE, 5
FORMATS = {2: CMPR, 13: CMPR, 6: RGB5A3, 8: RGB5A3}


@dataclass
class Texture:
    width: int
    height: int
    format: int
    levels: int


def looks_like(head: bytes) -> bool:
    """What can be checked in the 64 bytes a plugin's ``detect`` is given - everything but
    the pixel length, which needs the whole member (gcrip.classify.SNIFF_BYTES)."""
    return _read(head) is not None


def _read(data: bytes) -> Texture | None:
    if len(data) < HEADER:
        return None
    width, height, again_w, again_h = struct.unpack_from(">4I", data, 0)
    levels, code = struct.unpack_from(">2H", data, 16)
    if width != again_w or height != again_h:
        return None
    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM) or levels > MAX_LEVELS:
        return None
    fmt = FORMATS.get(code)
    if fmt is None:
        return None
    return Texture(width, height, fmt, levels or 1)


def header(data: bytes) -> Texture | None:
    """The full check, pixel length included."""
    tex = _read(data)
    if tex is None or HEADER + gx.encoded_size(tex.format, tex.width, tex.height) > len(data):
        return None
    return tex


def is_gct(data: bytes) -> bool:
    return header(data) is not None


def decode(data: bytes) -> np.ndarray | None:
    """RGBA of the top mip level."""
    tex = header(data)
    if tex is None:
        return None
    need = gx.encoded_size(tex.format, tex.width, tex.height)
    return gx.decode(tex.format, tex.width, tex.height, data[HEADER : HEADER + need])
