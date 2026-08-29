"""Radical Entertainment RCF archives (``RADCORE CEMENT LIBRARY`` on Hulk / Dark Summit /
The Incredible Hulk, ``ATG CORE CEMENT LIBRARY`` on Crash Tag Team Racing).

RADCORE: big-endian ``u32 @0x24 directory offset``; directory = ``u32 count, u32 names
offset, u32 names size, u32`` then ``(u32 hash, u32 offset, u32 size)`` entries sorted by
hash; the names table (little-endian) lists ``u32 length, name, u32 key`` in offset order.
ATG: ``u32 @0x24 dir offset, @0x28 dir size, @0x2c names offset, @0x30 names size, @0x38
count``; entries are 20 bytes ``(hash, offset, packed size, unpacked size, flags)`` and
members with ``flags & 1`` and ``packed != unpacked`` are LZR streams (gcrip.formats.lzr).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.formats import lzr

MAGIC_RADCORE = b"RADCORE CEMENT LIBRARY"
MAGIC_ATG = b"ATG CORE CEMENT LIBRARY"


@dataclass
class Member:
    name: str
    offset: int
    size: int
    unpacked: int
    compressed: bool


def is_rcf(head: bytes) -> bool:
    return head.startswith(MAGIC_RADCORE) or head.startswith(MAGIC_ATG)


def _names(data: bytes, off: int, count: int) -> list[str]:
    out = []
    o = off + 8
    for _ in range(count):
        if o + 4 > len(data):
            break
        ln = struct.unpack_from("<I", data, o)[0]
        s = data[o + 4 : o + 4 + ln].split(b"\0")[0].decode("latin-1", "replace")
        out.append(s.replace("\\", "/"))
        o += 8 + ln
    return out


def members(data: bytes) -> list[Member]:
    if data.startswith(MAGIC_RADCORE):
        dir_off = struct.unpack_from(">I", data, 0x24)[0]
        count, names_off = struct.unpack_from(">II", data, dir_off)
        ents = [struct.unpack_from(">III", data, dir_off + 16 + i * 12) for i in range(count)]
        ents = [e for e in ents if e[1] + e[2] <= len(data)]
        names = _names(data, names_off, len(ents))
        ents.sort(key=lambda e: e[1])
        return [
            Member(names[i] if i < len(names) else f"{h:08x}", off, sz, sz, False)
            for i, (h, off, sz) in enumerate(ents)
        ]
    if data.startswith(MAGIC_ATG):
        dir_off, _dir_size, names_off, _names_size = struct.unpack_from(">IIII", data, 0x24)
        count = struct.unpack_from(">I", data, 0x38)[0]
        ents = [struct.unpack_from(">IIIII", data, dir_off + i * 20) for i in range(count)]
        ents = [e for e in ents if e[1] + e[2] <= len(data)]
        names = _names(data, names_off, len(ents))
        ents.sort(key=lambda e: e[1])
        return [
            Member(
                names[i] if i < len(names) else f"{h:08x}",
                off,
                packed,
                unpacked,
                bool(flags & 1) and packed != unpacked,
            )
            for i, (h, off, packed, unpacked, flags) in enumerate(ents)
        ]
    return []


def read(data: bytes, m: Member) -> bytes:
    raw = data[m.offset : m.offset + m.size]
    if not m.compressed:
        return raw
    try:
        return lzr.lzr(raw, m.unpacked)
    except lzr.LzrError:
        return lzr.lzrf(raw, m.unpacked)
