"""Fire Emblem: Path of Radiance (GFEE01) containers.

``.cmp`` / ``.cms`` files are GBA-style LZ10 streams (byte 0x10, then the decompressed size
as a little-endian u24, then flag-byte groups of 8 tokens: literal byte, or u16 big-endian
``(length-3) << 12 | (distance-1)``).  Most decompress to a ``pack`` archive, which is also
what the uncompressed ``.pak`` files are:

  0x00 char[4] "pack"   0x04 u16 member count   0x06 u16 0
  0x08 members, 16 bytes each: u32 0, u32 name offset, u32 data offset, u32 size
  (names are NUL-terminated, offsets absolute)

Members are ``.g`` (node tree), ``.gs`` (geometry), ``.ga`` (animation), ``.tpl`` textures,
``.bin`` map data, ``.dbx`` scripts.
"""

from __future__ import annotations

import struct

PACK_MAGIC = b"pack"


def is_lz10(head: bytes, size: int | None = None) -> bool:
    if len(head) < 5 or head[0] != 0x10:
        return False
    out = head[1] | head[2] << 8 | head[3] << 16
    return out > 0 and (size is None or out >= size // 2)


def lz10_size(data: bytes) -> int:
    return data[1] | data[2] << 8 | data[3] << 16


def lz10_decompress(data: bytes) -> bytes:
    """Decode an LZ10 stream (the header byte is checked, not the caller's file name)."""
    if not is_lz10(data):
        raise ValueError("not an LZ10 stream")
    size = lz10_size(data)
    out = bytearray()
    i = 4
    n = len(data)
    while len(out) < size and i < n:
        flags = data[i]
        i += 1
        for bit in range(8):
            if len(out) >= size or i >= n:
                break
            if flags & (0x80 >> bit):
                if i + 1 >= n:
                    break
                v = data[i] << 8 | data[i + 1]
                i += 2
                length = (v >> 12) + 3
                dist = (v & 0xFFF) + 1
                if dist > len(out):
                    raise ValueError("LZ10 back-reference before start")
                start = len(out) - dist
                if length <= dist:
                    out += out[start : start + length]
                else:
                    for _ in range(length):
                        out.append(out[-dist])
            else:
                out.append(data[i])
                i += 1
    return bytes(out[:size])


def is_pack(head: bytes) -> bool:
    return head[:4] == PACK_MAGIC and len(head) >= 8


def pack_members(data: bytes) -> list[tuple[str, bytes]]:
    if not is_pack(data):
        raise ValueError("not a pack archive")
    (count,) = struct.unpack_from(">H", data, 4)
    out: list[tuple[str, bytes]] = []
    for i in range(count):
        base = 8 + i * 16
        if base + 16 > len(data):
            break
        _zero, name_off, data_off, size = struct.unpack_from(">4I", data, base)
        if name_off >= len(data) or data_off > len(data):
            continue
        end = data.find(b"\0", name_off, name_off + 0x100)
        name = data[name_off : end if end >= 0 else name_off + 0x100].decode("latin1")
        if not name:
            name = f"member{i}"
        out.append((name, data[data_off : data_off + size]))
    return out
