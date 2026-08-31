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

The Scorpion King's archives are a different layout - no `TOC`, and only the first 32 bytes
parse as an entry - so they are left alone here rather than forced through this reader.
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


def members(data: bytes) -> list[Member]:
    if not is_toc_wad(data[:HEADER]):
        return []
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
