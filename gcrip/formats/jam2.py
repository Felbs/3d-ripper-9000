"""``JAM2`` archives - Charlie and the Chocolate Factory keeps 244 MB in 38 of them.

A different format from High Voltage's ``LJAM`` (:mod:`gcrip.formats.ljam`) despite the shared
extension, and little-endian::

    +0   char magic[4]   "JAM2"
    +4   f32
    +8   u32 directory size, measured from +32
    +12  char[8]         a compression name - "none", "safe"
    +28  u16 name count | u16 extension count
    +32  char name[8] * name count           "FESPLASH", "DFE000AB", "ROOT", "SHAPES"
    ...  char ext[4]  * extension count       "AFA", "AGM", "GFF", "TPL"
    ...  u32
    ...  the records:  u16 name index, u16 extension index, u32 member offset

A member's own size is not in the record.  It is at the member, in a **32-byte header that
writes the size twice** and is otherwise zero::

    u32 size, u32 size again, 24 zero bytes, then the payload

That repetition is what makes the format check itself: a record pointing at the wrong place
almost never lands on two equal words, so the junk records in the table are rejected and the
real ones tile the file.  The 24 bytes after the two sizes are **not** always zero - they are
on the archives tagged ``safe`` and carry flags on the ones tagged ``none`` - so checking them
throws away every member of the big level archives, which is 234 of the disc's 245 MB.

The record table starts **four bytes after the extension table**, not at it.  With those four
bytes counted as part of a record every field is off by half a record, which still parses - the
offsets still validate and the members still tile - but the names come out shifted: 37 of the
38 entries labelled `TPL` then land on a `TPL` and one does not.  Reading the pairing off a
single mismatch is the only signal there is, so it is worth stating: **name and extension come
before the offset, and 38 of 38 `TPL` records then land on the `TPL` magic.**
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"JAM2"
COUNTS_AT = 28
NAMES_AT = 32
NAME = 8
EXT = 4
RECORD = 8
GAP = 4  # between the extension table and the records
MEMBER_HEADER = 32
MAX_NAMES = 65535


@dataclass
class Member:
    name: str
    offset: int
    size: int


def is_jam2(head: bytes) -> bool:
    return len(head) >= 32 and head[:4] == MAGIC


def members(data: bytes) -> list[Member]:
    if not is_jam2(data[:32]):
        return []
    names_n, exts_n = struct.unpack_from("<2H", data, COUNTS_AT)
    if not names_n or names_n > MAX_NAMES:
        return []
    exts_at = NAMES_AT + names_n * NAME
    records_at = exts_at + exts_n * EXT + GAP
    end = min(NAMES_AT + struct.unpack_from("<I", data, 8)[0], len(data))
    if records_at > end:
        return []

    def text(at: int, width: int) -> str:
        return data[at : at + width].split(b"\0")[0].decode("latin-1", "replace")

    names = [text(NAMES_AT + i * NAME, NAME) for i in range(names_n)]
    exts = [text(exts_at + i * EXT, EXT) for i in range(exts_n)]

    out: list[Member] = []
    for p in range(records_at, end - RECORD + 1, RECORD):
        name_i, ext_i, at = struct.unpack_from("<2HI", data, p)
        if name_i >= names_n or ext_i >= exts_n or at + MEMBER_HEADER > len(data):
            continue
        size, again = struct.unpack_from("<2I", data, at)
        if size != again or not size or at + MEMBER_HEADER + size > len(data):
            continue
        name = names[name_i]
        out.append(
            Member(f"{name}.{exts[ext_i]}" if exts[ext_i] else name, at + MEMBER_HEADER, size)
        )
    return out


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
