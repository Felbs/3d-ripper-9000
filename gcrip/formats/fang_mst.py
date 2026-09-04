"""Midway's Fang engine ``.mst`` archives (Freaky Flyers - ``pFang Game`` in the DOL).

**Little-endian** header ``"FANG", u8[4] version (0.7.1.24), u32 file size, u32 entries,
u32, u32, u32, u32, u32 6, 6, 6`` and, at 0x6c, 48-byte entries ``char[32] name, u32 offset,
u32 packed bytes, u32 timestamp, u32 unpacked bytes + 32``.  Every member is one **LZO1X**
stream (the first byte is a 17+ literal-run opcode straight into the member's class name,
``CGfPlayerDef``), decoded by :mod:`gcrip.formats.lzo`; the unpacked count carries 32 bytes
of slack the stream does not fill.  Members: ``.gcp`` particles, ``.gtx`` textures, ``.gob``
game objects, ``.gmo`` models, ``.gcw`` / ``.gmw`` collision and mesh worlds, ``.gst``
strings - their contents are **big-endian**.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.formats import lzo

MAGIC = b"FANG"
ENTRIES_AT = 0x6C
ENTRY = 48
NAME = 32
SLACK = 32
MAX_ENTRIES = 65536


@dataclass
class Entry:
    name: str
    offset: int
    packed: int
    unpacked: int


def is_mst(head: bytes, size: int = 0) -> bool:
    if head[:4] != MAGIC or len(head) < 16:
        return False
    total, entries = struct.unpack_from("<2I", head, 8)
    return 0 < entries <= MAX_ENTRIES and (size == 0 or total == size)


def entries(data: bytes) -> list[Entry]:
    if not is_mst(data[:16], len(data)):
        return []
    count = struct.unpack_from("<I", data, 12)[0]
    out = []
    for k in range(count):
        e = ENTRIES_AT + ENTRY * k
        if e + ENTRY > len(data):
            break
        name = data[e : e + NAME].split(b"\0")[0].decode("latin-1", "replace")
        offset, packed, _stamp, unpacked = struct.unpack_from("<4I", data, e + NAME)
        if not name or offset + packed > len(data):
            continue
        out.append(Entry(name, offset, packed, max(0, unpacked - SLACK)))
    return out


def member(data: bytes, e: Entry) -> bytes | None:
    try:
        blob = lzo.decompress(data[e.offset : e.offset + e.packed], e.unpacked + SLACK)
    except lzo.LzoError:
        return None
    return blob if blob else None
