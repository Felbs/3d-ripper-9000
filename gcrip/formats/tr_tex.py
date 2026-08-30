"""Terminal Reality ``.TEX`` textures, as shipped inside the POD archives (BloodRayne 3,785,
Blowout 787 - see :mod:`gcrip.formats.pod`).

A short little-endian header, then the pixels::

    u32 version     2 (BloodRayne) or 3 (Blowout)
    u32 format
    u32 width
    u32 height
    u32 [2]         zero on every texture seen
    u32             version 3 only - also zero

so the header is 24 bytes in version 2 and 28 in version 3.  Getting this wrong shifts the
pixels by four bytes and every texture decodes to noise, which is the only trap in the format.

The format word is Terminal Reality's own, not a GX code, but the payload underneath is
straight GX:

===== ============================ =====================================================
code  layout                       payload
===== ============================ =====================================================
11    GX ``CMPR`` (DXT1 in 8x8      exactly 4 bits per pixel, no palette, no mip chain
      blocks of 2x2 sub-blocks)
19    GX ``C8`` (8x4 tiles)        512-byte palette FIRST (256 entries, ``RGB5A3``),
                                    then one index byte per pixel
===== ============================ =====================================================

The bits-per-pixel arithmetic is what identifies them: every ``11`` texture measures 4.000
bpp across all 20 sizes on Blowout, and every ``19`` texture measures exactly
``8 bpp + 512 bytes`` (9.000 at 64x64, 8.250 at 128x128, 8.062 at 256x256), which is a
256-entry palette and nothing else.  Some textures carry a few bytes of tail padding, so the
payload is sliced to the size GX needs rather than trusted whole.

Codes 1, 2, 3 and 8 are NOT decoded - 100 of BloodRayne's 3,785 textures, none on Blowout:

* ``1`` (one texture, 9.5 bpp) and ``8`` (25, 8.125 / 8.5 / 10.0 bpp) are paletted, but the
  palette is 256 bytes rather than 512 and the surplus varies with the texture, so the entry
  count is not fixed at 256 and has still to be worked out;
* ``2`` (64, 16.02 - 17.5 bpp) is 16 bits per pixel plus a variable tail, and neither
  ``RGB5A3`` nor ``RGB565`` produces an image;
* ``3`` (10, exactly 32.0 bpp) is 32 bits per pixel but NOT GX ``RGBA8``: decoding it as one
  gives vertical stripes, so its tiling differs.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import gx_texture as gx

HEADER = 0x1C  # version 3; version 2 stops four bytes earlier
HEADER_V2 = 0x18
PALETTE = 512
PALETTE_ENTRIES = 256
RGB5A3 = 2

CMPR = 11
CI8 = 19
GX_FOR = {CMPR: 0xE, CI8: 0x9}
MAX_DIM = 4096


def header_size(version: int) -> int:
    return HEADER_V2 if version == 2 else HEADER


def is_tex(head: bytes, size: int | None = None) -> bool:
    if len(head) < HEADER_V2:
        return False
    version, fmt, width, height = struct.unpack_from("<4I", head, 0)
    if version not in (2, 3) or fmt not in GX_FOR:
        return False
    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return False
    if width & (width - 1) or height & (height - 1):  # GX sizes are powers of two
        return False
    return size is None or size >= header_size(version) + needed(fmt, width, height)


def needed(fmt: int, width: int, height: int) -> int:
    body = gx.encoded_size(GX_FOR[fmt], width, height)
    return body + PALETTE if fmt == CI8 else body


def decode(data: bytes) -> np.ndarray | None:
    """RGBA pixels, or None if this is not a texture we can read."""
    if not is_tex(data[:HEADER], len(data)):
        return None
    version, fmt, width, height = struct.unpack_from("<4I", data, 0)
    body = data[header_size(version) :]
    if fmt == CI8:
        palette = gx.decode_palette(RGB5A3, body[:PALETTE], PALETTE_ENTRIES)
        pixels = body[PALETTE : PALETTE + gx.encoded_size(GX_FOR[CI8], width, height)]
        return gx.decode(GX_FOR[CI8], width, height, pixels, palette)
    return gx.decode(GX_FOR[CMPR], width, height, body[: gx.encoded_size(0xE, width, height)])
