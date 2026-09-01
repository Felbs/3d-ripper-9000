"""``FSYS`` archives - Pokemon Colosseum and Pokemon XD: Gale of Darkness.

Two discs whose content is almost entirely inside these: **1,852 archives and 350 MB** on
Colosseum, **2,540 and 1,032 MB** on XD.  Both reported nothing at all, because nothing opened
an ``.fsys``.

Big-endian::

    +0    char magic[4]   "FSYS"
    +4    u32 version     0x102 (Colosseum) / 0x201 (XD)
    +8    u32 identifier
    +12   u32 entry count
    +16   u32 flags
    +20   u32 3           how many pointers the table at +24 holds
    +24   u32 -> a three-pointer table
    +32   u32 file length

The three pointers are, in order, the **list of per-entry detail pointers**, the start of the
detail records, and the start of the data.  Two independent sums confirm that reading, on both
versions at once: Colosseum's 157 entries need `96 + 157 * 4 = 724` bytes of pointer list, and
the second pointer is **736** - the same number rounded up to 32.  XD's two entries need
`96 + 8 = 104`, and its second pointer is **112**.  The third pointer equals the first entry's
data offset, and ``+32`` equals the file length exactly (18,069,472 and 131,180,768).

A detail record - 80 bytes on Colosseum, 112 on XD, so the stride is taken from the pointer
list rather than assumed::

    +0    u32 identifier
    +4    u32 data offset
    +8    u32 **unpacked** size
    +20   u32 **stored** size
    +32   u32 kind
    +36   u32 -> the member's name, NUL-terminated

**+8 is the unpacked size and +20 the stored one, not the other way round.**  On an
uncompressed member the two are equal, so the mistake is invisible on exactly the archive you
would check first - ``people_archive.fsys``, where both read 61,743.  It shows up only on a
compressed one, as a "size" larger than the archive containing it.

**Members are named**, which is the point of opening these at all: ``people_archive.fsys``
holds ``sensei_b1``, ``hunter_f_b2``, ``warugaki_b3``, ``jiji_b_b1`` - the game's cast, one
entry each.

A member is stored one of two ways, and the first four bytes say which: an uncompressed member
repeats its own stored size there, and a compressed one begins ``LZSS`` followed by the
unpacked and stored sizes again.  Anything else is refused, so a mis-read table cannot carve
the archive up at invented offsets.

**Almost everything is compressed**, which is the honest limit on this reader: across the 40
largest archives of each disc, Colosseum has 157 stored members (17 MB) against 2,257 ``LZSS``
(143 MB), and XD has none stored at all.  The container is solved; the codec is the gate.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"FSYS"
COUNT_AT = 12
POINTERS_AT = 24
LENGTH_AT = 32
POINTERS = 3
OFFSET_AT = 4
UNPACKED_AT = 8
SIZE_AT = 20
LZSS = b"LZSS"
LZSS_HEADER = 16
KIND_AT = 32
NAME_AT = 36
MIN_DETAIL = 40
MAX_COUNT = 1 << 16
MAX_NAME = 64


@dataclass
class Member:
    name: str
    kind: int
    offset: int
    size: int
    unpacked: int
    compressed: bool


def is_fsys(head: bytes) -> bool:
    return head[:4] == MAGIC


def _cstr(data: bytes, at: int) -> str:
    end = data.find(b"\x00", at, at + MAX_NAME)
    if end < 0:
        return ""
    return data[at:end].decode("latin-1", "replace")


def members(data: bytes) -> list[Member]:
    if not is_fsys(data[:4]) or len(data) < LENGTH_AT + 4:
        return []
    count = struct.unpack_from(">I", data, COUNT_AT)[0]
    table = struct.unpack_from(">I", data, POINTERS_AT)[0]
    if not (0 < count <= MAX_COUNT) or table + POINTERS * 4 > len(data):
        return []
    pointers = struct.unpack_from(f">{POINTERS}I", data, table)
    if pointers[0] + count * 4 > len(data):
        return []
    details = struct.unpack_from(f">{count}I", data, pointers[0])
    out: list[Member] = []
    for at in details:
        if at + MIN_DETAIL > len(data):
            continue
        offset = struct.unpack_from(">I", data, at + OFFSET_AT)[0]
        unpacked = struct.unpack_from(">I", data, at + UNPACKED_AT)[0]
        size = struct.unpack_from(">I", data, at + SIZE_AT)[0]
        kind = struct.unpack_from(">I", data, at + KIND_AT)[0]
        name_at = struct.unpack_from(">I", data, at + NAME_AT)[0]
        if size == 0 or offset + 4 > len(data) or offset + size > len(data):
            continue
        head = data[offset : offset + 4]
        if head == LZSS:
            compressed = True
        elif struct.unpack_from(">I", data, offset)[0] == size:
            compressed = False
        else:
            continue  # neither shape: the table was read wrong, so claim nothing
        out.append(
            Member(
                _cstr(data, name_at) or f"member{len(out):04d}",
                kind,
                offset,
                size,
                unpacked,
                compressed,
            )
        )
    return out
