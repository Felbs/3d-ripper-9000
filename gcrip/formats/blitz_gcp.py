"""Blitz Games ``.gcp`` archives (Pac-Man World 3, Bratz, Bad Boys, Cubix, Fairly OddParents,
Frogger: Ancient Shadow, Chicken Little).

``AllPaks.gcp`` is an archive of the per-level packs, addressed in 0x800 sectors::

    u32 hash | u32 data start (0x800) | u32 | u32 member count | u32 entry-table sector |
    u32 x5 | u32 name-table sector | u32 name-table size | ...

The name table is a run of NUL-terminated member names (``spectral_realm_3_sector01.gcp``,
``s_ancient_temple.gcp``, ``resident.gcp``); the entry table holds one 32-byte record per
member, ``u32 sector | u32 hash | u32 size | u32 index | 16 zero bytes``, and the members tile
the file (334 of 337 in Pac-Man World 3 end exactly where the next one starts).

Member packs repeat the header shape with ``data start`` 0x20; some open with Blitz's package
stamp (``01 69 07`` + ``dd/mm/yyyy at hh:mm:ss by <user>``) followed by the type-tagged object
stream (0x00 end, 0x01 u8, 0x03 u16, 0x05 u32, 0x06 f32 little-endian, 0x07 string), which
carries the world / entity tree; the rest of a member is asset data.  ``gcrip.plugins.blitz``
splits an archive into its named members and a member into its stamped packages, so the
structure scanner works on small, named blobs.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

SECTOR = 0x800
STAMP = re.compile(rb"\x01\x69\x07\d\d/\d\d/\d{4} at \d\d:\d\d:\d\d by ")
ENTRY = 32


@dataclass
class Member:
    name: str
    offset: int
    size: int
    hashcode: int


def is_pack(name: str, head: bytes) -> bool:
    if not name.lower().endswith(".gcp") or len(head) < 16:
        return False
    start, zero = struct.unpack_from(">II", head, 4)
    return zero == 0 and start in (0x20, SECTOR)


def is_archive(head: bytes, size: int) -> bool:
    """An archive (rather than a bare pack): data starts at 0x800 and the tables are inside."""
    if len(head) < 0x30:
        return False
    start, _zero, count = struct.unpack_from(">3I", head, 4)
    if start != SECTOR or not 0 < count < 100000:
        return False
    entries, names = (
        struct.unpack_from(">I", head, 0x10)[0],
        struct.unpack_from(">I", head, 0x28)[0],
    )
    return 0 < names * SECTOR < size and 0 < entries * SECTOR < size


def members(data: bytes) -> list[Member]:
    if not is_archive(data[:0x40], len(data)):
        return []
    count = struct.unpack_from(">I", data, 0x0C)[0]
    entries = struct.unpack_from(">I", data, 0x10)[0] * SECTOR
    names_off = struct.unpack_from(">I", data, 0x28)[0] * SECTOR
    names_size = struct.unpack_from(">I", data, 0x2C)[0]
    if entries + count * ENTRY > len(data) or names_off >= len(data):
        return []
    raw = data[names_off : min(names_off + names_size + 0x40, len(data))]
    names = [n.decode("latin-1", "replace") for n in raw.split(b"\0") if n]
    out = []
    for k in range(count):
        sector, hashcode, size, _idx = struct.unpack_from(">4I", data, entries + k * ENTRY)
        off = sector * SECTOR
        if size == 0 or off + size > len(data):
            continue
        name = names[k] if k < len(names) else f"member{k:04d}.gcp"
        out.append(Member(name, off, size, hashcode))
    return out


def packages(data: bytes) -> list[tuple[int, int, str]]:
    """(start, end, author) of the stamped packages in a member pack."""
    starts = [m.start() for m in STAMP.finditer(data) if m.start() % SECTOR == 0]
    out = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(data)
        who = data[s + 3 : s + 51].split(b"\0")[0].rsplit(b" by ", 1)[-1]
        out.append((s, end, who.decode("latin-1", "replace")))
    return out
