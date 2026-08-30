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
| 2, 3, 4, 10, 13 | `CMPR` |
| 5, 7 | `I8` |
| 6, 8 | `RGB5A3` |
| 0 | `RGBA8` |
| 9, 11, 12 | not identified |

**A file usually holds more than the top level**, so dividing its length by the pixel count and
reading the answer as bits per pixel is what leads you astray.  Codes 4 and 10 carry exactly
twice the `CMPR` data their dimensions need, which comes out as "8 bits a pixel" and points at
`I8`, `IA4` or a palette that is not in the file - and `I8` duly draws a GameCube controller as
vertical banding, which reads as an index stream shown as intensity.  Taking the first
``encoded_size(fmt, w, h)`` bytes draws the controller.

Where the mip count is set the whole chain is stored, and then the ratio does identify the
format, because a full chain is four thirds of the top level:

    bytes / pixels    0.67    1.33    2.00    5.33
    top level         0.5     1.0     1.5     4.0
    format            CMPR    I8      ?       RGBA8

That is how `0` was settled as `RGBA8` (a sky gradient), `5` and `7` as `I8` (a marble panel
and a lens flare) and `3` as `CMPR`.  Codes 9, 11 and 12 are left unidentified rather than
guessed - together they are under 3% of the sample.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

HEADER = 32
MAX_DIM = 4096
MAX_LEVELS = 16
CMPR, RGB5A3, I8, RGBA8 = 0xE, 5, 1, 6
# Free Radical's own numbering: several codes share a format
FORMATS = {
    0: RGBA8,
    2: CMPR,
    3: CMPR,
    4: CMPR,
    5: I8,
    6: RGB5A3,
    7: I8,
    8: RGB5A3,
    10: CMPR,
    13: CMPR,
}


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
