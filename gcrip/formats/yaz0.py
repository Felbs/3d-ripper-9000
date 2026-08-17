"""Yaz0 (Nintendo LZ77 variant) decompression.

Header: 'Yaz0', u32 BE decompressed size, 8 reserved bytes, then the stream.
Stream: a code byte, then 8 chunks (MSB first). Bit set = literal byte.
Bit clear = back-reference: two bytes  NR RR  -> dist = RRR + 1,
count = N + 2; if N == 0 a third byte follows and count = byte + 0x12.
"""

from __future__ import annotations

MAGIC = b"Yaz0"


def is_yaz0(data: bytes) -> bool:
    return data[:4] == MAGIC


def decompressed_size(data: bytes) -> int:
    return int.from_bytes(data[4:8], "big")


def decompress(src: bytes) -> bytes:
    if src[:4] != MAGIC:
        raise ValueError("not Yaz0 data")
    dst_size = int.from_bytes(src[4:8], "big")
    dst = bytearray(dst_size)
    src_len = len(src)
    sp = 16
    dp = 0
    while dp < dst_size:
        if sp >= src_len:
            raise ValueError("Yaz0 stream truncated")
        code = src[sp]
        sp += 1
        bit = 0x80
        while bit and dp < dst_size:
            if code & bit:
                dst[dp] = src[sp]
                sp += 1
                dp += 1
            else:
                b1 = src[sp]
                b2 = src[sp + 1]
                sp += 2
                dist = ((b1 & 0x0F) << 8 | b2) + 1
                n = b1 >> 4
                if n == 0:
                    n = src[sp] + 0x12
                    sp += 1
                else:
                    n += 2
                if n > dst_size - dp:
                    n = dst_size - dp
                start = dp - dist
                if start < 0:
                    raise ValueError("Yaz0 back-reference before start of output")
                if dist >= n:
                    dst[dp : dp + n] = dst[start : start + n]
                else:
                    # overlapping copy: repeat the `dist`-byte pattern
                    pattern = dst[start:dp]
                    reps = pattern * (n // dist + 1)
                    dst[dp : dp + n] = reps[:n]
                dp += n
            bit >>= 1
    return bytes(dst)
