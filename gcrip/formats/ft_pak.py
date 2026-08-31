"""FutureTactics: The Uprising keeps its whole game in one 143 MB ``files.pak``, and the disc
produced nothing because the archive has **no magic** - it opens with a count and then goes
straight into names.

Little-endian::

    +0   u32 entry count            5,458
    +4   the table, 56 bytes an entry:
             char name[48]          "FRONTEND\\ALIENGICON(1).PNG", backslash separated
             u32 offset
             u32 size
    ...  the members, from the end of the table

Having no magic, it is recognised by arithmetic that fits in the 64 bytes a plugin's
``is_container`` is given: the **first entry's offset is the end of the table**, so
``u32 at 52 == 4 + count * 56`` has to hold, and on this archive it does exactly (305,652).
That is a far stronger check than a name test, and it costs nothing.

**Bit 31 of the size is a flag.**  3,055 of the 5,458 entries have it set, and reading the word
as a plain size puts those members two gigabytes past the end of a 143 MB file - which looks
like a broken table rather than a flag, and cost a first pass 56% of the archive.  Masked to
its low 31 bits every entry lands inside the file, the members tile with gaps of nought to
three bytes, and none overlaps.

What comes out is worth the trouble: 1,207 RenderWare `.DFF` models, 1,052 `.DDS`, 818 `.AN2`,
797 `.ANM`, 708 `.BMP`, 637 `.PNG`, and gcrip already reads four of those.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

COUNT_AT = 0
TABLE_AT = 4
ENTRY = 56
NAME = 48
SIZE_MASK = 0x7FFFFFFF
MAX_ENTRIES = 262144


@dataclass
class Member:
    name: str
    offset: int
    size: int
    flagged: bool


def is_ft_pak(head: bytes) -> bool:
    """The table's own arithmetic, inside the 64 bytes ``is_container`` gets."""
    if len(head) < TABLE_AT + ENTRY:
        return False
    count = struct.unpack_from("<I", head, COUNT_AT)[0]
    if not 0 < count <= MAX_ENTRIES:
        return False
    first = struct.unpack_from("<I", head, TABLE_AT + NAME)[0]
    return first == TABLE_AT + count * ENTRY


def members(data: bytes) -> list[Member]:
    if not is_ft_pak(data[: TABLE_AT + ENTRY]):
        return []
    count = struct.unpack_from("<I", data, COUNT_AT)[0]
    if TABLE_AT + count * ENTRY > len(data):
        return []
    out: list[Member] = []
    for i in range(count):
        p = TABLE_AT + i * ENTRY
        raw = data[p : p + NAME].split(b"\0")[0]
        offset, word = struct.unpack_from("<2I", data, p + NAME)
        size = word & SIZE_MASK
        if not raw or not size or offset + size > len(data):
            continue
        name = raw.decode("latin-1", "replace").replace("\\", "/")
        out.append(Member(name, offset, size, bool(word >> 31)))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for m in members(data):
        name = m.name.lstrip("/").replace("/", "__")
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:
            stem, _dot, ext = name.rpartition(".")
            name = f"{stem}_{n:03d}.{ext}" if stem else f"{name}_{n:03d}"
        out.append((name, data[m.offset : m.offset + m.size]))
    return out
