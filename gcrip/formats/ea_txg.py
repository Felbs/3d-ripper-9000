"""EA ``TXG`` texture groups - the ``txf`` members of the Tiger Woods ``SHOC`` archives
(:mod:`gcrip.formats.shoc`), 39.8 MB of them across the four discs.

Big-endian, ``char tag[4]`` then ``u32 size``, and **the size excludes the eight-byte header**
- the opposite of the ``SHOC`` archive holding it, where it includes it.  Read the SHOC way the
walk stops on the first chunk; read this way it lands exactly on the member's last byte::

    TXG   char magic[4] "TXG " | u8 version[4]
    HEAD  8 bytes
    TXHE  the texture headers, 88 bytes each
    CLHE  colour-table headers   (always empty here)
    TXDA  the pixels
    CLDA  colour-table data      (always empty here)

``CLHE`` and ``CLDA`` are empty on every group found, so nothing here is palette-indexed -
which matches the formats that turn up: ``CMPR``, ``RGB5A3``, ``I8`` and ``I4``, none of which
needs one.

A header is 88 bytes::

    +0   char name[16]     NUL padded - "tbmulch", "tbcp1", "tbfw1" (turf, cart path, fairway)
    +16  four mip entries of 12 bytes: u32 offset into TXDA, then u16, u16 0xffff, u32 1
    +64  u16 width | u16 height
    +72  u8 GX format

The layout is confirmed by arithmetic rather than by the pictures coming out looking right:
the gap from mip 0 to mip 1 equals ``encoded_size(format, width, height)`` on 128 of a group's
146 textures, and the count times 88 is exactly the ``TXHE`` chunk's length.  The remaining 18
carry a single level, so their second entry is not another offset and the gap means nothing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

MAGIC = b"TXG "
HEADER = 8
ENTRY = 88
NAME = 16
MIP0_AT = 16
SIZE_AT = 64
FORMAT_AT = 72
MAX_DIM = 4096


@dataclass
class Texture:
    name: str
    width: int
    height: int
    format: int
    offset: int


def is_txg(head: bytes) -> bool:
    return head[:4] == MAGIC


def _chunks(data: bytes) -> dict[bytes, bytes]:
    out: dict[bytes, bytes] = {}
    at = HEADER
    while at + HEADER <= len(data):
        tag = data[at : at + 4]
        size = struct.unpack_from(">I", data, at + 4)[0]
        if not all(32 <= c < 127 for c in tag) or at + HEADER + size > len(data):
            break
        out.setdefault(tag, data[at + HEADER : at + HEADER + size])
        at += HEADER + size
    return out


def textures(data: bytes) -> list[Texture]:
    if not is_txg(data[:4]):
        return []
    chunks = _chunks(data)
    headers = chunks.get(b"TXHE")
    pixels = chunks.get(b"TXDA")
    if not headers or not pixels:
        return []
    out = []
    for i in range(len(headers) // ENTRY):
        rec = headers[i * ENTRY : (i + 1) * ENTRY]
        width, height = struct.unpack_from(">2H", rec, SIZE_AT)
        fmt = rec[FORMAT_AT]
        offset = struct.unpack_from(">I", rec, MIP0_AT)[0]
        if fmt not in gx.TILE_DIMS or not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
            continue
        if offset + gx.encoded_size(fmt, width, height) > len(pixels):
            continue
        name = rec[:NAME].split(b"\0")[0].decode("latin-1") or f"texture{i}"
        out.append(Texture(name, width, height, fmt, offset))
    return out


def decode(data: bytes, tex: Texture) -> np.ndarray | None:
    pixels = _chunks(data).get(b"TXDA")
    if pixels is None:
        return None
    size = gx.encoded_size(tex.format, tex.width, tex.height)
    try:
        return gx.decode(
            tex.format, tex.width, tex.height, pixels[tex.offset : tex.offset + size], None
        )
    except Exception:  # noqa: BLE001 - one bad texture must not stop the group
        return None
