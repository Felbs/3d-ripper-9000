"""Yay0 (older Nintendo LZ77 variant, used by .szp) decompression.

Header: 'Yay0', u32 BE decompressed size, u32 BE link-table offset,
u32 BE literal/chunk data offset. Mask words (u32 BE) start at 0x10.
Mask bit set (MSB first) = literal from chunk data. Bit clear = link (u16 BE):
dist = (link & 0xFFF) + 1, count = link >> 12; count += 2, or if 0,
count = next chunk byte + 0x12.
"""

from __future__ import annotations

MAGIC = b"Yay0"


def is_yay0(data: bytes) -> bool:
    return data[:4] == MAGIC


def decompressed_size(data: bytes) -> int:
    return int.from_bytes(data[4:8], "big")


def decompress(src: bytes) -> bytes:
    if src[:4] != MAGIC:
        raise ValueError("not Yay0 data")
    dst_size = int.from_bytes(src[4:8], "big")
    link_pos = int.from_bytes(src[8:12], "big")
    chunk_pos = int.from_bytes(src[12:16], "big")
    dst = bytearray(dst_size)
    mask_pos = 16
    dp = 0
    while dp < dst_size:
        mask = int.from_bytes(src[mask_pos : mask_pos + 4], "big")
        mask_pos += 4
        for _ in range(32):
            if dp >= dst_size:
                break
            if mask & 0x80000000:
                dst[dp] = src[chunk_pos]
                chunk_pos += 1
                dp += 1
            else:
                link = src[link_pos] << 8 | src[link_pos + 1]
                link_pos += 2
                dist = (link & 0x0FFF) + 1
                n = link >> 12
                if n == 0:
                    n = src[chunk_pos] + 0x12
                    chunk_pos += 1
                else:
                    n += 2
                if n > dst_size - dp:
                    n = dst_size - dp
                start = dp - dist
                if start < 0:
                    raise ValueError("Yay0 back-reference before start of output")
                if dist >= n:
                    dst[dp : dp + n] = dst[start : start + n]
                else:
                    pattern = dst[start:dp]
                    dst[dp : dp + n] = (pattern * (n // dist + 1))[:n]
                dp += n
            mask = (mask << 1) & 0xFFFFFFFF
    return bytes(dst)
