"""``KCEO ARCDT`` archives - Konami Computer Entertainment Osaka, on Evolution Snowboarding.

Cluster 2's remaining disc.  Its 29 ``.arc`` hold everything the game draws; the rest of the
disc is 48 ``.h4m`` movies and a 163 MB audio stream.

Big-endian, and about as friendly as an archive gets::

    +0   char magic[16]   "KCEO ARCDT 1.0B"
    +16  u32  count
    +20  u32  alignment   0x800 on every sample - also where the directory starts
    +24  u32  directory bytes, always count * 36
    +28  '-' padding up to the alignment
    +0x800  the entries, 36 bytes each:
                char name[24]   NUL-padded, "FL_STG13_MS_00.BPX"
                u32  sector     the member's offset in `alignment` units
                u32  size
                u32  zero

**Two identities check it and both hold on every sample**: the declared directory size is
exactly ``count * 36``, and every member's ``sector * alignment + size`` lands inside the file.
Measured over four archives - 1, 5, 75 and 74 entries - **all 155 fit and all 155 are named**.

The gaps between members run from 64 to 2,048 bytes, so members are sector-padded but not
tightly packed: a walk that insists each member begins exactly where the last one ended is too
strict and fails on the two large archives.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"KCEO ARCDT"
HEADER = 28
ENTRY = 36
NAME = 24
MAX_COUNT = 1 << 16


@dataclass
class Member:
    name: str
    offset: int
    size: int


def is_kceo_arc(head: bytes) -> bool:
    return head[: len(MAGIC)] == MAGIC


def members(data: bytes) -> list[Member]:
    if len(data) < HEADER or not is_kceo_arc(data[:16]):
        return []
    count, align, dirsize = struct.unpack_from(">3I", data, 16)
    if not 0 < count <= MAX_COUNT or align == 0 or align & (align - 1):
        return []
    # the directory is exactly one record a member; anything else is not this format
    if dirsize != count * ENTRY or align + dirsize > len(data):
        return []
    out = []
    for i in range(count):
        at = align + i * ENTRY
        raw = data[at : at + NAME].split(b"\0", 1)[0]
        sector, size, tail = struct.unpack_from(">3I", data, at + NAME)
        offset = sector * align
        if tail or size == 0 or offset + size > len(data):
            continue
        name = raw.decode("latin-1", "replace") or f"member{i:04d}.bin"
        out.append(Member(name, offset, size))
    return out
