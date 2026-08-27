"""LZO1X decompression (pure Python) and the block framing Ubisoft's Jade engine
puts around it.

Jade's binarized "BIN" files (ROOT/Bin/ffxxxxxx.bin inside a .bf big file) are a
sequence of blocks:

    u32 size        decompressed size of this block (0 = end)
    u32 zsize       stored size; == size means the block is stored raw
    u8[zsize]       LZO1X stream (or raw bytes)

Sizes are little-endian on every platform, GameCube included. The LZO1X format is
the standard one (minilzo); the decoder below follows lzo1x_decompress_safe.
"""

from __future__ import annotations

import struct


class LzoError(ValueError):
    pass


def lzo1x_decompress(src: bytes, out_size: int | None = None) -> bytes:  # noqa: C901
    """Decode one LZO1X stream. `out_size`, when known, stops the decoder early
    (streams written without an end marker)."""
    out = bytearray()
    ip = 0
    n = len(src)
    if n == 0:
        return b""
    t = src[ip]
    first_literal_run = False
    match_next = False
    if t > 17:
        ip += 1
        t -= 17
        if t < 4:
            match_next = True
        else:
            out += src[ip : ip + t]
            ip += t
            first_literal_run = True
    try:
        while True:
            if out_size is not None and len(out) >= out_size:
                return bytes(out[:out_size])
            if not match_next and not first_literal_run:
                t = src[ip]
                ip += 1
                if t < 16:
                    if t == 0:
                        while src[ip] == 0:
                            t += 255
                            ip += 1
                        t += 15 + src[ip]
                        ip += 1
                    t += 3
                    out += src[ip : ip + t]
                    ip += t
                    first_literal_run = True
            if first_literal_run:
                first_literal_run = False
                t = src[ip]
                ip += 1
                if t < 16:
                    m_pos = len(out) - (1 + 0x0800) - (t >> 2) - (src[ip] << 2)
                    ip += 1
                    if m_pos < 0:
                        raise LzoError("bad match position")
                    for _ in range(3):
                        out.append(out[m_pos])
                        m_pos += 1
                    t = src[ip - 2] & 3
                    if t == 0:
                        continue
                    match_next = True
            if match_next:
                match_next = False
                out += src[ip : ip + t]
                ip += t
                t = src[ip]
                ip += 1
            # match loop
            while True:
                if t >= 64:
                    m_pos = len(out) - 1 - ((t >> 2) & 7) - (src[ip] << 3)
                    ip += 1
                    ln = (t >> 5) + 1
                elif t >= 32:
                    t &= 31
                    if t == 0:
                        while src[ip] == 0:
                            t += 255
                            ip += 1
                        t += 31 + src[ip]
                        ip += 1
                    m_pos = len(out) - 1 - (src[ip] >> 2) - (src[ip + 1] << 6)
                    ip += 2
                    ln = t + 2
                elif t >= 16:
                    m_pos = len(out) - ((t & 8) << 11)
                    t &= 7
                    if t == 0:
                        while src[ip] == 0:
                            t += 255
                            ip += 1
                        t += 7 + src[ip]
                        ip += 1
                    m_pos -= (src[ip] >> 2) + (src[ip + 1] << 6)
                    ip += 2
                    if m_pos == len(out):
                        return bytes(out)  # end-of-stream marker
                    m_pos -= 0x4000
                    ln = t + 2
                else:
                    m_pos = len(out) - 1 - (t >> 2) - (src[ip] << 2)
                    ip += 1
                    ln = 2
                if m_pos < 0:
                    raise LzoError("bad match position")
                if len(out) - m_pos >= ln:
                    out += out[m_pos : m_pos + ln]
                else:
                    for _ in range(ln):
                        out.append(out[m_pos])
                        m_pos += 1
                t = src[ip - 2] & 3
                if t == 0:
                    break
                out += src[ip : ip + t]
                ip += t
                t = src[ip]
                ip += 1
            if ip >= n:
                return bytes(out)
    except IndexError:
        if out_size is not None and len(out) >= out_size:
            return bytes(out[:out_size])
        raise LzoError("truncated LZO stream") from None


def is_jade_blocks(data: bytes) -> bool:
    """Cheap sniff: first block header with sane sizes."""
    if len(data) < 8:
        return False
    size, zsize = struct.unpack_from("<II", data, 0)
    return 0 < size <= 0x400000 and 0 < zsize <= size and zsize + 8 <= len(data)


def decompress_blocks(data: bytes) -> bytes:
    """Decode a Jade block-framed LZO stream (a whole binarized BIN payload)."""
    out = []
    pos = 0
    n = len(data)
    while pos + 8 <= n:
        size, zsize = struct.unpack_from("<II", data, pos)
        pos += 8
        if size == 0:
            break
        if zsize > n - pos:
            raise LzoError(f"block at {pos - 8:#x} runs past the end of the data")
        blk = data[pos : pos + zsize]
        pos += zsize
        if zsize == size:
            out.append(blk)
        else:
            dec = lzo1x_decompress(blk, size)
            if len(dec) != size:
                raise LzoError(f"block at {pos - zsize - 8:#x}: got {len(dec)} of {size} bytes")
            out.append(dec)
    return b"".join(out)
