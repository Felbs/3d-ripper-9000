"""Neko Entertainment's LZ - the ``.GCN`` / ``.pc`` level files of Cocoto Kart Racer, Cocoto
Funfair and Cocoto Platform Jumper (``L%d.GCN``, ``L%dGFX.PC``, ``L%dTIN.PC`` in the DOL's
format strings).

Header ``u32 packed bytes, u32 unpacked bytes`` (big-endian; the packed count is the file
size less 8), then **Okumura's LZSS.C** exactly: a flag byte, bits LSB-first, 1 = literal,
0 = a 2-byte reference ``b0, b1`` naming an *absolute index* ``b0 | (b1 & 0xf0) << 4`` into
a 4,096-byte ring buffer that starts zero-filled with the write position at 4,078, and a
length ``(b1 & 0xf) + 3``.  Found by sweeping flag order, literal bit and field packing on a
2,228-byte ``TIN.PC``; the absolute-index reading (over a plain distance) was settled on Baten
Kaitos's text files, which the same routine unpacks and where a distance reading garbles
"Mana Stone".  Every ``.GCN`` and ``.pc`` on the three Cocoto discs unpacks to exactly its
declared size (3.4-5.9 MB in, 5.6-9.7 MB out).

The unpacked ``.GCN`` is one ``MWLD`` chunk (``u32 3, u32 4, u32 bytes, "MWLD"``) - a serialised
world with no GX display lists and no float runs (quantised, unread); ``GFX.PC`` is raw
texture data.
"""

from __future__ import annotations

import struct

MAX_UNPACKED = 64 << 20
HEADER = 8
RING = 4096
MAX_MATCH = 18
THRESHOLD = 2


def is_packed(head: bytes, size: int) -> bool:
    if len(head) < HEADER or size < HEADER + 2:
        return False
    packed, unpacked = struct.unpack_from(">2I", head, 0)
    return packed == size - HEADER and packed < unpacked <= MAX_UNPACKED


def unpack(data: bytes) -> bytes | None:
    if not is_packed(data[:HEADER], len(data)):
        return None
    packed, unpacked = struct.unpack_from(">2I", data, 0)
    blob = lzss(data[HEADER : HEADER + packed], unpacked)
    return blob if len(blob) == unpacked else None


def lzss(src: bytes, unpacked: int | None = None) -> bytes:
    """Okumura's LZSS.C: a 4,096-byte ring buffer of zeros written from index 4,078, flag
    bits LSB-first, 1 = literal, 0 = ``b0, b1`` naming an absolute ring index
    ``b0 | (b1 & 0xf0) << 4`` and a length ``(b1 & 0xf) + 3``.  Shared by Baten Kaitos's
    text and data files (no header there)."""
    ring = bytearray(RING)
    r = RING - MAX_MATCH
    out = bytearray()
    i, n = 0, len(src)
    while i < n and (unpacked is None or len(out) < unpacked):
        flags = src[i]
        i += 1
        for k in range(8):
            if i >= n or (unpacked is not None and len(out) >= unpacked):
                break
            if (flags >> k) & 1:
                c = src[i]
                i += 1
                out.append(c)
                ring[r] = c
                r = (r + 1) % RING
            else:
                if i + 2 > n:
                    return bytes(out)
                b0, b1 = src[i], src[i + 1]
                i += 2
                idx = b0 | ((b1 & 0xF0) << 4)
                for j in range((b1 & 0xF) + THRESHOLD + 1):
                    c = ring[(idx + j) % RING]
                    out.append(c)
                    ring[r] = c
                    r = (r + 1) % RING
    return bytes(out)
