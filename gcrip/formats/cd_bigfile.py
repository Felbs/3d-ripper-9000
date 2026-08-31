"""Crystal Dynamics ``bigfile.dat`` - Tomb Raider: Legend keeps the whole game in one,
1,353,598,976 bytes beside only ``bi2.bin`` and ``fst.bin``.

Big-endian::

    +0              u32 count
    +4              u32 hash[count]      sorted, so the game can binary-search a name
    +4 + count*4    record[count], 16 bytes each:
                        u32 unpacked size
                        u32 offset, in 2048-byte sectors
                        u32 0xffffffff
                        u32

There are **no names** - only the hashes - so members come out named by their hash.

Three pieces of arithmetic identify the fields, none of which needs a name table:

* the hash array is **strictly ascending across all 4,314 entries** and spans 767,790 to
  4,292,209,041, which is what a sorted 32-bit hash table looks like and what nothing else
  does;
* every record's third word is ``0xffffffff`` - all 4,314 of them, exactly 16 bytes apart -
  which is what fixes the stride;
* the offset field is the only one that fits: times 2048 its maximum is 1,353,596,928 against
  a file of 1,353,598,976, so the last member ends on the archive's last sector.  Read as
  bytes, or with either of the other two fields as the offset, it does not reach halfway.

A member is a zlib stream when it starts ``78 9c`` and stored otherwise.  **The unpacked size
confirms the whole reading**: on the first 120 records, 42 carry zlib and all 42 inflate to
exactly the size the record declares.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

SECTOR = 2048
ENTRY = 16
SENTINEL = 0xFFFFFFFF
ZLIB = b"\x78\x9c"
MIN_COUNT = 8
MAX_COUNT = 1 << 18
PROBE = 12


@dataclass
class Member:
    name: str
    offset: int
    unpacked: int


def _count(head: bytes) -> int | None:
    if len(head) < 8:
        return None
    count = struct.unpack_from(">I", head, 0)[0]
    return count if MIN_COUNT <= count <= MAX_COUNT else None


def is_bigfile(head: bytes) -> bool:
    """The 64 bytes ``classify`` sniffs hold the count and the first fifteen hashes, which is
    enough: they have to ascend."""
    count = _count(head)
    if count is None:
        return False
    # never probe past the hash array itself - beyond it the record fields do not ascend
    n = min(PROBE, count, (len(head) - 4) // 4)
    if n < 4:
        return False
    hashes = struct.unpack_from(f">{n}I", head, 4)
    return all(hashes[i] < hashes[i + 1] for i in range(n - 1))


def members(data: bytes) -> list[Member]:
    count = _count(data[:8])
    if count is None:
        return []
    table = 4 + count * 4
    if table + count * ENTRY > len(data):
        return []
    hashes = struct.unpack_from(f">{count}I", data, 4)
    if any(hashes[i] >= hashes[i + 1] for i in range(count - 1)):
        return []
    out = []
    for i in range(count):
        unpacked, sector, sentinel, _extra = struct.unpack_from(">4I", data, table + i * ENTRY)
        if sentinel != SENTINEL:
            return []
        at = sector * SECTOR
        if at >= len(data) or not unpacked:
            continue
        out.append(Member(f"{hashes[i]:08x}", at, unpacked))
    return out


def read(data: bytes, member: Member) -> bytes | None:
    """The member's bytes, inflated when it is a zlib stream.  ``None`` when the payload does
    not come out at the size the record declares, so a truncated read is never passed on."""
    blob = data[member.offset : member.offset + member.unpacked + SECTOR]
    if blob[:2] == ZLIB:
        try:
            got = zlib.decompressobj().decompress(blob)
        except zlib.error:
            return None
        return got if len(got) == member.unpacked else None
    got = data[member.offset : member.offset + member.unpacked]
    return got if len(got) == member.unpacked else None
