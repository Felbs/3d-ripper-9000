"""EA Redwood Shores "rcmp" - the LZ behind ``Rdat`` blocks in Tiger Woods PGA Tour 2003, 2004
and 2005's ``SHOC`` archives (``Golf/Rcmp/rcmp_mad_codec.c`` in the executable's path strings).

Ported from Tiger Woods 2005 Disc 1's DOL: the ``SHOC`` chunk reader at 0x80188b44 hands an
``Rdat`` block's payload (after a u32 unpacked size) to the routine at 0x80188834 with that size,
and this is that routine.  Every control is a big-endian 16-bit word ``w``:

  (w & 0x8800) == 0x8800   k = bits 12-14
      k == 0               literal run of (w & 0x7ff) bytes
      k != 0               run: repeat the byte (k | ((w >> 5) & 0x38)) back, (w & 0xff) + 3 times
  otherwise                copy: length = bits 12-14 (+3; 7 means the next byte + 7 + 3),
                           offset = w & 0xfff
      bit 15 clear         forward copy from offset back
      bit 15 set           mirrored copy: bytes at (out - offset + 2), walking backwards

Decoding stops when the declared size is reached.  The 2005 course archive checks out block
for block: 511 of 511 ``Rdat`` blocks land on their declared sizes, and the terrain resource
assembles to exactly its ``SHDR`` size, opening ``OBG `` / ``ARRA`` like the stored 06 copy.
No block on that disc emits an overlapping forward copy, so the game's 16-byte gulp copy
and byte-at-a-time LZ agree.
"""

from __future__ import annotations


class RcmpError(ValueError):
    pass


def unpack(src: bytes, size: int) -> bytes:
    out = bytearray()
    p = 0
    n_src = len(src)
    while len(out) < size:
        if p + 2 > n_src:
            raise RcmpError("rcmp stream ends before the declared size")
        w = (src[p] << 8) | src[p + 1]
        p += 2
        if (w & 0x8800) == 0x8800:
            k = (w >> 12) & 7
            if k == 0:
                n = w & 0x7FF
                if p + n > n_src:
                    raise RcmpError("literal run past the end of the stream")
                out += src[p : p + n]
                p += n
            else:
                dist = k | ((w >> 5) & 0x38)
                n = (w & 0xFF) + 3
                if dist > len(out):
                    raise RcmpError("run source before the start of the output")
                out += bytes((out[-dist],)) * n
            continue
        code = (w >> 12) & 7
        off = w & 0xFFF
        if code == 7:
            if p >= n_src:
                raise RcmpError("long copy length past the end of the stream")
            code = src[p] + 7
            p += 1
        n = code + 3
        if w & 0x8000:
            s = len(out) - off + 2
            if s - n + 1 < 0 or s >= len(out):
                raise RcmpError("mirrored copy outside the output")
            for i in range(n):
                out.append(out[s - i])
        else:
            if off == 0 or off > len(out):
                raise RcmpError("copy source before the start of the output")
            if off >= n:
                out += out[-off : len(out) - off + n]
            else:
                for _ in range(n):
                    out.append(out[-off])
    if len(out) != size:
        raise RcmpError(f"decoded {len(out)} bytes for a declared {size}")
    return bytes(out)
