"""Ubisoft Montreal ``.fat`` + ``.000`` archives - Batman: Vengeance (three pairs: ``levels``,
``Dlr``, ``Etf``) and Batman: Rise of Sin Tzu (a pair a level, 37 of them).

``.fat`` (little-endian) is a byte ``01`` then records ending ``u32 time, u32 time, u32 name
length, name\\0`` with ``/gamedata/...`` paths; a directory's name ends in ``/`` and has 16
bytes before the times, a file's 20: ``u16 flags, u16, u32 index, u32 offset, u32 unpacked,
u32 packed``.  The record is found from its tail - the two timestamps (2001-2003) followed by a
length and a ``/`` - because the leading bytes of a directory record are tool memory.

``.000`` holds the files at their offsets as **LZO1X blocks**: ``u32 unpacked (8,192), u32
packed, u32 0xdeadbabe, u8 flag`` then the stream; flag 3 opens a file, flag 1 continues one
**and its matches reach back into the previous blocks' output**
(:func:`gcrip.formats.lzo.decompress` takes that history), flag 0 is a stored block (packed
== unpacked).

Vengeance's members are ``.flt`` "flat files" - a ``mac`` header and a serialised object
stream naming ``^VisualMaterial:`` / ``^GameMaterial:`` and ``.tsd`` textures; Sin Tzu's are
``.tsd`` textures, ``.a3i`` (A3d) models and ``.bin``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.formats import lzo

MAGIC = 0xDEADBABE
BLOCK_HEADER = 13
FLAG_FIRST = 3
FLAG_STORED = 0
HISTORY = 0x20000
MAX_NAME = 512


@dataclass
class Entry:
    name: str
    offset: int
    unpacked: int
    packed: int


def is_fat(head: bytes) -> bool:
    return (
        len(head) >= 32
        and head[:13] == b"\x01\x01\0\0\0\x01\0\0\0\0\0\0\0"
        and head[29:30] == b"/"  # the root directory's path, "/gamedata/" or "/ar..."
    )


def _tail(d: bytes, at: int) -> bool:
    if at + 13 > len(d):
        return False
    t1, t2, ln = struct.unpack_from("<3I", d, at)
    return (
        0x20000000 < t1 < 0x60000000
        and 0x20000000 < t2 < 0x60000000
        and 1 <= ln <= MAX_NAME
        and at + 12 + ln <= len(d)
        and d[at + 12] == ord("/")
    )


def entries(data: bytes) -> list[Entry]:
    out = []
    o = 1
    while o + 32 <= len(data):
        pre = 16 if _tail(data, o + 16) else 20 if _tail(data, o + 20) else None
        if pre is None:
            break
        ln = struct.unpack_from("<I", data, o + pre + 8)[0]
        name = data[o + pre + 12 : o + pre + 12 + ln].split(b"\0")[0].decode("latin-1", "replace")
        if pre == 20 and not name.endswith("/"):
            _flags, _x, _index, offset, unpacked, packed = struct.unpack_from("<HHIIII", data, o)
            out.append(Entry(name, offset, unpacked, packed))
        o += pre + 12 + ln
    return out


def unpack(store: bytes, e: Entry) -> bytes | None:
    """The file's blocks from ``.000``, each continuing the last."""
    out = bytearray()
    o = e.offset
    while len(out) < e.unpacked and o + BLOCK_HEADER <= len(store):
        unpacked, packed, magic, flag = struct.unpack_from("<3IB", store, o)
        if magic != MAGIC or o + BLOCK_HEADER + packed > len(store):
            return None
        src = store[o + BLOCK_HEADER : o + BLOCK_HEADER + packed]
        if flag == FLAG_STORED or packed == unpacked:
            block = src
        else:
            try:
                block = lzo.decompress(src, None, history=bytes(out[-HISTORY:]))
            except lzo.LzoError:
                return None
        out += block[:unpacked]
        o += BLOCK_HEADER + packed
    return bytes(out[: e.unpacked]) if len(out) >= e.unpacked else None
