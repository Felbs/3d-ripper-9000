"""Billy Hatcher ``.prd`` packages: ``u32 1 | u32 unpacked | u32 packed | u32 | u32`` then a
Sega PRS stream from 0x20 that inflates to a ``U\\xaa8-`` archive - ``magic | u32 table
offset (0x20) | u32 names size | u32 data offset`` and, at the table, ``u32 1 | u32 0 | u32
count + 1`` followed by ``count`` entries ``u32 name offset, u32 offset, u32 size`` (name
offsets relative to the byte after the entries)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.formats import prs

MAGIC = b"U\xaa8-"


@dataclass
class Member:
    name: str
    offset: int
    size: int


def is_prd(head: bytes) -> bool:
    if len(head) < 0x20 or struct.unpack_from(">I", head, 0)[0] != 1:
        return False
    unpacked, packed = struct.unpack_from(">2I", head, 4)
    return 0 < packed <= unpacked + unpacked // 8 + 16 and unpacked < (64 << 20)


def unpack(data: bytes) -> bytes:
    unpacked = struct.unpack_from(">I", data, 4)[0]
    return prs.decompress(data[0x20:], unpacked)


def members(u: bytes) -> list[Member]:
    if u[:4] != MAGIC or len(u) < 0x30:
        return []
    table, _names_size, _data = struct.unpack_from(">3I", u, 4)
    _one, _zero, count = struct.unpack_from(">3I", u, table)
    count = max(count - 1, 0)
    p = table + 12
    names = p + count * 12
    out = []
    for _ in range(min(count, 4096)):
        if p + 12 > len(u):
            break
        name_off, off, size = struct.unpack_from(">3I", u, p)
        p += 12
        s = names + name_off
        e = u.find(b"\0", s)
        name = u[s : e if e >= 0 else len(u)].decode("latin-1", "replace")
        if name and size and off + size <= len(u):
            out.append(Member(name, off, size))
    return out
