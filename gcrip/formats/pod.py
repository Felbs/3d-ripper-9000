"""Terminal Reality ``POD`` archives (BloodRayne, Blowout, RoadKill - ``POD3``; 4x4 Evo 2 -
``POD2``).

Little-endian throughout.  Both versions share the header up to the file count and the 20-byte
index entry; they differ only in where the index lives::

    char  magic[4]      "POD2" / "POD3"
    u32   checksum
    char  comment[80]           e.g. "Localized, platform-independent files"
    u32   file count            0x58
    ...

``POD2`` puts the index inline at 0x60, the name table straight after it, and the file data
after that.  ``POD3`` grows the header to 0x120 (author and copyright strings) and moves the
index to the END of the file, at the offset stored at 0x108 - a value that is not aligned and
cannot be derived from the file size, which is what made the format look undocumented::

    u32   index offset          0x108   (POD3 only)
    u32   index checksum        0x10c
    u32   name table size       0x110

Index entries are ``u32 path offset | u32 size | u32 offset | u32 timestamp | u32 checksum``,
with the path offset relative to the name table that follows the index.  Names are
NUL-terminated and share suffixes - a shorter name may point into the tail of a longer one - so
they must be read as pointers, never walked in sequence.  File data is contiguous: entry
offsets tile exactly (verified 1241/1241 on 4x4 Evo 2's TRUCK.pod, 21/21 on Blowout's
LANGUAGE.POD).

After the POD3 name table comes the audit trail - one record per edit, holding the developer's
user name, a timestamp and the path - which carries no file data and is ignored.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGICS = (b"POD2", b"POD3")
POD2_INDEX = 0x60
POD3_HEADER = 0x120
ENTRY = 20
MAX_FILES = 200000


@dataclass
class Entry:
    name: str
    offset: int
    size: int
    timestamp: int


def is_pod(head: bytes) -> bool:
    """True for a POD header.

    Deliberately checks the magic alone: a container plugin is offered only the first
    ``gcrip.classify.SNIFF_BYTES`` (64) bytes of a file, which is not enough to reach the file
    count at 0x58 or the POD3 index offset at 0x108.  The directory is validated in full by
    :func:`entries`, which is given the whole archive.
    """
    return len(head) >= 4 and head[:4] in MAGICS


def version(head: bytes) -> int:
    """2 or 3 for a POD header, 0 if this is not one."""
    if len(head) < 0x60 or head[:4] not in MAGICS:
        return 0
    count = struct.unpack_from("<I", head, 0x58)[0]
    if not 0 < count <= MAX_FILES:
        return 0
    if head[:4] == b"POD2":
        return 2
    if len(head) < POD3_HEADER:
        return 0
    return 3 if struct.unpack_from("<I", head, 0x108)[0] >= POD3_HEADER else 0


def _index(data: bytes, ver: int) -> int:
    return POD2_INDEX if ver == 2 else struct.unpack_from("<I", data, 0x108)[0]


def entries(data: bytes) -> list[Entry]:
    ver = version(data[:POD3_HEADER])
    if not ver:
        return []
    count = struct.unpack_from("<I", data, 0x58)[0]
    index = _index(data, ver)
    names = index + count * ENTRY
    if names > len(data):
        return []
    # POD3 keeps the index after the data, so nothing may run into it; POD2 keeps it in front.
    limit = index if ver == 3 else len(data)
    out: list[Entry] = []
    for i in range(count):
        path_off, size, offset, stamp, _sum = struct.unpack_from("<5I", data, index + i * ENTRY)
        if size == 0 or offset + size > limit or offset < (names if ver == 2 else POD3_HEADER):
            continue
        start = names + path_off
        if start >= len(data):
            continue
        end = data.find(b"\0", start)
        name = data[start : end if end >= 0 else len(data)].decode("latin-1", "replace")
        if not name:
            continue
        out.append(Entry(name.replace("\\", "/").lstrip("./"), offset, size, stamp))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return [(e.name, data[e.offset : e.offset + e.size]) for e in entries(data)]
