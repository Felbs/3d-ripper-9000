"""THQ ``pack`` archives (Avatar: The Last Airbender, The Adventures of Jimmy Neutron, Alien
Hominid, Darkened Skye, Future Tactics ...): ``.PAK`` files that hold named members, often a
pack inside a pack.

Header (big-endian): ``char "pack" | u32 version (1) | u32 header size | u32 total size |
u32 name-table offset | u32 member count | u32``, then 16-byte entries at 0x1c - ``u32 data
offset | u32 size | u32 flags | u32 name offset`` - and the name table of NUL-terminated
paths (``data/boot.rad``) at the offset the header names.  Members are usually ``.rad``
objects (``rad0`` + section table) or further packs.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"pack"
ENTRY = 16
TABLE = 0x1C


@dataclass
class Member:
    name: str
    offset: int
    size: int
    flags: int


def is_pack(head: bytes) -> bool:
    if len(head) < TABLE or head[:4] != MAGIC:
        return False
    version, _hdr, _total, names, count = struct.unpack_from(">5I", head, 4)
    return version == 1 and 0 < count < 100000 and names >= TABLE


def members(data: bytes) -> list[Member]:
    if not is_pack(data[:TABLE]):
        return []
    names_off, count = struct.unpack_from(">2I", data, 0x10)
    if names_off >= len(data):
        return []
    out = []
    for k in range(count):
        o = TABLE + k * ENTRY
        if o + ENTRY > len(data):
            break
        offset, size, flags, name_off = struct.unpack_from(">4I", data, o)
        if size == 0 or offset + size > len(data):
            continue
        p = names_off + name_off
        if p >= len(data):
            continue
        end = data.find(b"\0", p)
        name = data[p : end if end >= 0 else p].decode("latin-1", "replace")
        out.append(Member(name or f"member{k:04d}", offset, size, flags))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for m in members(data):
        name = m.name
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append((name, data[m.offset : m.offset + m.size]))
    return out
