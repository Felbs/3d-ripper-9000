"""Visual Concepts ``RTXT`` texture records - the ``.IFF`` members of ``game.dat``.

NBA 2K2/2K3, NFL 2K3 and the two NCAA 2K3 discs keep everything in one ``game.dat``
(:mod:`gcrip.formats.vc_dat`).  Most of its ``.IFF`` members are packed with a codec that is
not solved yet, but **58 of NBA 2K3's 1,916 are stored as they are** - ``size == span`` in the
table - and four of those are large: ``PLAYERS.IFF`` (10.2 MB), ``LOADM.IFF`` (4.5 MB),
``CHWG.IFF`` (3.5 MB) and ``AOSTREET.IFF`` (1.2 MB).  Those are texture banks, and they need no
codec at all.

A member is a run of fixed records, each one image.  Big-endian::

    +0    16 bytes, copied from the member's own header
    +16   char tag[4]      "RTXT" - reversed, so the tag is TXTR
    +20   u32 size         the record's length less 16
    +24   u32 size         again
    +28   u32 0, then 12 zero bytes
    +44   char tag[4]      "RTXT" again, then two more sizes
    +64   char name[]      NUL-terminated, padded to 4 - "HEAD0000", "logo030", "0369"
    ...   12 bytes
    ...   u32 width, u32 height
    +176  width * height bytes of 8-bit palette indices, **row-major, not GX-tiled**
    ...   512 bytes: 256 palette entries, RGB565 big-endian

``176 + width * height + 512 == record size`` is the check, and it is what makes the reader
safe: a record whose header does not reconcile with its own length is skipped rather than
guessed at.  It holds on 72 records of ``AOSTREET``, 600 of ``PLAYERS`` and 53 of ``CHWG``
(256x256 there), and fails on ``LOADM``, whose 102 records are laid out differently and are
therefore declined.

**The indices are not tiled.**  Reading them row-major is measurably smoother than
de-swizzling them as GX ``C8`` - 1.4x on every record tried - which is the opposite of what
every other GameCube texture in this project does, so it is worth stating plainly.  The palette
is ``RGB565`` big-endian: decoding with it gives an image about twice as smooth as either
``IA8`` or ``RGB5A3``, and those two invent an alpha channel the format does not have.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

MAGIC = b"RTXT"
TAG_AT = 16
SIZE_AT = 20
NAME_AT = 64
DIMS_GAP = 12
PIXELS_AT = 176
PALETTE_ENTRIES = 256
PALETTE_BYTES = PALETTE_ENTRIES * 2
PALETTE_FORMAT = 1  # RGB565
HEADER = 16
MAX_NAME = 32
MAX_DIM = 4096
MAX_RECORDS = 4096


@dataclass
class Texture:
    name: str
    width: int
    height: int
    pixels: bytes
    palette: bytes


def is_rtxt(head: bytes) -> bool:
    """The tag sits at +16, inside the 64 bytes ``classify`` sniffs."""
    return len(head) >= TAG_AT + 4 and head[TAG_AT : TAG_AT + 4] == MAGIC


def _record(rec: bytes) -> Texture | None:
    if len(rec) < PIXELS_AT + PALETTE_BYTES or rec[TAG_AT : TAG_AT + 4] != MAGIC:
        return None
    raw = rec[NAME_AT : NAME_AT + MAX_NAME].split(b"\0", 1)[0]
    if not raw or any(c < 32 or c >= 127 for c in raw):
        return None
    name = raw.decode("latin-1")
    at = NAME_AT + (len(name) + 4) // 4 * 4 + DIMS_GAP
    if at + 8 > len(rec):
        return None
    width, height = struct.unpack_from(">2I", rec, at)
    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None
    # The record states its own length; a header that does not reconcile with it is a
    # header read at the wrong place, not a texture to guess at.
    if PIXELS_AT + width * height + PALETTE_BYTES != len(rec):
        return None
    pixels = rec[PIXELS_AT : PIXELS_AT + width * height]
    palette = rec[PIXELS_AT + width * height :]
    return Texture(name, width, height, pixels, palette)


def textures(data: bytes) -> list[Texture]:
    """Every record whose header reconciles with its own declared length."""
    if not is_rtxt(data[: TAG_AT + 4]):
        return []
    out: list[Texture] = []
    at = 0
    while at + PIXELS_AT <= len(data) and len(out) < MAX_RECORDS:
        if data[at + TAG_AT : at + TAG_AT + 4] != MAGIC:
            break
        span = struct.unpack_from(">I", data, at + SIZE_AT)[0] + HEADER
        if span <= HEADER or at + span > len(data):
            break
        got = _record(data[at : at + span])
        if got is not None:
            out.append(got)
        at += span
    return out


def decode(tex: Texture) -> np.ndarray:
    """RGBA8, (H, W, 4).  The indices are row-major, so no de-swizzling happens here."""
    palette = gx.decode_palette(PALETTE_FORMAT, tex.palette, PALETTE_ENTRIES)
    idx = np.frombuffer(tex.pixels, dtype=np.uint8).reshape(tex.height, tex.width)
    return palette[idx].astype(np.uint8)
