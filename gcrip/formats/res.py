"""``res\\n`` resource files (Digimon Rumble Arena 2, Lemony Snicket's A Series of Unfortunate
Events, Samurai Jack: The Shadow of Aku - the same middleware under three publishers).

Header (big-endian): ``char "res\\n" | u16 version (7) | u16 | u32 data offset | u32 data size
| u32 | u32 | u32 | u32 directory offset | u32 directory size | u32 tag count`` followed by
one 8-byte record per tag kind (``char tag[4] | u8 | u8 | u16``).  The directory lives at the
end of the file: ``u32 entry count`` then 20-byte entries ``u32 id | char tag[4] | u32 offset
| u32 size | u32 flags``, where the offset is relative to the data area.

Section tags seen: ``wave`` / ``musc`` / ``mdat`` (audio), ``strg`` / ``indx`` (text and its
index), and on level files ``sdta``, ``gshd``, ``node``, ``surf``, ``ndbg``, ``levl``,
``tern``, ``rdms`` - the geometry side, which is not decoded yet.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"res\n"
ENTRY = 20


@dataclass
class Section:
    tag: str
    ident: int
    offset: int  # absolute in the file
    size: int
    flags: int


def is_res(head: bytes) -> bool:
    if len(head) < 0x28 or head[:4] != MAGIC:
        return False
    version = head[4]  # stored little-endian: 07 00
    data_off, data_size = struct.unpack_from(">2I", head, 8)
    return 0 < version <= 32 and data_off >= 0x28 and data_size > 0


def sections(data: bytes) -> list[Section]:
    if not is_res(data[:0x28]):
        return []
    data_off, data_size = struct.unpack_from(">2I", data, 8)
    dir_off, dir_size = struct.unpack_from(">2I", data, 0x1C)
    if dir_off + dir_size > len(data) or dir_size < 4:
        return []
    count = struct.unpack_from(">I", data, dir_off)[0]
    if not 0 < count < 100000 or 4 + count * ENTRY > dir_size + ENTRY:
        return []
    out = []
    for i in range(count):
        p = dir_off + 4 + i * ENTRY
        if p + ENTRY > len(data):
            break
        ident, tag, off, size, flags = struct.unpack_from(">I4sIII", data, p)
        start = data_off + off
        if size == 0 or start + size > len(data) or off + size > data_size + size:
            continue
        out.append(Section(tag.decode("latin-1", "replace").strip("\0"), ident, start, size, flags))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for i, s in enumerate(sections(data)):
        name = f"{i:03d}_{s.tag or 'sect'}_{s.ident}.bin"
        out.append((name, data[s.offset : s.offset + s.size]))
    return out
