"""Sega PRS (LZ77 with a bit-flag stream) as used by Sonic Team / Sega GameCube titles
(Shadow the Hedgehog .one members, Sonic Adventure 2: Battle .prs).  Flags are read
LSB-first from flag bytes: 1 = literal; 0,0 = short copy (2 flag bits + 2 length, offset =
byte - 256); 0,1 = long copy (little-endian u16: offset = (v >> 3) - 0x2000, length = (v & 7)
+ 2, or 0 -> next byte + 1); a long copy with offset 0 and length 0 ends the stream."""

from __future__ import annotations


def decompress(src: bytes, limit: int | None = None) -> bytes:
    out = bytearray()
    p = 0
    n = len(src)
    flag = 0
    nb = 0

    def bit() -> int:
        nonlocal p, flag, nb
        if nb == 0:
            if p >= n:
                raise ValueError("PRS: flag byte past the end")
            flag = src[p]
            p += 1
            nb = 8
        b = flag & 1
        flag >>= 1
        nb -= 1
        return b

    while p < n:
        if bit():
            out.append(src[p])
            p += 1
        elif bit():
            if p + 2 > n:
                break
            v = src[p] | (src[p + 1] << 8)
            p += 2
            off = (v >> 3) - 0x2000
            ln = v & 7
            if v == 0:
                break
            if ln == 0:
                if p >= n:
                    break
                ln = src[p] + 1
                p += 1
            else:
                ln += 2
            if -off > len(out):
                raise ValueError("PRS: back-reference before start")
            start = len(out) + off
            for k in range(ln):
                out.append(out[start + k])
        else:
            ln = (bit() << 1 | bit()) + 2
            if p >= n:
                break
            off = src[p] - 256
            p += 1
            if -off > len(out):
                raise ValueError("PRS: back-reference before start")
            start = len(out) + off
            for k in range(ln):
                out.append(out[start + k])
        if limit is not None and len(out) >= limit:
            break
    return bytes(out)
