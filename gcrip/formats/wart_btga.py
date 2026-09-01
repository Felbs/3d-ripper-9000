"""Warthog `.btga` textures - the image resources inside a ``WART3.00`` `.hog` archive.

Once :mod:`gcrip.plugins.wart_hog` opens an archive and decompresses its members, the `.btga`
are plain GX textures behind a 96-byte header::

    +4    u32  resource kind, 3 for a texture (10 .bmsh, 1 .bskl, 2 .banr)
    +25   u8   mipmapped flag, set when the chain has more than one level
    +27   u8   format code, 0x01 or 0x81
    +60   u32  width
    +64   u32  height
    +68   u32  levels in the mip chain
    +88   u32  payload bytes, repeated at +92
    +96   the GX pixels, one mip chain, no palette

**The size arithmetic is the check and it is self-proving**: the declared payload has to equal
both ``len(data) - 96`` and the sum of ``encoded_size(format, w >> i, h >> i)`` over the
declared levels.  On the 26 textures of Animaniacs' ``frontend.hog`` that holds for all 26,
which is also what fixes the bits per texel - 0x01 is four and 0x81 is eight.

**Which four-bit format** is settled by smoothness against a shuffled copy of each image's own
pixels: `CMPR` scores 1.6 to 24.5 across the 21 samples where `I4` scores 0.99 to 2.3, and the
`I4` figures sit on the noise floor.  `C4` and `C8` are excluded by the arithmetic itself -
both need a palette, and the payload is exactly the pixels with no room for one.

**Which eight-bit format** cannot be settled that way, because `I8` and `IA4` share the 8x4
tile and score within 0.05 of each other on every sample.  What separates them is splitting the
byte: under `I8` the low nibble is the least-significant bits of one ramp and should be close to
noise, under `IA4` it is the alpha channel and should be as structured as the intensity.  It is
the second - 1.71 to 4.17 against 1.62 to 4.01 for the high nibble - and the two samples that
carry the argument are the ones using the full byte range (`ahud04` at 137 distinct values,
`animaniacs_text` at 256), where an `I8` low nibble could not have scored that.  The fonts and
HUD art this format holds want an alpha channel, and `IA4` is what gives them one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

HEADER = 96
KIND_AT = 4
KIND_TEXTURE = 3
CODE_AT = 27
WIDTH_AT = 60
HEIGHT_AT = 64
LEVELS_AT = 68
PAYLOAD_AT = 88
MAX_DIM = 4096
MAX_LEVELS = 16
# engine format code -> GX format.  Only these two are attested; anything else is declined
# rather than guessed, because a wrong format still decodes to a plausible-looking image.
BY_CODE = {0x01: 14, 0x81: 2}


@dataclass
class Texture:
    width: int
    height: int
    levels: int
    fmt: int
    rgba: np.ndarray


def _chain(fmt: int, width: int, height: int, levels: int) -> int:
    return sum(
        gx.encoded_size(fmt, max(1, width >> i), max(1, height >> i)) for i in range(levels)
    )


def looks_like(head: bytes) -> bool:
    """Cheap check on the 64 bytes ``classify`` sniffs - the dimensions sit past them, so this
    can only test the kind and the format code."""
    if len(head) < CODE_AT + 1:
        return False
    (kind,) = struct.unpack_from(">I", head, KIND_AT)
    return kind == KIND_TEXTURE << 24 and head[CODE_AT] in BY_CODE


def texture(data: bytes) -> Texture | None:
    if len(data) < HEADER or not looks_like(data[:64]):
        return None
    width, height = struct.unpack_from(">I", data, WIDTH_AT)[0], struct.unpack_from(
        ">I", data, HEIGHT_AT
    )[0]
    (levels,) = struct.unpack_from(">I", data, LEVELS_AT)
    (payload,) = struct.unpack_from(">I", data, PAYLOAD_AT)
    fmt = BY_CODE.get(data[CODE_AT])
    if fmt is None or not 0 < width <= MAX_DIM or not 0 < height <= MAX_DIM:
        return None
    if not 0 < levels <= MAX_LEVELS or HEADER + payload != len(data):
        return None
    if _chain(fmt, width, height, levels) != payload:
        return None
    return Texture(width, height, levels, fmt, gx.decode(fmt, width, height, data[HEADER:]))
