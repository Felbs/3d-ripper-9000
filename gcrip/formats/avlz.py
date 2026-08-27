"""Amusement Vision ".lz" archives (F-Zero GX, Super Monkey Ball 2 backgrounds).

Header (little-endian, unlike everything else on the disc):
  u32 payload size (file size minus this 8-byte header)
  u32 decompressed size
Payload: Okumura LZSS - a flag byte, then 8 items LSB first; a set bit is one literal
byte, a clear bit is a 2-byte back-reference `lo, hi`: ring offset = lo | (hi & 0xF0) << 4,
length = (hi & 0x0F) + 3, read from a 4096-byte ring that starts zeroed with the write
cursor at 0xFEE (so references into the untouched area produce zeros, which the stock
encoder uses for the runs of zero bytes at the start of a GMA).
"""

from __future__ import annotations

import struct

RING = 0x1000
START = 0xFEE


class AvlzError(Exception):
    pass


def looks_like(data: bytes, size: int | None = None) -> bool:
    """Cheap sniff on the header: sizes must be plausible for the file."""
    if len(data) < 12:
        return False
    payload, full = struct.unpack_from("<II", data, 0)
    if size is not None and payload != size - 8:
        return False
    return 0 < payload <= full <= 0x10000000


def decompress(data: bytes) -> bytes:
    if len(data) < 8:
        raise AvlzError("truncated LZ header")
    payload, full = struct.unpack_from("<II", data, 0)
    src = data[8 : 8 + payload]
    out = bytearray(full)
    ring = bytearray(RING)
    r = START
    pos = 0
    o = 0
    n = len(src)
    while o < full and pos < n:
        flags = src[pos]
        pos += 1
        for _ in range(8):
            if o >= full or pos >= n:
                break
            if flags & 1:
                c = src[pos]
                pos += 1
                out[o] = c
                o += 1
                ring[r] = c
                r = (r + 1) & (RING - 1)
            else:
                if pos + 1 >= n:
                    break
                lo, hi = src[pos], src[pos + 1]
                pos += 2
                off = lo | (hi & 0xF0) << 4
                length = (hi & 0x0F) + 3
                for k in range(length):
                    if o >= full:
                        break
                    c = ring[(off + k) & (RING - 1)]
                    out[o] = c
                    o += 1
                    ring[r] = c
                    r = (r + 1) & (RING - 1)
            flags >>= 1
    if o != full:
        raise AvlzError(f"LZ stream ended early: {o} of {full} bytes")
    return bytes(out)


def compress(data: bytes) -> bytes:
    """Encoder for the test round-trip: greedy longest match, same ring geometry."""
    n = len(data)
    ring = bytearray(RING)
    r = START
    out = bytearray()
    i = 0
    while i < n:
        flags = 0
        items = bytearray()
        for bit in range(8):
            if i >= n:
                break
            best_len, best_off = 0, 0
            if i + 3 <= n:
                for off in range(RING):
                    length = 0
                    while (
                        length < 18
                        and i + length < n
                        and ring[(off + length) & (RING - 1)] == data[i + length]
                    ):
                        # a match that runs into bytes written during this copy is fine
                        # for the decoder only if the ring is updated as it goes; keep it
                        # simple and never let the match overlap the write cursor
                        if (off + length) & (RING - 1) == r:
                            break
                        length += 1
                    if length > best_len:
                        best_len, best_off = length, off
                        if length == 18:
                            break
            if best_len >= 3:
                items.append(best_off & 0xFF)
                items.append((best_off >> 4) & 0xF0 | (best_len - 3))
                for k in range(best_len):
                    ring[r] = data[i + k]
                    r = (r + 1) & (RING - 1)
                i += best_len
            else:
                flags |= 1 << bit
                items.append(data[i])
                ring[r] = data[i]
                r = (r + 1) & (RING - 1)
                i += 1
        out.append(flags)
        out += items
    return struct.pack("<II", len(out), n) + bytes(out)
