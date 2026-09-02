"""``MULA`` texture archives and their ``GCT `` images - Cabela's, inside ``Data/data.arc``.

Cluster 2's last three discs.  ``docs/OPEN.md`` had them down as a dead end: *"gxscan finds
nothing in an inflated block and none of gcrip's magics appear, so it would cost ~600 MB of
inflation per disc for no output"*.  That was measured on **the first block only**, and
``data.arc`` is not homogeneous - it is a chain of raw zlib streams at 0x800-aligned offsets
whose contents differ completely along its 307 MB.  The first blocks are navigation data
stamped ``PathGen 3.2``; the middle holds Lua (``LoadScript("Sound\\stdsound.snd")``); and the
tail is ``MULA``, a named texture archive.  Sampling one block and generalising is what made
the disc look empty.

## The archive

Little-endian::

    +0    char magic[4]      "MULA"
    +4    u32  count
    +8    count x { u32 size; u32 name_offset }
    then  u32  string table bytes
    then  the NUL-terminated names, `name_offset` counted from here
    then  the payloads, in entry order, `size` bytes each

**The identity that checks it**: the payloads tile the rest of the block exactly.  On the two
blocks small enough to inflate whole, ``data_start + sum(size)`` comes to 412,520 and 147,312 -
their inflated lengths, to the byte - with 192 of 192 and 90 of 90 names decoding as ordinary
paths (``TEXTURES\\LEVELS\\COLORMAP\\MAP7\\MAP7A_GRD_01_X1.GCT``).

## The images

Each payload holds one image, big-endian::

    +0    char magic[4]      "GCT "   (the payload pads it to 0 or 2 - see `gct_at`)
    +4    u16  width
    +6    u16  height
    +8    u16  GX texture format
    +12   u8   mip levels
    +16   u32  pixel bytes
    +28   the palette, if the format has one, then the pixels

with a 32-byte header counted from the start of the payload rather than from the magic.

**And the identity that checks that**: ``32 + palette + pixel bytes == the entry's size``, on
**200 of 200** textures.  It also settles the palette sizes rather than assuming them - the
first 136 matched with a 512-byte palette and 64 did not, every one of those format 8 and every
one short by exactly 480, which is 512 - 32: format 8 is ``C4`` with 16 entries, format 9 is
``C8`` with 256.  Formats seen are 9 (126), 8 (64) and 14 (CMPR, 10).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"MULA"
GCT = b"GCT "
HEADER = 8
ENTRY = 8
GCT_HEADER = 32
MAX_COUNT = 1 << 16
#: bytes of palette by GX format: C4 holds 16 entries, C8 and C14X2 hold 256, at 2 bytes each
PALETTE_BYTES = {8: 32, 9: 512, 10: 512}


@dataclass
class Member:
    name: str
    offset: int
    size: int


@dataclass
class Texture:
    name: str
    width: int
    height: int
    fmt: int
    levels: int
    palette: bytes
    pixels: bytes


def is_mula(head: bytes) -> bool:
    return head[:4] == MAGIC


def members(data: bytes) -> list[Member]:
    """Every member, or ``[]`` if the payloads do not tile the block."""
    if len(data) < HEADER or not is_mula(data[:4]):
        return []
    count = struct.unpack_from("<I", data, 4)[0]
    if not 0 < count <= MAX_COUNT:
        return []
    table_end = HEADER + count * ENTRY
    if table_end + 4 > len(data):
        return []
    entries = [struct.unpack_from("<2I", data, HEADER + i * ENTRY) for i in range(count)]
    str_bytes = struct.unpack_from("<I", data, table_end)[0]
    base = table_end + 4
    start = base + str_bytes
    if start > len(data) or str_bytes > len(data):
        return []
    # the payloads run to the end of the block; a count or string table read wrong overshoots
    if start + sum(size for size, _ in entries) > len(data):
        return []
    out: list[Member] = []
    at = start
    for i, (size, name_off) in enumerate(entries):
        p = base + name_off
        end = data.find(b"\0", p, start)
        name = data[p:end].decode("latin-1", "replace") if 0 <= p < start and end > p else ""
        out.append(Member(name or f"member{i:04d}", at, size))
        at += size
    return out


def gct_at(blob: bytes) -> int | None:
    """Where the ``GCT `` magic starts, or ``None``.

    It is at 0 in some archives and at 2 in others - the payloads are padded to an alignment
    the entry size does not record - so the header is located rather than assumed.
    """
    for at in (0, 2):
        if blob[at : at + 4] == GCT:
            return at
    return None


def is_gct(blob: bytes) -> bool:
    return gct_at(blob) is not None


def texture(blob: bytes, name: str = "") -> Texture | None:
    """The image in one member, or ``None`` when the sizes do not reconcile."""
    pad = gct_at(blob) if len(blob) >= GCT_HEADER else None
    if pad is None:
        return None
    width, height, fmt = struct.unpack_from(">3H", blob, pad + 4)
    levels = blob[pad + 12]
    pixel_bytes = struct.unpack_from(">I", blob, pad + 16)[0]
    if not (0 < width <= 4096 and 0 < height <= 4096):
        return None
    pal = PALETTE_BYTES.get(fmt, 0)
    if pad + GCT_HEADER + pal + pixel_bytes != len(blob):
        return None
    palette = blob[pad + GCT_HEADER : pad + GCT_HEADER + pal]
    pixels = blob[pad + GCT_HEADER + pal :]
    return Texture(name or "gct", width, height, fmt, levels, palette, pixels)
