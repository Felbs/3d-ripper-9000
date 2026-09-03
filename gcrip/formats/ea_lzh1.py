"""EA GCMP.LIB "LZH1" - the codec behind TERF ``comp5`` members (Madden, NCAA, NFL Street, NASCAR).

Ported from Madden NFL 06's DOL.  The codec table at 0x805816c0 registers ``NONE``, ``RLE1``,
``HUFF``, ``LZM1``, ``LZH1`` in that order, so TERF's COMP type 5 is LZH1; its decoder is the
state machine at 0x804f82a4 / 0x804f8eec / 0x804f945c with the bit reader at 0x804f9c44.

The stream (bits are read MSB-first, bytes big-endian):

  repeat:
    1 bit            0 = a block follows, 1 = end of stream
    if end:          32 bits Adler-32 of the whole output; stop
    285 x 4 bits     code lengths of the literal/length alphabet (0 = unused)
    30 x 4 bits      code lengths of the distance alphabet
    canonical Huffman codes are assigned by deflate's rule (shorter codes first, then by
    symbol); a code is read one bit at a time from the MSB-first stream
    symbols until 256:
      < 256          literal byte
      256            end of block
      257 + i        match: length i + 3 for i < 8, else LEN_BASE[i] + LEN_EXTRA[i] bits,
                     and i = 27 is a bare 227 (the longest match)
      then a distance symbol d: d + 1 for d < 4, else DIST_BASE[d] + DIST_EXTRA[d] bits

The length and distance tables are deflate's, the window is 32 KiB, the maximum match 227.
"""

from __future__ import annotations

import zlib

LEN_EXTRA = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 3 + [0]
LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 228]
DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]
DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073,
             4097, 6145, 8193, 12289, 16385, 24577]
LITERALS = 285
DISTANCES = 30
MAX_BITS = 15


class Lzh1Error(ValueError):
    pass


def _canonical(lengths: list[int]) -> tuple[list[int], int]:
    """Lookup table indexed by the next MAX_BITS bits -> symbol << 4 | length, plus max length."""
    counts = [0] * (MAX_BITS + 1)
    for n in lengths:
        counts[n] += 1
    counts[0] = 0
    code = 0
    first = [0] * (MAX_BITS + 1)
    for n in range(1, MAX_BITS + 1):
        code = (code + counts[n - 1]) << 1
        first[n] = code
    table = [0] * (1 << MAX_BITS)
    longest = 0
    for sym, n in enumerate(lengths):
        if not n:
            continue
        c = first[n]
        first[n] += 1
        if c >= 1 << n:
            raise Lzh1Error("over-subscribed Huffman code")
        entry = sym << 4 | n
        start = c << (MAX_BITS - n)
        for k in range(start, start + (1 << (MAX_BITS - n))):
            table[k] = entry
        longest = max(longest, n)
    return table, longest


def unpack(data: bytes, expected: int | None = None, verify: bool = True) -> bytes:
    """Decode one LZH1 stream.  ``expected`` (TERF's declared size) bounds the output."""
    out = bytearray()
    pos = 0
    buf = 0
    cnt = 0
    n = len(data)
    limit = expected if expected is not None else 1 << 31

    def fill(need: int) -> None:
        nonlocal pos, buf, cnt
        while cnt < need:
            buf = (buf << 8) | (data[pos] if pos < n else 0)
            pos += 1
            cnt += 8

    def bits(k: int) -> int:
        nonlocal buf, cnt
        if cnt < k:
            fill(k)
        cnt -= k
        v = buf >> cnt
        buf &= (1 << cnt) - 1
        return v

    while True:
        if pos > n + 4:
            raise Lzh1Error("ran off the end of the stream")
        if bits(1):
            tail = bits(32)
            if verify and zlib.adler32(bytes(out)) != tail:
                raise Lzh1Error("Adler-32 mismatch")
            if expected is not None and len(out) != expected:
                raise Lzh1Error(f"decoded {len(out)} bytes, TERF declared {expected}")
            return bytes(out)
        lit, _ = _canonical([bits(4) for _ in range(LITERALS)])
        dist, _ = _canonical([bits(4) for _ in range(DISTANCES)])
        while True:
            if cnt < MAX_BITS:
                fill(MAX_BITS)
            e = lit[buf >> (cnt - MAX_BITS)]
            k = e & 15
            if not k:
                raise Lzh1Error("invalid literal/length code")
            cnt -= k
            buf &= (1 << cnt) - 1
            sym = e >> 4
            if sym < 256:
                out.append(sym)
                continue
            if sym == 256:
                break
            i = sym - 257
            if i < 8:
                length = i + 3
            elif LEN_EXTRA[i]:
                length = LEN_BASE[i] + bits(LEN_EXTRA[i])
            else:
                length = 227
            if cnt < MAX_BITS:
                fill(MAX_BITS)
            e = dist[buf >> (cnt - MAX_BITS)]
            k = e & 15
            if not k:
                raise Lzh1Error("invalid distance code")
            cnt -= k
            buf &= (1 << cnt) - 1
            d = e >> 4
            distance = d + 1 if d < 4 else DIST_BASE[d] + bits(DIST_EXTRA[d])
            if distance > len(out):
                raise Lzh1Error("distance before the start of the output")
            if len(out) + length > limit:
                raise Lzh1Error("output longer than declared")
            if distance >= length:
                out += out[-distance : len(out) - distance + length]
            else:
                for _ in range(length):
                    out.append(out[-distance])
            if pos > n + 4:
                raise Lzh1Error("ran off the end of the stream")

