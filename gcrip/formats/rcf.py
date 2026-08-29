"""Radical Entertainment RCF archives (``RADCORE CEMENT LIBRARY`` on Hulk / Dark Summit /
The Incredible Hulk, ``ATG CORE CEMENT LIBRARY`` on Crash Tag Team Racing).

RADCORE: big-endian ``u32 @0x24 directory offset``; directory = ``u32 count, u32 names
offset, u32 names size, u32`` then ``(u32 hash, u32 offset, u32 size)`` entries sorted by
hash; the names table (little-endian) lists ``u32 length, name, u32 key`` in offset order.
ATG: ``u32 @0x24 dir offset, @0x28 dir size, @0x2c names offset, @0x30 names size, @0x38
count``; entries are 20 bytes ``(hash, offset, packed size, unpacked size, flags)`` - or 12
bytes ``(hash, offset, size)`` in the stored-only archives - and members with ``flags & 1``
and ``packed != unpacked`` are chains of ``u16 LE packed, u16 LE unpacked`` LZR blocks
(gcrip.formats.lzr; ``packed == 0`` = a stored block).
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
    """RADCORE names: ``u32 count, u32 0`` then ``u32 length, name, u32 key`` per member."""
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


def _atg_names(data: bytes, off: int, count: int) -> list[str]:
    """ATG names: 8-byte table header, then per member ``u32 key, u32 0x80000, u32 0,
    u32 LE length, name (NUL included), 3 zero bytes`` in offset order."""
    out = []
    o = off + 8
    for _ in range(count):
        if o + 16 > len(data):
            break
        ln = struct.unpack_from("<I", data, o + 12)[0]
        if ln > 1024:
            break
        s = data[o + 16 : o + 16 + ln].split(b"\0")[0].decode("latin-1", "replace")
        out.append(s.replace("\\", "/"))
        o += 16 + ln + 3
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
        dir_off, dir_size, names_off, _names_size = struct.unpack_from(">IIII", data, 0x24)
        count = struct.unpack_from(">I", data, 0x38)[0]
        esize = dir_size // count if count else 20
        if esize >= 20:
            ents = [struct.unpack_from(">IIIII", data, dir_off + i * 20) for i in range(count)]
        else:  # (hash, offset, size): stored members only
            raw = (struct.unpack_from(">III", data, dir_off + i * 12) for i in range(count))
            ents = [(h, off, sz, sz, 0) for h, off, sz in raw]
        ents = [e for e in ents if e[1] + e[2] <= len(data)]
        names = _atg_names(data, names_off, len(ents))
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
    """A member's bytes; ATG members are chains of ``u16 LE packed, u16 LE unpacked``
    blocks of LZR (block unpacked size 4096, the last one smaller; ``packed == 0`` means
    the block is stored as-is)."""
    raw = data[m.offset : m.offset + m.size]
    if not m.compressed:
        return raw
    out = bytearray()
    o = 0
    while len(out) < m.unpacked and o + 4 <= len(raw):
        packed, unpacked = struct.unpack_from("<HH", raw, o)
        o += 4
        if packed == 0:
            out += raw[o : o + unpacked]
            o += unpacked
            continue
        if unpacked == 0 or o + packed > len(raw):
            raise lzr.LzrError("bad RCF block")
        block = raw[o : o + packed]
        try:
            out += lzr.lzr(block, unpacked)
        except lzr.LzrError:
            out += lzr.lzrf(block, unpacked)
        o += packed
    if len(out) != m.unpacked:
        raise lzr.LzrError("RCF member size mismatch")
    return bytes(out)
