"""RefPack: EA's LZ77 variant (the 0x10FB family), used inside BIG/VIV archives and FSH
shapes across EA's catalogue.

Header (big-endian): u16 flags, where 0xFB in the low byte is the signature; bit 0x8000
selects 32-bit sizes (else 24-bit), bit 0x0100 says a compressed-size field precedes the
decompressed size. Then the command stream:

  00-7F  2 bytes: literal (b0 & 3), copy ((b0 & 0x1C) >> 2) + 3
                  from ((b0 & 0x60) << 3 | b1) + 1 back
  80-BF  3 bytes: literal (b1 >> 6) & 3, copy (b0 & 0x3F) + 4
                  from ((b1 & 0x3F) << 8 | b2) + 1 back
  C0-DF  4 bytes: literal (b0 & 3), copy ((b0 & 0x0C) << 6 | b3) + 5
                  from ((b0 & 0x10) << 12 | b1 << 8 | b2) + 1 back
  E0-FB  1 byte : literal ((b0 & 0x1F) + 1) * 4
  FC-FF  1 byte : literal (b0 & 3), then stop
"""

from __future__ import annotations

import struct


def is_refpack(data: bytes) -> bool:
    if len(data) < 5:
        return False
    return data[1] == 0xFB and (data[0] & 0x3E) == 0x10


def sizes(data: bytes) -> tuple[int, int | None, int]:
    """(decompressed size, compressed size or None, offset of the command stream)."""
    flags = data[0]
    pos = 2
    wide = 4 if flags & 0x80 else 3
    compressed = None
    if flags & 0x01:
        compressed = int.from_bytes(data[pos : pos + wide], "big")
        pos += wide
    decompressed = int.from_bytes(data[pos : pos + wide], "big")
    pos += wide
    return decompressed, compressed, pos


def decompress(data: bytes) -> bytes:
    if not is_refpack(data):
        raise ValueError("not a RefPack stream")
    out_len, _comp, pos = sizes(data)
    out = bytearray()
    n = len(data)
    while pos < n:
        b0 = data[pos]
        if b0 < 0x80:
            b1 = data[pos + 1]
            pos += 2
            lit = b0 & 3
            cnt = ((b0 & 0x1C) >> 2) + 3
            back = ((b0 & 0x60) << 3 | b1) + 1
        elif b0 < 0xC0:
            b1, b2 = data[pos + 1], data[pos + 2]
            pos += 3
            lit = (b1 >> 6) & 3
            cnt = (b0 & 0x3F) + 4
            back = ((b1 & 0x3F) << 8 | b2) + 1
        elif b0 < 0xE0:
            b1, b2, b3 = data[pos + 1], data[pos + 2], data[pos + 3]
            pos += 4
            lit = b0 & 3
            cnt = ((b0 & 0x0C) << 6 | b3) + 5
            back = ((b0 & 0x10) << 12 | b1 << 8 | b2) + 1
        elif b0 < 0xFC:
            pos += 1
            lit = ((b0 & 0x1F) + 1) * 4
            cnt = 0
            back = 0
        else:
            pos += 1
            lit = b0 & 3
            out += data[pos : pos + lit]
            break
        if lit:
            out += data[pos : pos + lit]
            pos += lit
        if cnt:
            start = len(out) - back
            if start < 0:
                raise ValueError("RefPack back-reference before start of output")
            if back >= cnt:
                out += out[start : start + cnt]
            else:  # overlapping copy: byte by byte
                for _ in range(cnt):
                    out.append(out[start])
                    start += 1
    if out_len and len(out) != out_len:
        raise ValueError(f"RefPack size mismatch: header {out_len}, got {len(out)}")
    return bytes(out)


def compress_literal(data: bytes) -> bytes:
    """Encode `data` as a RefPack stream of literals only (test helper / round-trip)."""
    out = bytearray(struct.pack(">H", 0x10FB) + len(data).to_bytes(3, "big"))
    pos = 0
    while len(data) - pos >= 4:
        n = min((len(data) - pos) // 4, 28) * 4
        out.append(0xE0 + n // 4 - 1)
        out += data[pos : pos + n]
        pos += n
    rest = data[pos:]
    out.append(0xFC + len(rest))
    out += rest
    return bytes(out)
