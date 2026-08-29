"""Eighting FPK archives (Naruto: Clash of Ninja / Gekitou Ninja Taisen, Bloody Roar:
Primal Fury, Zatch Bell!, Battle Stadium D.O.N).  Big-endian: ``u32 0 | u32 count | u32
header size (16) | u32 file size`` then 32-byte entries ``char name[20], u32 offset, u32
packed size, u32 unpacked size``.  Members are PRS-compressed (Eighting's variant of Sega's
PRS, as documented by GNTool: MSB-first flag bits, big-endian long-copy pairs) unless the
two sizes are equal.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class Member:
    name: str
    offset: int
    packed: int
    size: int


def is_fpk(head: bytes, size: int | None = None) -> bool:
    if len(head) < 48 or head[:4] != b"\0\0\0\0":
        return False
    count, hsize, total = struct.unpack_from(">3I", head, 4)
    if hsize != 16 or not (0 < count < 100_000) or total < 16 + count * 32:
        return False
    if size is not None and total != size:
        return False
    name = head[16:36].split(b"\0")[0]
    return bool(name) and all(32 <= c < 127 for c in name)


def members(data: bytes) -> list[Member]:
    """Entries carry a 20-byte name (Naruto GNT) or a 32-byte one (RenderWare-based
    Bloody Roar / D.O.N.: ``chr/ar2/0000_gc.dff``); the width whose entries all fit wins."""
    if not is_fpk(data[:64]):
        return []
    count, hsize, _total = struct.unpack_from(">3I", data, 4)
    for width in (20, 32):
        out = _entries(data, count, hsize, width)
        if out is not None:
            return out
    return []


def _entries(data: bytes, count: int, hsize: int, width: int) -> list[Member] | None:
    esize = width + 12
    first = hsize + count * esize
    out = []
    for i in range(count):
        o = hsize + i * esize
        if o + esize > len(data):
            return None
        name = data[o : o + width].split(b"\0")[0].decode("latin-1", "replace")
        off, packed, size = struct.unpack_from(">3I", data, o + width)
        if not name or any(ord(c) < 32 or ord(c) > 126 for c in name):
            return None
        if off < first or off + packed > len(data):
            return None
        if size:
            out.append(Member(name.replace("\\", "/"), off, packed, size))
    return out


def prs_decompress(src: bytes, out_len: int) -> bytes:
    """Eighting PRS: flag bits MSB-first; 1 = literal; 0,0 = short copy (2 bits length + 2,
    offset byte - 256); 0,1 = long copy (big-endian u16: offset >> 3, length & 7 (+2, or 0
    -> next byte + 1))."""
    out = bytearray()
    p = 0
    n = len(src)
    flag = 0
    nb = 0
    while p < n and len(out) < out_len:
        if nb == 0:
            flag = src[p]
            p += 1
            nb = 8
        lit = flag & 0x80
        flag = (flag << 1) & 0xFF
        nb -= 1
        if lit:
            if p >= n:
                break
            out.append(src[p])
            p += 1
            continue
        if nb == 0:
            if p >= n:
                break
            flag = src[p]
            p += 1
            nb = 8
        long = flag & 0x80
        flag = (flag << 1) & 0xFF
        nb -= 1
        if not long:
            ln = 0
            for _ in range(2):
                if nb == 0:
                    if p >= n:
                        return bytes(out)
                    flag = src[p]
                    p += 1
                    nb = 8
                ln = (ln << 1) | (1 if flag & 0x80 else 0)
                flag = (flag << 1) & 0xFF
                nb -= 1
            ln += 2
            if p >= n:
                break
            pos = src[p] - 256
            p += 1
        else:
            if p + 2 > n:
                break
            pos = ((src[p] << 8) | src[p + 1]) - 0x10000
            p += 2
            ln = pos & 7
            pos >>= 3
            if ln == 0:
                if p >= n:
                    break
                ln = src[p] + 1
                p += 1
            else:
                ln += 2
        pos += len(out)
        if pos < 0:
            raise ValueError("PRS copy before the start of the output")
        for i in range(ln):
            if len(out) >= out_len:
                break
            out.append(out[pos + i])
    return bytes(out)


def read(data: bytes, m: Member) -> bytes:
    raw = data[m.offset : m.offset + m.packed]
    if m.packed == m.size:
        return raw
    return prs_decompress(raw, m.size)
