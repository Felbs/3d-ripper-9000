"""Yuke's ``.pac`` / ``.tex`` packs on GameCube (WWE Day of Reckoning 1-2, WrestleMania XIX).

A flat little-endian table::

    u32 entries, u32 flags (0x100), u32 0, u32 table offset (16)
    entry (32)   char name[16], char type[4] ("ymg", "tex", "ycg", "tpl", "meg", ...),
                 u32 bytes, u32 offset, u32 0

``.tex`` packs hold ``tpl`` entries (plain GameCube TPL palettes); ``.pac`` packs hold
``ymg`` (Yuke's ``YOBJ`` models, behind a 16-byte ``DUMY`` stamp on some), ``ycg``, nested
``tex`` and 2D ``meg`` sheets.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAX_ENTRIES = 1 << 16
ENTRY = 32


@dataclass
class Entry:
    name: str
    kind: str
    offset: int
    size: int


def is_pac(head: bytes, size: int) -> bool:
    if len(head) < 48 or size < 48:
        return False
    count, flags, zero, table = struct.unpack_from("<4I", head, 0)
    if not 0 < count <= MAX_ENTRIES or zero or table != 16 or flags & 0xFF:
        return False
    if table + ENTRY * count > size:
        return False
    name = head[16:32]
    kind = head[32:36]
    return (
        name[0] not in (0, 0x20)
        and all(32 <= c < 127 for c in kind.split(b"\0")[0])
        and kind[0] != 0
    )


def entries(data: bytes) -> list[Entry]:
    count, _flags, _zero, table = struct.unpack_from("<4I", data, 0)
    out = []
    for i in range(min(count, MAX_ENTRIES)):
        o = table + ENTRY * i
        if o + ENTRY > len(data):
            break
        name = data[o : o + 16].split(b"\0")[0].decode("latin-1", "replace")
        kind = data[o + 16 : o + 20].split(b"\0")[0].decode("latin-1", "replace")
        size, off = struct.unpack_from("<II", data, o + 20)
        if off + size <= len(data) and size:
            out.append(Entry(name, kind, off, size))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    seen: dict[str, int] = {}
    for e in entries(data):
        stem = e.name or "entry"
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        name = f"{stem}{'' if n == 0 else f'_{n}'}.{e.kind or 'bin'}"
        out.append((name, data[e.offset : e.offset + e.size]))
    return out
