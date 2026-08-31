"""``WART3.00`` ``.hog`` archives - Warthog's engine, on Animaniacs, Looney Tunes: Back in
Action and Harry Potter and the Sorcerer's Stone.

101 archives across the three discs hold **138,326 named members**, among them 19,156
``.bmsh`` meshes, 29,047 ``.btga`` textures, 3,286 ``.bskl`` skeletons and 10,509 ``.anm``
animations.  The directory below is solved and verified; **the member codec is not**, so this
module reads the table and is deliberately not registered as a container plugin - expanding
into still-compressed members would only feed the pipeline garbage.  See ``docs/OPEN.md``.

Big-endian throughout::

    +0   char magic[8]        "WART3.00"
    +8   u32  member count
    +12  u32  name table offset
    +16  u32  file-name section bytes
    +20  u32  directory-name section bytes
    +24  the records, 24 bytes each:
             u32 data offset
             u32 packed size
             u32 unpacked size
             u32 hash
             u32 file name offset    from name table + directory bytes
             u32 directory name offset

The name table is two runs of NUL-terminated strings: the directories first (each ending in a
slash), then the file names, and a record names one of each - so a member's path is
``dirs[record.dir] + files[record.name]``.

**The field order is the trap.**  Read as if the records began at +16, every offset and size
still chains perfectly - member N ends exactly where member N+1 begins - because the two name
words merely shift the whole window by eight bytes.  What gives it away is the payload: under
the wrong order Animaniacs' two ``.btga`` fonts unpack to 9,602 bytes and its two ``.tnf``
metrics files to 131,168, which is backwards.  Under the right one both textures are 131,168
and both metrics files 9,602.  *Contiguity confirms the stride, not the field order.*

The directory-bytes word is byte-swapped on some archives - Animaniacs stores 30 as
``00 00 00 1e`` and Looney Tunes stores 147 as ``93 00 00 00``.  Rather than trust either, the
value is accepted only if it lands just past a NUL in the name table, and byte-swapped if not.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"WART3.00"
HEADER = 24
ENTRY = 24
MAX_COUNT = 1 << 20


@dataclass
class Member:
    name: str
    offset: int
    packed: int
    unpacked: int
    hash: int


def is_wart_hog(head: bytes) -> bool:
    """``head`` may be as little as the 64 bytes ``classify`` sniffs."""
    return head[:8] == MAGIC


def _dir_bytes(word: int, table: bytes) -> int | None:
    for value in (word, struct.unpack("<I", struct.pack(">I", word))[0]):
        if 0 < value < len(table) and not table[value - 1]:
            return value
    return None


def _string(table: bytes, at: int) -> str | None:
    if not 0 <= at < len(table):
        return None
    end = table.find(b"\0", at)
    return table[at:end].decode("latin-1") if end > at else None


def members(data: bytes) -> list[Member]:
    if not is_wart_hog(data[:8]) or len(data) < HEADER:
        return []
    count, names_at, _files, dir_word = struct.unpack_from(">4I", data, 8)
    if not 0 < count <= MAX_COUNT or not HEADER < names_at < len(data):
        return []
    if HEADER + count * ENTRY > names_at:
        return []
    table = data[names_at:]
    dir_bytes = _dir_bytes(dir_word, table)
    if dir_bytes is None:
        return []
    out = []
    for i in range(count):
        offset, packed, unpacked, digest, name_at, dir_at = struct.unpack_from(
            ">6I", data, HEADER + i * ENTRY
        )
        name = _string(table, dir_bytes + name_at)
        folder = _string(table, dir_at)
        if name is None:
            continue
        out.append(Member((folder or "") + name, offset, packed, unpacked, digest))
    return out
