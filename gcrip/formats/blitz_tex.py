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

Formats 17 and 19 turn up too.  **Format 17 is 16 bits per pixel** - proved by where its data
ends rather than by decoding it: at exactly ``160 + width * height * 2`` the bytes turn into
plausible big-endian f32 (-7.96, 111.09, -3.49 on the first sample), and across 40 textures the
fraction of sane f32 at each candidate boundary is 0.09 at 4 bpp and 0.06 at 8 bpp against 0.61
at 16 bpp.  So the walk **steps over** a format 17 rather than stopping, and still does not
decode it.

Which 16-bit encoding it is remains open, and the three GX candidates are ruled out.  A
smoothness test - mean absolute difference between neighbouring pixels - identifies both known
formats with an order of magnitude to spare (format 15 scores 0.87 as ``RGBA8`` against 22 or
more for everything else; format 21 scores 2.66 as ``CMPR`` against 59 or more).  Nothing does
that for format 17: the best 16-bit candidate, ``IA8``, sits at 29 with ``RGB565`` at 44 and
``RGB5A3`` at 47, so it is some other 16-bit layout.  Format 19 is only ever 16x16 here and
several candidates decode it to a constant image, which no test can separate.

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
# formats whose size is known but whose encoding is not: the walk steps over them
BYTES_PER_PIXEL = {17: 2}
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
    known = fmt in GX_FOR or fmt in BYTES_PER_PIXEL
    if not known or not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None
    if width & (width - 1) or height & (height - 1):
        return None
    if count != width * height:  # the pack's own consistency check
        return None
    body = at + DESCRIPTOR
    size = (
        gx.encoded_size(GX_FOR[fmt], width, height)
        if fmt in GX_FOR
        else width * height * BYTES_PER_PIXEL[fmt]
    )
    if body + size > len(data):
        return None
    return Texture(width, height, fmt, body, size)


def descriptors(data: bytes) -> list[Texture]:
    """**Every** entry in the chain, decodable or not, or [] if the pack does not open with a
    descriptor.

    Use this to count what a pack holds.  :func:`textures` returns only the entries this module
    can decode, so a census built on it cannot see format 17 at all and will report it as
    absent - which is exactly what happened twice while measuring how common it is.
    """
    out: list[Texture] = []
    at = FIRST
    for _ in range(MAX_TEXTURES):
        found = _descriptor(data, at)
        if found is None:
            break
        out.append(found)
        at = found.offset + found.size
    return out


def textures(data: bytes) -> list[Texture]:
    """Every *decodable* texture in the chain, or [] if the pack does not open with a
    descriptor.  A format whose size is known but whose encoding is not is stepped over, so
    one undecodable entry no longer hides everything behind it.

    This deliberately omits what it cannot decode; :func:`descriptors` is the one to count with.
    """
    return [t for t in descriptors(data) if t.format in GX_FOR]


def decode(data: bytes, tex: Texture) -> np.ndarray:
    pixels = data[tex.offset : tex.offset + tex.size]
    return gx.decode(GX_FOR[tex.format], tex.width, tex.height, pixels)
