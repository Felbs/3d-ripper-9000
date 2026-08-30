"""Darkened Skye ``PAK`` archives - 16 of them, holding 255 ``.SKX`` models.

    +0   char magic[4]   "PAK\\0"
    +4   u32 version     1
    +8   u32 name table size
    +12  the name table: NUL-terminated names, "COIN.SKX", "DRAAK.SKX", "FRUITCEKE.SKX"
    ...  entry table, 44 bytes a record, little-endian:
             u32 name offset (into the name table)
             u32, u32
             u32 data offset
             u32 size
             ...

The entry table does **not** start immediately after the name table - there is padding whose
length varies - so rather than guess it the reader scans forward for the first position where
the records **tile**: each member's offset plus its size equals the next member's offset.  That
is the same self-check the rest of these archives allow, and it settles the table position
exactly.

All 16 archives parse this way, giving 255 members that all tile, every one a ``.SKX`` whose
first four bytes are ``00 58 4b 53`` - ``SKX`` byte-swapped.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"PAK\0"
NAMES_AT = 12
ENTRY = 44
SEARCH = 128  # how far past the name table the entry table may begin
MAX_MEMBERS = 65536


@dataclass
class Member:
    name: str
    offset: int
    size: int


def is_pak(head: bytes) -> bool:
    return len(head) >= NAMES_AT and head[:4] == MAGIC


def _walk(data: bytes, table: int, name_table: int) -> list[Member]:
    out: list[Member] = []
    p = table
    while p + ENTRY <= len(data) and len(out) < MAX_MEMBERS:
        name_off, _b, _c, offset, size = struct.unpack_from("<5I", data, p)
        if name_off >= name_table or size == 0 or offset == 0 or offset + size > len(data):
            break
        if out and out[-1].offset + out[-1].size != offset:  # members tile
            break
        stop = data.find(b"\0", NAMES_AT + name_off)
        name = data[NAMES_AT + name_off : stop if stop >= 0 else None].decode("latin-1", "replace")
        if not name:
            break
        out.append(Member(name, offset, size))
        p += ENTRY
    return out


def members(data: bytes) -> list[Member]:
    if not is_pak(data[:NAMES_AT]):
        return []
    name_table = struct.unpack_from("<I", data, 8)[0]
    if not 0 < name_table < len(data):
        return []
    best: list[Member] = []
    for table in range(NAMES_AT + name_table, min(NAMES_AT + name_table + SEARCH, len(data)), 4):
        got = _walk(data, table, name_table)
        if len(got) > len(best):
            best = got
    return best


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for m in members(data):
        name = m.name
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:
            stem, _dot, ext = name.rpartition(".")
            name = f"{stem}_{n:03d}.{ext}" if stem else f"{name}_{n:03d}"
        out.append((name, data[m.offset : m.offset + m.size]))
    return out
