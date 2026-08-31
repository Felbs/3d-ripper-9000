"""``TOC`` ``.wad`` archives - Spawn: Armageddon keeps its whole game in 201 of them, 435 MB.

Big-endian::

    +0   16 zero bytes
    +16  char magic[4]   "TOC\\0"
    +20  u32 table bytes
    +24  u32 entry count
    +28  the table, 32 bytes an entry:
             char name[16]      "SPAWNTPAGE02", "GLOBALSFX", "DBSHOTGUN_A"
             char type[4]       "TIM", "SFX", "PHM", "PAT", "PHA", "SPR", "GAM", "GRP"
             u32 offset
             u32 size
             u32
    ...  the members, 32-byte aligned

``table bytes == count * 32`` is the check, and it holds on all 201 archives.

**The dead-ends list said these were audio.**  They are not: 5,919 of Spawn's 12,034 members are
`TIM` textures, against 142 `SFX`.  The note came from sampling four bytes at the start of each
file, and this is exactly the trap that produces - on The Scorpion King, whose `.wad` open with
their own name rather than zeros, that sample returned `TBLE`, `GMLE`, `MTPP`, `RVAR`, `LEV0`
and `MCPA`, which read like chunk tags and are simply the first four letters of `TBLEV30SFX`,
`GMLEVEL...`, `RVAREA04SFX` and so on.  **A four-byte sample turns an embedded filename into a
fake magic.**

The Scorpion King's 200 archives are the **same records without the central table**: each one
begins with a 28-byte wrapper - `char name[16] | char type[4] | u32 size | u32` - and the next
record follows at ``offset + 28 + size``.  Reading the size as the whole record's length stops
the walk after one member every time; the size counts only what comes after the wrapper.

All 200 walk that way, giving 8,883 records - 6,099 of them `TIM` - and 299 of the disc's
312 MB.  The walk stops a little short of every file's end rather than exactly on it, so the
tail is padding or something unindexed; the coverage is reported rather than assumed exact.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"TOC\x00"
MAGIC_AT = 16
HEADER = 28
ENTRY = 32
NAME = 16
TYPE = 4
MAX_ENTRIES = 262144
WRAPPER = 28  # the inline variant: name[16] | type[4] | u32 size | u32
KINDS = {b"TIM", b"SFX", b"PHM", b"PAT", b"PHA", b"SPR", b"GAM", b"GRP", b"SOB"}
MAX_MEMBER = 1 << 27
MIN_INLINE = 2


@dataclass
class Member:
    name: str
    kind: str
    offset: int
    size: int


def is_toc_wad(head: bytes) -> bool:
    if len(head) < HEADER or head[MAGIC_AT : MAGIC_AT + 4] != MAGIC or any(head[:MAGIC_AT]):
        return False
    table, count = struct.unpack_from(">2I", head, 20)
    return 0 < count <= MAX_ENTRIES and table == count * ENTRY


def looks_inline(head: bytes) -> bool:
    """The Scorpion King variant has **no magic at all**, so it has to be recognised from the
    shape of its first record inside the 64 bytes ``classify`` sniffs: a NUL-padded name, one
    of the known type tags, and a plausible size.

    Without this the variant is invisible to the pipeline.  :func:`members` was written and
    tested for it, and :func:`expand` calls it - but the plugin only ever asked
    :func:`is_toc_wad`, which wants Spawn's magic, so the disc's 6,099 textures never reached
    a scene.  ``members`` still requires two chaining records, so a loose claim here costs an
    in-memory parse and nothing else.
    """
    if len(head) < WRAPPER:
        return False
    name = head[:NAME]
    if not (32 < name[0] < 127):
        return False
    body = name.rstrip(b"\0")
    if not body or not all(32 <= c < 127 for c in body):
        return False
    if head[NAME : NAME + TYPE].rstrip(b"\0") not in KINDS:
        return False
    size = struct.unpack_from(">I", head, NAME + TYPE)[0]
    return 0 < size < MAX_MEMBER


def _inline(data: bytes) -> list[Member]:
    """The Scorpion King variant: wrapped records back to back, no central table."""
    out: list[Member] = []
    p = 0
    while p + WRAPPER <= len(data) and len(out) < MAX_ENTRIES:
        raw = data[p : p + NAME].split(b"\0")[0]
        kind = data[p + NAME : p + NAME + TYPE].split(b"\0")[0]
        size = struct.unpack_from(">I", data, p + NAME + TYPE)[0]
        if not raw or not all(32 <= c < 127 for c in raw):
            break
        if not size or p + WRAPPER + size > len(data):
            break
        out.append(
            Member(
                raw.decode("latin-1"),
                kind.decode("latin-1", "replace"),
                p + WRAPPER,
                size,
            )
        )
        p += WRAPPER + size
    return out if len(out) >= MIN_INLINE else []


def members(data: bytes) -> list[Member]:
    if not is_toc_wad(data[:HEADER]):
        return _inline(data)
    table, count = struct.unpack_from(">2I", data, 20)
    if HEADER + table > len(data):
        return []
    out: list[Member] = []
    for i in range(count):
        p = HEADER + i * ENTRY
        name = data[p : p + NAME].split(b"\0")[0].decode("latin-1", "replace")
        kind = data[p + NAME : p + NAME + TYPE].split(b"\0")[0].decode("latin-1", "replace")
        offset, size, _extra = struct.unpack_from(">3I", data, p + NAME + TYPE)
        if not size or offset < HEADER + table or offset + size > len(data):
            continue
        out.append(Member(name or f"member{i:05d}", kind, offset, size))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for m in members(data):
        name = f"{m.name}.{m.kind}" if m.kind else m.name
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:
            stem, _dot, ext = name.rpartition(".")
            name = f"{stem}_{n:03d}.{ext}" if stem else f"{name}_{n:03d}"
        out.append((name, data[m.offset : m.offset + m.size]))
    return out
