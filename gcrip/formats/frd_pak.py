"""Free Radical ``P4CK`` / ``P5CK`` / ``P8CK`` archives - TimeSplitters 2, TimeSplitters:
Future Perfect and Second Sight keep everything in them, 2.7 GB across 637 files, and all
three discs reported zero models and zero textures.

Little-endian, four header words, and **two different meanings for them** that the magic does
not distinguish - the arithmetic does::

    +0   char magic[4]   "P4CK", "P5CK" or "P8CK"
    +4   u32
    +8   u32
    +12  u32

*Sized*, when ``a + b + c == len(file)``: `a` data bytes (the header included), then `b` bytes
of table, then `c` bytes of names.

*Counted*, when ``a + b * 12 == len(file)``: `a` is the **offset** of the table, `b` an entry
**count** and `c` the offset of the name block.  Each entry is `u32 name offset (from the name
block), u32 size, u32 data offset` - the size and the offset in the opposite order to the other
layout.  Both tests are exact and neither holds on the other's files, so nothing has to be
guessed from the magic.

**The entries come in three shapes and the magic does not say which**, so the reader tries each
and keeps the one that reconciles:

    named    16 bytes:  u32 name offset, u32 data offset, u32 size, u32 stored
    hashed   16 bytes:  u32 name hash,   u32 data offset, u32 size, u32 stored
    inline   60 bytes:  char name[48],   u32 data offset, u32 size, u32 stored

**The fourth word is the stored length and the third is the length after unpacking.**  Where
it is zero the member is stored as it is and the two agree; where it is not, the member is
**gzip**, and the gzip header carries the real file name - `prop_all_gcas.war` - which is what
the hashed archives are missing.  Reading the third word as the stored length walks a
compressed archive straight off the end of its data region, and that is what it looks like:
a fifth of Future Perfect's archives failing a range check for no visible reason.

A **name offset is measured from the start of the table**, not from the name block - on
``lv60.pak`` the five offsets are 80, 111, 146, 170 and 196 against a table of 80 bytes, and
subtracting the table size lands each one exactly on a string.  Reading them as name-block
offsets puts every name 80 bytes late.

The shapes are told apart by arithmetic rather than by a flag: the table size has to divide by
the stride, every member has to fit inside the data region, and the members have to **tile it
to the last byte** - ``igcs_06.pak`` runs from 32 to 794,304 with no gap bigger than an
alignment pad, and that is what identifies its 16-byte hashed entries against 60-byte inline
ones that would also divide.
"""

from __future__ import annotations

import gzip
import struct
import zlib
from dataclasses import dataclass

MAGICS = (b"P4CK", b"P5CK", b"P8CK")
HEADER = 16
NAMED = 16
INLINE = 60
INLINE_NAME = 48
TRAILING = 12
GZIP = bytes([31, 139])
ALIGN = 32  # the largest padding seen between members
MAX_MEMBERS = 262144


@dataclass
class Member:
    name: str
    offset: int
    stored: int  # bytes in the file
    size: int  # bytes after unpacking; the same when it is not compressed


def is_pck(head: bytes) -> bool:
    return len(head) >= HEADER and head[:4] in MAGICS


def _named(data: bytes, at: int, size: int, names: int) -> list[Member] | None:
    """16-byte entries whose first word is an offset from the start of the table."""
    if not names or size % NAMED:
        return None
    out = []
    for p in range(at, at + size, NAMED):
        name_at, offset, length, stored = struct.unpack_from("<4I", data, p)
        stop = data.find(b"\0", at + name_at)
        if not 0 < name_at < size + names or stop < 0:
            return None
        name = data[at + name_at : stop].decode("latin-1", "replace")
        out.append(Member(name, offset, stored or length, length))
    return out


def _hashed(data: bytes, at: int, size: int) -> list[Member] | None:
    if size % NAMED:
        return None
    out = []
    for i, p in enumerate(range(at, at + size, NAMED)):
        key, offset, length, stored = struct.unpack_from("<4I", data, p)
        out.append(Member(f"{key:08x}_{i:04d}", offset, stored or length, length))
    return out


def _inline(data: bytes, at: int, size: int) -> list[Member] | None:
    """60-byte entries carrying the name in place of an offset."""
    if size % INLINE:
        return None
    out = []
    for p in range(at, at + size, INLINE):
        raw = data[p : p + INLINE_NAME].split(b"\0")[0]
        if not raw or not all(32 <= c < 127 for c in raw):
            return None
        offset, length, stored = struct.unpack_from("<3I", data, p + INLINE_NAME)
        out.append(Member(raw.decode("latin-1"), offset, stored or length, length))
    return out


def _score(members: list[Member] | None, limit: int) -> int:
    """How much of the data region the members account for; -1 if any escapes it.

    An empty member is not a wrong reading - the cutscene archives are full of them - so a
    zero size counts for nothing rather than disqualifying the shape.  Insisting on non-empty
    members costs Future Perfect a fifth of its archives."""
    if not members:
        return -1
    for m in members:
        if m.stored and (m.offset < HEADER or m.offset + m.stored > limit):
            return -1
    return sum(m.stored for m in members)


def _trailing(data: bytes, table: int, count: int, names: int) -> list[Member]:
    """The other layout: the three header words are a table offset, an entry **count** and a
    name-block offset, and the table is the last ``count * 12`` bytes of the file.

    ``P8CK`` archives use it, and they are not told apart by the magic but by the arithmetic -
    ``table + count * 12 == len(file)`` holds on every one and on none of the others.  Entries
    are ``u32 name offset (from the name block), u32 size, u32 data offset``, which is the
    reverse of the order the first layout uses."""
    out = []
    for i in range(count):
        name_at, size, offset = struct.unpack_from("<3I", data, table + i * TRAILING)
        stop = data.find(b"\0", names + name_at)
        if not names + name_at < table or stop < 0 or offset + size > table:
            return []
        name = data[names + name_at : stop].decode("latin-1", "replace")
        out.append(Member(name, offset, size, size))
    return out


def members(data: bytes) -> list[Member]:
    if not is_pck(data[:HEADER]):
        return []
    body, table, names = struct.unpack_from("<3I", data, 4)
    if body + table * TRAILING == len(data) and HEADER <= names <= body:
        return _trailing(data, body, table, names)
    if body + table + names != len(data) or not table or body + table > len(data):
        return []
    if table // NAMED > MAX_MEMBERS:
        return []
    best, score = [], 0
    for got in (
        _named(data, body, table, names),
        _inline(data, body, table),
        _hashed(data, body, table),
    ):
        value = _score(got, body)
        if value > score:
            best, score = got, value
    return best


def _unpack(blob: bytes) -> tuple[str | None, bytes]:
    """Gunzip a member and take the name out of the gzip header, which is the only place the
    hashed archives keep one."""
    if not blob.startswith(GZIP):
        return None, blob
    name = None
    if blob[3] & 0x08:  # FNAME
        stop = blob.find(b"\0", 10)
        if stop > 0:
            name = blob[10:stop].decode("latin-1", "replace")
    try:
        return name, gzip.decompress(blob)
    except (OSError, EOFError, zlib.error):
        return name, blob


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for m in members(data):
        if not m.stored:
            continue
        inner, blob = _unpack(data[m.offset : m.offset + m.stored])
        name = (inner or m.name).replace("\\", "/").lstrip("/").replace("/", "__")
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:
            stem, _dot, ext = name.rpartition(".")
            name = f"{stem}_{n:03d}.{ext}" if stem else f"{name}_{n:03d}"
        out.append((name, blob))
    return out
