"""Yuke's ``.tex`` texture directories - WWE Day of Reckoning 1 and 2, WrestleMania XIX.

Three discs holding **7,641 `.tex` files and 309 MB** between them, and all three reported
almost nothing: 14, 76 and 9 textures.  Nothing opened the `.tex`, so the TPLs inside were
never seen.

Little-endian::

    +0    u32 count            30
    +4    u32 0x100
    +8    u32 0
    +12   u32 16               where the table starts
    +16   the table, 32 bytes an entry:
              char name[16]    "tooth", "blood", "c036_hand", "cos_sode", "eye"
              char type[4]     "tpl"
              u32 size
              u32 offset
              u32 0

**The size comes before the offset**, which is the one trap in the format: read them the other
way round and the entries overlap, run backwards and point at the middle of neighbouring
members.  It still produces plausible-looking numbers - offsets inside the file, sizes under
its length - so it does not announce itself.  What settles it is that the payloads then land on
the TPL magic: with size and offset the right way round, all 30 entries of `036_0.tex` point
exactly at the 30 `00 20 af 30` headers in the file, and consecutive members tile
(992 + 1088 = 2080, 2080 + 33376 = 35456, ...).

The members are ordinary Nintendo TPLs, so ``gcrip/plugins/tpl.py`` decodes them once this
hands them over - there is no new texture code here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = 16
ENTRY = 32
NAME_LEN = 16
TYPE_LEN = 4
TYPE_AT = 16
SIZE_AT = 20
OFFSET_AT = 24
KIND = b"tpl"
MAX_COUNT = 1 << 16
SNIFF = 36


@dataclass
class Member:
    name: str
    kind: str
    offset: int
    size: int


def is_tex(head: bytes) -> bool:
    """The first entry's type tag sits at +32, inside the 64 bytes classify sniffs."""
    if len(head) < SNIFF:
        return False
    count, _version, zero, table = struct.unpack_from("<4I", head, 0)
    if not (0 < count <= MAX_COUNT) or zero != 0 or table != HEADER:
        return False
    return head[TYPE_AT + HEADER : TYPE_AT + HEADER + len(KIND)] == KIND


def members(data: bytes) -> list[Member]:
    """Every entry that lies inside the file.  Members must not overlap - that is what
    catches a size/offset swap rather than trusting the field order."""
    if not is_tex(data[:64]):
        return []
    count = struct.unpack_from("<I", data, 0)[0]
    out: list[Member] = []
    for i in range(count):
        at = HEADER + i * ENTRY
        if at + ENTRY > len(data):
            break
        raw = data[at : at + NAME_LEN].split(b"\x00", 1)[0]
        kind = data[at + TYPE_AT : at + TYPE_AT + TYPE_LEN].split(b"\x00", 1)[0]
        size, offset = struct.unpack_from("<2I", data, at + SIZE_AT)
        if size == 0 or offset < HEADER or offset + size > len(data):
            continue
        name = raw.decode("latin-1", "replace") or f"member{i:04d}"
        out.append(Member(name, kind.decode("latin-1", "replace") or "bin", offset, size))
    spans = sorted((m.offset, m.offset + m.size) for m in out)
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        if start < end:
            return []
    return out
