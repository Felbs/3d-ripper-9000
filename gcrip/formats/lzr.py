"""Radical Entertainment's LZR / LZRF byte-oriented LZ77 streams and the ``P3DZ`` wrapper
around compressed Pure3D files (Simpsons Hit & Run, Hulk, Crash Tag Team Racing, ...).

``P3DZ``: ``"P3DZ" | u32 LE unpacked size`` then blocks of ``u32 LE packed | u32 LE
unpacked | packed bytes``; each block is an independent LZR (or LZRF) stream.

LZR: control byte ``c``; ``c <= 15`` is a literal run of ``c`` bytes (``0`` = 15 + an
extension count read as 255-continued bytes), ``c > 15`` is a match of ``c & 15`` bytes
(``0`` = 15 + extension) at offset ``(c >> 4) | (next byte << 4)``.
LZRF: ``c & 0x80`` = match of ``c & 0x7f`` bytes (``0`` = 127 + extension) at a 1- or
2-byte offset (``0x80`` flag -> ``(high << 4) + (low & 0x7f)``), else a literal run of ``c``
bytes (``0`` = 127 + extension).
"""

from __future__ import annotations

import struct

MAGIC = b"P3DZ"


class LzrError(ValueError):
    pass


def _extension(src: bytes, i: int) -> tuple[int, int]:
    """255-continued extension count starting at src[i]: (count, new index)."""
    total = 0
    while True:
        if i >= len(src):
            raise LzrError("truncated length extension")
        v = src[i]
        i += 1
        if v:
            return total + v, i
        total += 255


def _copy(out: bytearray, offset: int, count: int) -> None:
    if offset <= 0 or offset > len(out):
        raise LzrError(f"bad match offset {offset} at {len(out)}")
    if offset >= count:
        out += out[-offset : len(out) - offset + count]
    else:
        for _ in range(count):
            out.append(out[-offset])


def lzr(src: bytes, size: int) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while len(out) < size:
        if i >= n:
            raise LzrError("truncated LZR stream")
        c = src[i]
        i += 1
        if c > 15:
            count = c & 15
            if count == 0:
                ext, i = _extension(src, i)
                count = 15 + ext
            if i >= n:
                raise LzrError("truncated LZR offset")
            offset = (c >> 4) | (src[i] << 4)
            i += 1
            _copy(out, offset, count)
        else:
            run = c
            if run == 0:
                ext, i = _extension(src, i)
                run = 15 + ext
            if i + run > n:
                raise LzrError("truncated LZR literals")
            out += src[i : i + run]
            i += run
    if i != n or len(out) != size:
        raise LzrError("LZR stream length mismatch")
    return bytes(out)


def lzrf(src: bytes, size: int) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while len(out) < size:
        if i >= n:
            raise LzrError("truncated LZRF stream")
        c = src[i]
        i += 1
        if c & 0x80:
            count = c & 0x7F
            if count == 0:
                ext, i = _extension(src, i)
                count = 127 + ext
            if i >= n:
                raise LzrError("truncated LZRF offset")
            oc = src[i]
            i += 1
            if oc & 0x80:
                if i >= n:
                    raise LzrError("truncated LZRF long offset")
                offset = (src[i] << 4) + (oc & 0x7F)
                i += 1
            else:
                offset = oc
            _copy(out, offset, count)
        else:
            run = c
            if run == 0:
                ext, i = _extension(src, i)
                run = 127 + ext
            if i + run > n:
                raise LzrError("truncated LZRF literals")
            out += src[i : i + run]
            i += run
    if i != n or len(out) != size:
        raise LzrError("LZRF stream length mismatch")
    return bytes(out)


def is_p3dz(head: bytes) -> bool:
    return head[:4] == MAGIC


def decompress_p3dz(data: bytes) -> bytes:
    """The Pure3D file inside a ``P3DZ`` wrapper (blocks tried as LZR, then LZRF)."""
    if not is_p3dz(data) or len(data) < 16:
        raise LzrError("not a P3DZ file")
    total = struct.unpack_from("<I", data, 4)[0]
    out = bytearray()
    o = 8
    while len(out) < total:
        if o + 8 > len(data):
            raise LzrError("truncated P3DZ block table")
        packed, unpacked = struct.unpack_from("<II", data, o)
        o += 8
        if packed == 0 or unpacked == 0 or o + packed > len(data):
            raise LzrError("bad P3DZ block")
        block = data[o : o + packed]
        try:
            out += lzr(block, unpacked)
        except LzrError:
            out += lzrf(block, unpacked)
        o += packed
    if len(out) != total:
        raise LzrError("P3DZ size mismatch")
    return bytes(out)
