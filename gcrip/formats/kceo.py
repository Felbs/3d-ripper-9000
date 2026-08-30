"""Konami ``KCEO ARCDT`` archives (Evolution Snowboarding, 29 ``.arc``).

The file says what it is in the first sixteen bytes - ``KCEO ARCDT 1.0B`` - and the rest is
plain::

    +0   char magic[16]   "KCEO ARCDT 1.0B\\0"
    +16  u32 member count
    +20  u32 table offset  (0x800)
    +24  u32
    +28  filler, '-' repeated up to the table

    table, 36 bytes a record:
        char name[20]     NUL-padded, e.g. "FL_STG21_00.BPX"
        u32               0
        u32 sector        of the member, in 0x800 sectors
        u32 size
        u32               0

Everything is big-endian.  The members tile the file: record 0 sits at sector 2 and is 172,416
bytes, which ends inside sector 86, and record 1 starts at sector 87; record 1 is 178,176 bytes
and record 2 starts where that lands.  That tiling is the check that the layout is right.

Members are Konami ``.BPX`` files, whose own format is a separate problem - splitting the
archive hands them to the rest of the pipeline under their real names.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"KCEO ARCDT"
HEADER = 16
ENTRY = 36
NAME = 20
SECTOR = 0x800
MAX_MEMBERS = 65536


@dataclass
class Member:
    name: str
    offset: int
    size: int


def is_kceo(head: bytes) -> bool:
    return len(head) >= 24 and head[: len(MAGIC)] == MAGIC


def members(data: bytes) -> list[Member]:
    if not is_kceo(data[:24]):
        return []
    count, table = struct.unpack_from(">2I", data, HEADER)
    if not 0 < count <= MAX_MEMBERS or not HEADER <= table < len(data):
        return []
    out: list[Member] = []
    for i in range(count):
        p = table + i * ENTRY
        if p + ENTRY > len(data):
            break
        name = data[p : p + NAME].split(b"\0")[0].decode("latin-1", "replace")
        _zero, sector, size, _z2 = struct.unpack_from(">4I", data, p + NAME)
        offset = sector * SECTOR
        if not name or size == 0 or offset + size > len(data):
            continue
        out.append(Member(name, offset, size))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return [(m.name, data[m.offset : m.offset + m.size]) for m in members(data)]
