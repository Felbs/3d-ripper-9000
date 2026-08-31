"""Visual Concepts ``DAT`` archives - NBA 2K2, NBA 2K3, NFL 2K3, NCAA College Basketball 2K3
and NCAA College Football 2K3 each ship **nine files**, one of which is a 0.8-1.3 GB
``files/game.dat`` holding the entire game.  5.5 GB across the five discs, and nothing opened
it, so all five reported zero models and zero textures.

Big-endian::

    +0   char magic[4]   "DAT\\1" or "DAT\\0"
    +4   u32, u32 16, u32
    +32  u32 entry count             1,968 on NBA 2K3
    +36  the entry table, 24 bytes an entry:
             u32 a counter that falls by about 15 an entry
             u32 name hash
             u32 kind - 0x01000000 on the `.IFF` members
             u32 0
             u32 offset
             u32 size
    ...  12 bytes, then the name list: `count` NUL-terminated names, "PB00.IFF" to "TEAMS.BIN"
    ...  the members, from the next 32-byte boundary after that list

**The table starts at 36, not 32.**  Read from 32 the columns look plausible - a size, a
counter, a hash, a flag, a zero, an offset - and the offsets even increase for a while.  What
gives it away is that each entry's "size" is really the *previous* entry's span: rotate the
record by one field and ``size == next offset - offset`` starts holding on the uncompressed
members.  The word at 32 that looks like the first entry's size is the entry count.

**Offsets are relative to the end of the name list, rounded up to 32**, not to the end of the
table.  Measured from the table, entry 0 lands in the middle of the names.  Two things confirm
the right base: every member then opens with the same twelve bytes, and the spans **tile the
file exactly** - 827,367,176 bytes over 1,968 members on NBA 2K3, to the byte.

A member is stored as it is; the ``kind`` word marks the ones whose payload is packed, and on
NBA 2K3 the 1,916 entries carrying `0x01000000` are exactly the 1,916 names ending in `.IFF`.
That payload is a bit-packed stream nothing standard reads yet (see ``docs/OPEN.md``), so
members come out as stored - which is already what the 52 `.DAT` / `.BIN` / `.CDF` members
need, and gives the rest to the scanner under their real names.

``LINES.BIN`` (336 MB of commentary) and ``PLAYERS.BIN`` (140 MB) are 477 of the 827 MB on
their own and are neither geometry nor texture, so members over ``MAX_MEMBER`` are skipped:
holding them would add half a gigabyte to every worker for nothing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGICS = (b"DAT\x00", b"DAT\x01")
COUNT_AT = 32
TABLE_AT = 36
ENTRY = 24
ALIGN = 32
PACKED = 0x01000000
MAX_ENTRIES = 262144
MAX_NAME = 64
LIST_HEADER = 12  # between the table and the first name
MAX_MEMBER = 32 << 20  # see the module docstring


@dataclass
class Member:
    name: str
    offset: int
    size: int
    packed: bool


def is_dat(head: bytes) -> bool:
    if len(head) < TABLE_AT + ENTRY or head[:4] not in MAGICS:
        return False
    count = struct.unpack_from(">I", head, COUNT_AT)[0]
    return 0 < count <= MAX_ENTRIES


def members(data: bytes) -> list[Member]:
    if not is_dat(data[: TABLE_AT + ENTRY]):
        return []
    count = struct.unpack_from(">I", data, COUNT_AT)[0]
    table_end = TABLE_AT + count * ENTRY
    if table_end + count > len(data):
        return []
    rows = [struct.unpack_from(">6I", data, TABLE_AT + i * ENTRY) for i in range(count)]

    p = table_end + LIST_HEADER
    names: list[str] = []
    while len(names) < count:
        stop = data.find(b"\0", p)
        if stop < 0 or stop - p > MAX_NAME:
            return []
        raw = data[p:stop]
        if not names and (not raw or not all(32 <= c < 127 for c in raw)):
            return []  # the list does not start where it should
        names.append(raw.decode("latin-1", "replace"))
        p = stop + 1
    base = (p + ALIGN - 1) & ~(ALIGN - 1)
    if base >= len(data):
        return []

    out: list[Member] = []
    for i, (_ctr, _hash, kind, zero, offset, _size) in enumerate(rows):
        if zero:
            return []
        end = rows[i + 1][4] if i + 1 < count else len(data) - base
        if not 0 <= offset < end <= len(data) - base:
            return []
        out.append(Member(names[i], base + offset, end - offset, kind == PACKED))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for m in members(data):
        if not m.size or m.size > MAX_MEMBER:
            continue
        name = m.name
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:
            stem, _dot, ext = name.rpartition(".")
            name = f"{stem}_{n:03d}.{ext}" if stem else f"{name}_{n:03d}"
        out.append((name, data[m.offset : m.offset + m.size]))
    return out
