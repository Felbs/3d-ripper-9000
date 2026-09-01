"""Pokemon Colosseum / XD textures - the image members inside an ``FSYS`` archive.

Once :mod:`gcrip.formats.fsys` opens an archive and inflates its ``LZSS`` members, a good
number of them are plainly images::

    +0    u16 width
    +2    u16 height
    +4    u8  bits per pixel     0x20 = 32, 0x10 = 16
    +5    u8                     0x01 on every image seen
    ...   the rest of a 128-byte header
    +128  GX pixels

``poke_face.fsys`` is the clearest case: 42x84 portraits, one per Pokemon.

**Bits per pixel is what names the format**, not a GX code - the field holds 32 and 16 where GX
would say 6 and 5.  The size then confirms it: ``128 + encoded_size(format, width, height)``
has to equal the member exactly, and on the twenty largest archives of the two discs that holds
for **505 members at 32 bpp and one at 16**, with the 32 bpp group carrying `20 01` at +4 and
the 16 bpp one `10 01` - **two separate bytes**, not a `u16`; read as one it comes out 8193 and
nothing matches.

Decoded, `face344` is 5.1x smoother than a shuffled copy of its own pixels.  That is also the
proof that the ``LZSS`` codec above it is right: a wrong decompression cannot produce a
coherent picture, and "it decoded to the declared length" - which eighty wrong parameter sets
also managed - never could have settled it.

Members whose first four bytes are not plausible dimensions are the archive's other content -
1,456 of them in the same sample - and are left alone.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

HEADER = 128
BPP_AT = 4
MAX_DIM = 1024
# bits per pixel -> the GX format that stores it.  Only these two are attested; a paletted
# depth would need a palette and nothing has located one, so 4 and 8 are not guessed at.
BY_DEPTH = {32: 6, 16: 5}


@dataclass
class Texture:
    width: int
    height: int
    depth: int
    rgba: np.ndarray


def looks_like(head: bytes) -> bool:
    """Cheap check on the 64 bytes ``classify`` sniffs."""
    if len(head) < BPP_AT + 2:
        return False
    width, height = struct.unpack_from(">2H", head, 0)
    depth = head[BPP_AT]
    return 0 < width <= MAX_DIM and 0 < height <= MAX_DIM and depth in BY_DEPTH


def texture(data: bytes) -> Texture | None:
    if len(data) < HEADER + 32 or not looks_like(data[:64]):
        return None
    width, height = struct.unpack_from(">2H", data, 0)
    depth = data[BPP_AT]
    fmt = BY_DEPTH.get(depth)
    if fmt is None:
        return None
    # the member has to be exactly the header plus one GX buffer for its own dimensions
    if HEADER + gx.encoded_size(fmt, width, height) != len(data):
        return None
    rgba = gx.decode(fmt, width, height, data[HEADER:])
    return Texture(width, height, depth, rgba)
