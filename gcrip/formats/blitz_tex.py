"""Textures inside a Blitz Games ``.gcp`` pack (Bratz: Rock Angelz, Bad Boys, Pac-Man World 3,
Chicken Little, ...).

The packs that carry no package stamp - 1,121 of the 1,680 on Bratz: Rock Angelz, all named
``common_*`` - are texture packs.  They hold a chain of descriptors, each followed by its own
pixel data::

    0x820  descriptor 0  (160 bytes)
    0x8c0  pixel data 0
           descriptor 1  (160 bytes)
           pixel data 1
           ...

A descriptor is seven big-endian ``u32``::

    u32 width | u32 height | u32 format | u32 0x101 | u32 0 | u32 0xff000000 | u32 width*height

That last field is what makes the walk safe: it has to equal ``width * height``, so a
descriptor either checks out or the chain has ended.  The 160-byte descriptor size is the
``00 00 00 a0`` word that sits at 0x870 in every pack, and it is confirmed by arithmetic - the
gap between the two descriptors of ``common_BP Hair_Hat 01 Sector.gcp`` is 8,352 bytes, which
is 8,192 (``CMPR`` for 128x128) plus exactly 160.

======  ==================
format  encoding
======  ==================
15      GX ``RGBA8``
21      GX ``CMPR``
======  ==================

Formats 17 and 19 turn up too (10 and 1 of a 60-pack sample) and are not decoded; the walk
stops when it meets one rather than guessing at a size it cannot verify.

Nothing here is compressed.  An earlier reading of this format measured the pixels from 0x1000
instead of from the descriptor, which made a 128x128 texture look like 0.39 bytes per pixel -
below even ``CMPR`` - and turned an ordinary GX texture into an imaginary codec.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

FIRST = 0x820
DESCRIPTOR = 160
GX_FOR = {15: 6, 21: 0xE}
MAX_DIM = 2048
MAX_TEXTURES = 4096


@dataclass
class Texture:
    width: int
    height: int
    format: int
    offset: int  # of the pixel data
    size: int


def _descriptor(data: bytes, at: int) -> Texture | None:
    if at + DESCRIPTOR > len(data):
        return None
    width, height, fmt, _flags, _zero, _colour, count = struct.unpack_from(">7I", data, at)
    if fmt not in GX_FOR or not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None
    if width & (width - 1) or height & (height - 1):
        return None
    if count != width * height:  # the pack's own consistency check
        return None
    body = at + DESCRIPTOR
    size = gx.encoded_size(GX_FOR[fmt], width, height)
    if body + size > len(data):
        return None
    return Texture(width, height, fmt, body, size)


def textures(data: bytes) -> list[Texture]:
    """Every texture in the chain, or [] if the pack does not open with a descriptor."""
    out: list[Texture] = []
    at = FIRST
    while len(out) < MAX_TEXTURES:
        found = _descriptor(data, at)
        if found is None:
            break
        out.append(found)
        at = found.offset + found.size
    return out


def decode(data: bytes, tex: Texture) -> np.ndarray:
    pixels = data[tex.offset : tex.offset + tex.size]
    return gx.decode(GX_FOR[tex.format], tex.width, tex.height, pixels)
