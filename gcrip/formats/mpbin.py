"""Hudson Soft Mario Party GameCube ``.bin`` archives (Mario Party 4-7): ``u32 count | u32
offsets[count]`` (big-endian) and per member ``u32 unpacked size | u32 compression |
data``.  Compression 0 stored, 1 LZSS (1 KB ring starting at 0x3be, 3-bit-flag stream), 2/3/4
"slide" (Yaz0-like: 32-bit flag words, 12-bit distance, 4-bit length with an extension
byte), 5 RLE, 7 zlib (after an 8-byte size header).  Layout after MPLibrary's MPBIN.cs.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass


@dataclass
class Member:
    index: int
    offset: int  # of the 8-byte member header
    packed: int
    size: int
    compression: int


def is_mpbin(head: bytes, size: int | None = None) -> bool:
    if len(head) < 16:
        return False
    count, first = struct.unpack_from(">2I", head, 0)
    if not (0 < count < 4096) or first not in (4 + 4 * count, 8 + 4 * count):
        return False
    return size is None or first + 8 <= size


def members(data: bytes) -> list[Member]:
    if not is_mpbin(data[:16], len(data)):
        return []
    count = struct.unpack_from(">I", data, 0)[0]
    if 4 + 4 * count > len(data):
        return []
    offsets = list(struct.unpack_from(f">{count}I", data, 4))
    out = []
    for i, off in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < count else len(data)
        if off + 8 > len(data) or end < off + 8:
            continue
        size, comp = struct.unpack_from(">2I", data, off)
        out.append(Member(i, off, end - off - 8, size, comp))
    return out


def _lzss(src: bytes, out_len: int) -> bytes:
    window = bytearray(1024)
    wpos = 0x3BE
    out = bytearray()
    p = 0
    code = 0
    n = len(src)
    while len(out) < out_len and p < n:
        if not code & 0x100:
            code = src[p] | 0xFF00
            p += 1
        if code & 1:
            if p >= n:
                break
            b = src[p]
            p += 1
            out.append(b)
            window[wpos] = b
            wpos = (wpos + 1) & 1023
        else:
            if p + 2 > n:
                break
            b1, b2 = src[p], src[p + 1]
            p += 2
            off = ((b2 & 0xC0) << 2) | b1
            ln = (b2 & 0x3F) + 3
            for _ in range(ln):
                v = window[off & 1023]
                off += 1
                window[wpos] = v
                wpos = (wpos + 1) & 1023
                out.append(v)
                if len(out) >= out_len:
                    break
        code >>= 1
    return bytes(out)


def _slide(src: bytes, out_len: int) -> bytes:
    out = bytearray()
    p = 4
    n = len(src)
    bits = 0
    nbits = 0
    while len(out) < out_len:
        if nbits == 0:
            if p + 4 > n:
                break
            bits = struct.unpack_from(">I", src, p)[0]
            p += 4
            nbits = 32
        if bits & 0x80000000:
            if p >= n:
                break
            out.append(src[p])
            p += 1
        else:
            if p + 2 > n:
                break
            b1, b2 = src[p], src[p + 1]
            p += 2
            dist = (((b1 & 0x0F) << 8) | b2) + 1
            ln = (b1 >> 4) + 2
            if ln == 2:
                if p >= n:
                    break
                ln = src[p] + 18
                p += 1
            for _ in range(ln):
                if len(out) >= out_len:
                    break
                out.append(out[-dist] if dist <= len(out) else 0)
        bits = (bits << 1) & 0xFFFFFFFF
        nbits -= 1
    return bytes(out)


def _rle(src: bytes, out_len: int) -> bytes:
    out = bytearray()
    p = 0
    n = len(src)
    while len(out) < out_len and p < n:
        code = src[p]
        p += 1
        ln = code & 0x7F
        if code & 0x80:
            out += src[p : p + ln]
            p += ln
        else:
            if p >= n:
                break
            out += bytes([src[p]]) * ln
            p += 1
    return bytes(out[:out_len])


def read(data: bytes, m: Member) -> bytes:
    raw = data[m.offset + 8 : m.offset + 8 + m.packed]
    if m.compression == 0:
        return raw[: m.size] if m.size else raw
    if m.compression == 1:
        return _lzss(raw, m.size)
    if m.compression in (2, 3, 4):
        return _slide(raw, m.size)
    if m.compression == 5:
        return _rle(raw, m.size)
    if m.compression == 7:
        return zlib.decompress(raw[8:])
    return raw
