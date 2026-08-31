"""THQ ``pack`` archives (Avatar: The Last Airbender, The Adventures of Jimmy Neutron, Alien
Hominid, Darkened Skye, Future Tactics ...): ``.PAK`` files that hold named members, often a
pack inside a pack.

Header (big-endian): ``char "pack" | u32 version (1) | u32 header size | u32 total size |
u32 name-table offset | u32 member count | u32``, then 16-byte entries at 0x1c - ``u32 data
offset | u32 size | u32 flags | u32 name offset`` - and the name table of NUL-terminated
paths (``data/boot.rad``) at the offset the header names.  Members are usually ``.rad``
objects (``rad0`` + section table) or further packs.

**Two versions share the magic and differ in both the header length and the entry shape**, so
the version word at +4 has to be read before anything else:

* **version 1** - header `magic | version | header size | total size | name-table offset |
  count | u32`, then 16-byte entries at 0x1c of `data offset | size | flags | name offset`.
* **version 0** (The Adventures of Jimmy Neutron, 23 archives, 1 GB) - a 24-byte header
  `magic | version | u32 | total size | name-table offset | count`, then **12-byte** entries of
  `name offset | data offset | size`.

The check that settles the version-0 layout is that the entries end exactly where the names
begin: ``24 + count * 12 == name-table offset`` (132 on `boot.pak`, to the byte).  A member of
size zero is normal there - several entries alias the same data offset - so an empty member is
skipped rather than treated as a broken table.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"pack"
ENTRY = 16
TABLE = 0x1C
ENTRY_V0 = 12
TABLE_V0 = 24


@dataclass
class Member:
    name: str
    offset: int
    size: int
    flags: int


def is_pack(head: bytes) -> bool:
    if len(head) < TABLE or head[:4] != MAGIC:
        return False
    version = struct.unpack_from(">I", head, 4)[0]
    if version == 0:
        names, count = struct.unpack_from(">2I", head, 0x10)
        return 0 < count < 100000 and names == TABLE_V0 + count * ENTRY_V0
    _hdr, _total, names, count = struct.unpack_from(">4I", head, 8)
    return version == 1 and 0 < count < 100000 and names >= TABLE


def _name_at(data: bytes, at: int) -> str:
    end = data.find(b"\0", at)
    return data[at : end if end >= 0 else at].decode("latin-1", "replace")


def _members_v0(data: bytes, names_off: int, count: int) -> list[Member]:
    out = []
    for k in range(count):
        o = TABLE_V0 + k * ENTRY_V0
        if o + ENTRY_V0 > len(data):
            break
        name_off, offset, size = struct.unpack_from(">3I", data, o)
        if size == 0 or offset + size > len(data) or names_off + name_off >= len(data):
            continue  # a zero-size entry aliases another member's data; it is not an error
        name = _name_at(data, names_off + name_off)
        out.append(Member(name or f"member{k:04d}", offset, size, 0))
    return out


def members(data: bytes) -> list[Member]:
    if not is_pack(data[:TABLE]):
        return []
    names_off, count = struct.unpack_from(">2I", data, 0x10)
    if names_off >= len(data):
        return []
    if struct.unpack_from(">I", data, 4)[0] == 0:
        return _members_v0(data, names_off, count)
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
