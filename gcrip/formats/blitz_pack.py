"""Blitz Games (BlitzTech) ``.gcp`` bare packs - the resource index.

Read with the engine's own names: Bratz: Rock Angelz ships ``Bratz_NGC_M.elf`` with full
DWARF debug information, and ``_TBPackageIndex`` is its header (big-endian, offsets in
32-byte units)::

    +0x00 u32 id (name hash)      +0x04 u32 data start (0x20)   +0x08 u32 flags
    +0x0c u32 noofFiles           +0x10 u32 indexOffset         +0x14 u32 tagOffset
    +0x1c u32 noofTags            +0x20 u32 blockMapOffset      +0x24 u32 blockMapSize
    +0x28 u32 filenameTableOffset +0x2c u32 filenameTableSize   +0x30 u32 indexSize
    +0x38 u32 buildNumber

The index is 32 bytes a file: ``u32 offset, u32 crc, u32 size, u32 name offset (into the
filename table), u32 1, u32 tags, u32 owner, u32 flags``.  Every resource opens with a
32-byte ``_TBResourceInfo`` whose byte at +6 is the resource type: 0 texture, 1 actor,
15 simulation.  Two system files (``FilenameTable.pak.sys``, ``TagTable.pak.sys``) and a
one-byte ``dummy`` sit in every pack.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

UNIT = 32
ENTRY = 32
DATA_START = 0x20
TYPE_TEXTURE, TYPE_ACTOR, TYPE_SIM = 0, 1, 15
MAX_FILES = 1 << 16


@dataclass
class Resource:
    name: str
    offset: int
    size: int
    crc: int
    tags: int
    kind: int  # _TBResourceInfo.type, or -1 for system files


def is_bare_pack(head: bytes) -> bool:
    if len(head) < 0x40:
        return False
    start, zero, count = struct.unpack_from(">3I", head, 4)
    return start == DATA_START and zero == 0 and 0 < count < MAX_FILES


def resources(data: bytes) -> list[Resource]:
    if not is_bare_pack(data[:0x40]):
        return []
    count, index = struct.unpack_from(">II", data, 0x0C)
    names_at, names_len = struct.unpack_from(">II", data, 0x28)
    index *= UNIT
    names_at *= UNIT
    if index + count * ENTRY > len(data) or names_at + names_len > len(data):
        return []
    names = data[names_at : names_at + names_len]
    out: list[Resource] = []
    for i in range(count):
        off, crc, size, name_off, _one, tags, _owner, _flags = struct.unpack_from(">8I", data, index + i * ENTRY)
        off *= UNIT
        if off + size > len(data) or name_off >= len(names):
            continue
        end = names.find(b"\0", name_off)
        name = names[name_off : end if end >= 0 else len(names)].decode("latin-1")
        kind = -1
        if not name.endswith(".pak.sys") and size >= 32:
            kind = data[off + 6]
        out.append(Resource(name, off, size, crc, tags, kind))
    return out
