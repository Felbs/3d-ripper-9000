"""PRS - Sega's LZ77 variant (Saturn/Dreamcast/Naomi; Sonic Adventure, PSO, Skies ...).

Bit-flag driven: a control byte gives 8 flags, LSB first; 1 = literal byte.
0 then flag 1 = long copy: two bytes; offset = (b1 << 5 | b0 >> 3) - 0x2000 (signed,
relative), length = (b0 & 7) + 2, or if that is 2 a third byte holds length - 1.
0 then flag 0 = short copy: two flag bits give length - 2 (MSB first), then one byte
offset - 0x100. Length 0 in a long copy with a zero offset terminates.
"""

from __future__ import annotations


class _Bits:
    __slots__ = ("data", "pos", "flag", "count")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.flag = 0
        self.count = 0

    def bit(self) -> int:
        if self.count == 0:
            self.flag = self.data[self.pos]
            self.pos += 1
            self.count = 8
        b = self.flag & 1
        self.flag >>= 1
        self.count -= 1
        return b

    def byte(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v


def decompress(data: bytes, max_out: int = 512 << 20) -> bytes:
    out = bytearray()
    bits = _Bits(data)
    n = len(data)
    try:
        while bits.pos < n:
            if bits.bit():
                out.append(bits.byte())
                continue
            if bits.bit():
                b0 = bits.byte()
                b1 = bits.byte()
                if b0 == 0 and b1 == 0:
                    break
                offset = ((b1 << 8) | b0) >> 3
                length = b0 & 7
                if length == 0:
                    length = bits.byte() + 1
                else:
                    length += 2
                offset -= 0x2000
            else:
                length = (bits.bit() << 1 | bits.bit()) + 2
                offset = bits.byte() - 0x100
            start = len(out) + offset
            if start < 0:
                raise ValueError("PRS: back-reference before start")
            for i in range(length):
                out.append(out[start + i])
            if len(out) > max_out:
                raise ValueError("PRS: output too large")
    except IndexError as e:
        raise ValueError("PRS: truncated stream") from e
    return bytes(out)


def looks_like_prs(name: str) -> bool:
    return name.lower().endswith(".prs")
