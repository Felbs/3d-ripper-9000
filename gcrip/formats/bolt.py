"""Mass Media ``BOLT`` archives (``.BLT``) - Muppets Party Cruise, Namco Museum 50th Anniversary,
Pac-Man Fever, Shrek Super Party - and the LZ that packs their members.

Read with the engine's own names: Muppets Party Cruise ships ``Muppets.elf`` with 65 MB of
DWARF, so ``BOLTHeader``, ``BOLTGroupEntry`` / ``BOLTMemberEntry`` and ``MMI::Decompress``
are read, not guessed.  Big-endian.

  BOLTHeader (16):       "BOLT", u8 hours, mins, secs, sec100, u8 month, day, year,
                         u8 NGroups, u32 Size (the file length)
  BOLTGroupEntry (16):   u8 Flags, Init, Term, NumberMembers, u32 Size, u32 Offset (of the
                         group's member table), u32 (runtime pointer) - NGroups of them
  BOLTMemberEntry (16):  u8 Flags (0x08 = stored, else packed), Init, Term, Type, u32 Size,
                         u32 Offset, u32 (runtime address; a hash on disc)

A board archive is two groups (the 24 tiles, then 2 extras); Namco Museum's 321 MB
``Data0.blt`` is 42.

The codec (``MMI::Decompress(void*, int, short)``, a debug build so every local has a stack
slot) is a byte-oriented LZ with prefix bytes that widen the next copy's length and offset:

  b < 0x80        copy: length = (len << 3) + ((b >> 4) & 7) + prefixes + 2,
                        offset = (off << 4) + (b & 15) + 1; then reset
  0x80..0x8f      literal run of (len << 4) + (b & 15) + 1 bytes; reset
  0x90..0x9f      len = b & 3, off = (b >> 2) & 3, prefixes += 1
  0xa0..0xbf      len = (len << 5) + (b & 0x1f), prefixes += 1
  0xc0..0xff      off = (off << 6) + (b & 0x3f), prefixes += 1
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"BOLT"
HEADER = 0x20  # header plus at least one group entry
ENTRY = 16
PACKED = 0x40  # set on packed members of the 2003 archives; the 2002 ones leave it clear
STORED = 0x08  # MMI::Decompress: bit 3 copies the member as it is, anything else inflates
MAX_ENTRIES = 1 << 16


class BoltError(ValueError):
    pass


@dataclass
class Member:
    index: int
    flags: int
    kind: int
    size: int  # unpacked
    offset: int
    end: int  # of the packed bytes
    hash: int
    group: int = 0
    slot: int = 0  # position inside the group


def is_bolt(head: bytes, size: int = 0) -> bool:
    if head[:4] != MAGIC or len(head) < HEADER:
        return False
    declared = struct.unpack_from(">I", head, 12)[0]
    return declared == size if size else True


def decompress(src: bytes, size: int) -> bytes:
    out = bytearray()
    p = 0
    length = offset = prefixes = 0
    n = len(src)
    while len(out) < size:
        if p >= n:
            raise BoltError(f"stream ended at {len(out)} of {size} bytes")
        b = src[p]
        p += 1
        if b < 0x80:
            length = (length << 3) + ((b >> 4) & 7) + prefixes + 2
            offset = (offset << 4) + (b & 0x0F) + 1
            if offset > len(out):
                raise BoltError("copy before the start of the output")
            s = len(out) - offset
            for i in range(length):
                out.append(out[s + i])
            length = offset = prefixes = 0
        elif b <= 0x8F:
            count = (length << 4) + (b & 0x0F) + 1
            if p + count > n:
                raise BoltError("literal run past the end of the stream")
            out += src[p : p + count]
            p += count
            length = prefixes = 0
        elif b <= 0x9F:
            length = b & 3
            offset = (b & 0x0C) >> 2
            prefixes += 1
        elif b <= 0xBF:
            length = (length << 5) + (b & 0x1F)
            prefixes += 1
        else:
            offset = (offset << 6) + (b & 0x3F)
            prefixes += 1
    return bytes(out[:size])


def members(data: bytes) -> list[Member]:
    if not is_bolt(data[:HEADER]):
        return []
    ngroups = data[11]
    groups = []
    for g in range(ngroups):
        at = 16 + g * ENTRY
        if at + ENTRY > len(data):
            break
        _flags, _init, _term, count, _size, offset, _ptr = struct.unpack_from(">BBBBIII", data, at)
        if offset < 16 + ngroups * ENTRY or offset + count * ENTRY > len(data):
            break
        groups.append((count, offset))
    raw: list[tuple[int, int, int, int, int, int, int]] = []
    for g, (count, offset) in enumerate(groups):
        for i in range(count):
            p = offset + i * ENTRY
            flags, _init, _term, kind, size, off, h = struct.unpack_from(">BBBBIII", data, p)
            if off < 16 or off > len(data):
                continue
            raw.append((g, i, flags, kind, size, off, h))
    # packed members have no stored packed length: it runs to the next member's start
    starts = sorted({r[5] for r in raw} | {len(data)})
    out = []
    for g, i, flags, kind, size, off, h in raw:
        nxt = starts[starts.index(off) + 1] if starts.index(off) + 1 < len(starts) else len(data)
        out.append(Member(len(out), flags, kind, size, off, nxt, h, g, i))
    return out


def unpack(data: bytes, m: Member) -> bytes:
    blob = data[m.offset : m.end]
    if not m.flags & STORED:
        return decompress(blob, m.size)
    return blob[: m.size]
