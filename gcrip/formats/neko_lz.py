"""Neko Entertainment's LZ - the ``.GCN`` / ``.pc`` level files of Cocoto Kart Racer, Cocoto
Funfair and Cocoto Platform Jumper (``L%d.GCN``, ``L%dGFX.PC``, ``L%dTIN.PC`` in the DOL's
format strings).

Header ``u32 packed bytes, u32 unpacked bytes`` (big-endian; the packed count is the file
size less 8), then LZSS: a flag byte, bits LSB-first, **1 = literal byte, 0 = a 2-byte
reference** ``b0, b1`` with distance ``(b0 | (b1 & 0xf0) << 4) + 1`` and length
``(b1 & 0xf) + 3``, the window pre-filled with zeros so a reference before the start copies
zeros.  Found by sweeping the flag order, literal bit, field packing and minimum length on a
2,228-byte ``TIN.PC`` - four variants land on the exact unpacked size, one gives structured
output (``0a 00 10`` records, ascending index runs); that one also unpacks every ``.GCN`` and
``.pc`` on the three discs to exactly its declared size (3.4-5.9 MB in, 5.6-9.7 MB out).

The unpacked ``.GCN`` is one ``MWLD`` chunk (``u32 3, u32 4, u32 bytes, "MWLD"``) - a serialised
world with no GX display lists and no float runs (quantised, unread); ``GFX.PC`` is raw
texture data.
"""

from __future__ import annotations

import struct

MAX_UNPACKED = 64 << 20
HEADER = 8


def is_packed(head: bytes, size: int) -> bool:
    if len(head) < HEADER or size < HEADER + 2:
        return False
    packed, unpacked = struct.unpack_from(">2I", head, 0)
    return packed == size - HEADER and packed < unpacked <= MAX_UNPACKED


def unpack(data: bytes) -> bytes | None:
    if not is_packed(data[:HEADER], len(data)):
        return None
    packed, unpacked = struct.unpack_from(">2I", data, 0)
    src = data[HEADER : HEADER + packed]
    out = bytearray()
    i, n = 0, len(src)
    while len(out) < unpacked and i < n:
        flags = src[i]
        i += 1
        for k in range(8):
            if len(out) >= unpacked or i >= n:
                break
            if (flags >> k) & 1:
                out.append(src[i])
                i += 1
            else:
                if i + 2 > n:
                    return None
                b0, b1 = src[i], src[i + 1]
                i += 2
                dist = (b0 | ((b1 & 0xF0) << 4)) + 1
                length = (b1 & 0xF) + 3
                if dist > len(out):
                    zeros = min(length, dist - len(out))
                    out.extend(bytes(zeros))
                    length -= zeros
                for _ in range(length):
                    out.append(out[-dist])
    return bytes(out) if len(out) == unpacked else None
