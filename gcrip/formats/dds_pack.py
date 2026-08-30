"""Byte-swapped DDS textures, packed many to a file.

Home Run King keeps its art in ``data.afs`` as 236 members, and each member is a **run of
concatenated DDS files** - 118 of them in the first one, 256x128 and 64x128 and 256x64 - with
two GameCube twists:

* the header is **big-endian**, so ``dwSize`` reads ``00 00 00 7c`` rather than ``7c 00 00 00``;
* the pixel-format fourcc is stored **reversed**, ``1TXD`` for ``DXT1``.

The fourcc is the only thing that is DXT1 about the pixels: the payload is **GX ``CMPR``** -
the same DXT1 blocks, but in GameCube tiling and byte order - which is what a GameCube build
would upload to the hardware.  The DDS header is left-over tooling metadata.  Decoding it as
linear DXT1 gives noise; the distance between consecutive files proves the point, matching
``gx_texture.encoded_size(CMPR, w, h)`` exactly for every entry (16,384 bytes for a 256x128,
4,096 for a 64x128, 2,048 for a 64x64).

Members are split on the ``DDS `` magic, and every candidate has to carry ``dwSize == 124`` in
one byte order or the other - that check is what stops a ``DDS `` sequence inside pixel data
from being mistaken for a header.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

MAGIC = b"DDS "
HEADER = 128
DDSD_SIZE = 124
MAX_DIM = 8192


@dataclass
class Entry:
    offset: int
    width: int
    height: int
    fourcc: bytes  # the right way round, e.g. b"DXT1"
    big_endian: bool


def _header(data: bytes, at: int) -> Entry | None:
    if at + HEADER > len(data) or data[at : at + 4] != MAGIC:
        return None
    for big in (True, False):
        order = ">2I" if big else "<2I"
        (size,) = struct.unpack_from(">I" if big else "<I", data, at + 4)
        if size != DDSD_SIZE:
            continue
        height, width = struct.unpack_from(order, data, at + 12)
        if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
            continue
        raw = data[at + 84 : at + 88]
        fourcc = raw[::-1] if big else raw
        return Entry(at, width, height, fourcc, big)
    return None


def entries(data: bytes) -> list[Entry]:
    """Every DDS in the blob, in order."""
    out: list[Entry] = []
    p = 0
    while True:
        q = data.find(MAGIC, p)
        if q < 0:
            break
        found = _header(data, q)
        if found is not None:
            out.append(found)
        p = q + 4
    return out


def is_pack(head: bytes) -> bool:
    return _header(head, 0) is not None


GX_CMPR = 0xE


def payload(entry: Entry) -> int:
    """Bytes of pixel data, which is also the distance to the next file."""
    return gx.encoded_size(GX_CMPR, entry.width, entry.height)


def decode(data: bytes, entry: Entry) -> np.ndarray:
    """RGBA for one entry."""
    if entry.fourcc != b"DXT1":
        raise ValueError(f"unsupported pixel format {entry.fourcc!r}")
    start = entry.offset + HEADER
    return gx.decode(GX_CMPR, entry.width, entry.height, data[start : start + payload(entry)])
