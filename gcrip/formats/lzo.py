"""LZO1X decompressor (pure Python) - the codec behind Metroid Prime 2's PAK/MREA
"segmented LZO1X-999" blocks. Any LZO1X-1/-999 stream decodes with the same routine.

Stream grammar (from lzo1x_d.ch), all offsets relative to the output position `op`:
  first byte > 17: (byte - 17) literals follow (17+ = long literal run at stream start)
  opcode < 16 at run start: literal run of (op + 3) bytes; op == 0 means the length is
      extended by 255 per zero byte plus the next byte plus 15
  then a match opcode t:
      t >= 64: M2 - length (t >> 5) + 1, distance 1 + ((t >> 2) & 7) + (next << 3)
      t >= 32: M3 - length (t & 31) + 2 (0 = extended), distance 1 + (le16 >> 2)
      t >= 16: M4 - length (t & 7) + 2 (0 = extended), distance 0x4000 + ((t & 8) << 11)
               + (le16 >> 2); distance 0x4000 with no length is the end-of-stream mark
      t <  16: M1 - length 2, distance 1 + (t >> 2) + (next << 2)
      (after a literal run of >= 4 bytes: M1 distance is 0x801 + (t >> 2) + (next << 2), len 3)
  the low 2 bits of the last byte of every match give the count of literals (0-3) that
  follow before the next match opcode.
"""

from __future__ import annotations


class LzoError(ValueError):
    pass


def decompress(src: bytes, max_out: int | None = None, history: bytes = b"") -> bytes:
    """Decode one LZO1X stream. `max_out` (the known decompressed size) is only a guard.
    `history` is output that precedes this stream and that its matches may reach back into
    (Ubisoft's ``deadbabe`` blocks continue each other that way)."""
    out = bytearray(history)
    base = len(history)
    n = len(src)
    ip = 0
    try:
        t = src[ip]
        state = "run"  # next thing to read is a literal-run opcode
        if t > 17:
            ip += 1
            t -= 17
            out += src[ip : ip + t]
            ip += t
            state = "match_next_first" if t < 4 else "first_literal_run"
        while True:
            if state == "run":
                t = src[ip]
                ip += 1
                if t >= 16:
                    state = "match"
                else:
                    if t == 0:
                        while src[ip] == 0:
                            t += 255
                            ip += 1
                        t += 15 + src[ip]
                        ip += 1
                    t += 3
                    out += src[ip : ip + t]
                    ip += t
                    state = "first_literal_run"
                    continue
            if state == "first_literal_run":
                t = src[ip]
                ip += 1
                if t < 16:
                    m_pos = len(out) - 0x801 - (t >> 2) - (src[ip] << 2)
                    ip += 1
                    if m_pos < 0:
                        raise LzoError("lookbehind underrun")
                    out += out[m_pos : m_pos + 3]
                    state = "match_done"
                else:
                    state = "match"
            if state == "match_next_first":
                t = src[ip]
                ip += 1
                state = "match"
            if state == "match":
                op = len(out)
                if t >= 64:
                    m_pos = op - 1 - ((t >> 2) & 7) - (src[ip] << 3)
                    ip += 1
                    length = (t >> 5) + 1
                elif t >= 32:
                    length = t & 31
                    if length == 0:
                        while src[ip] == 0:
                            length += 255
                            ip += 1
                        length += 31 + src[ip]
                        ip += 1
                    m_pos = op - 1 - ((src[ip] | (src[ip + 1] << 8)) >> 2)
                    ip += 2
                    length += 2
                elif t >= 16:
                    m_pos = op - ((t & 8) << 11)
                    length = t & 7
                    if length == 0:
                        while src[ip] == 0:
                            length += 255
                            ip += 1
                        length += 7 + src[ip]
                        ip += 1
                    m_pos -= (src[ip] | (src[ip + 1] << 8)) >> 2
                    ip += 2
                    if m_pos == op:
                        break  # end of stream
                    m_pos -= 0x4000
                    length += 2
                else:
                    m_pos = op - 1 - (t >> 2) - (src[ip] << 2)
                    ip += 1
                    length = 2
                if m_pos < 0:
                    raise LzoError("lookbehind underrun")
                if m_pos + length <= op:
                    out += out[m_pos : m_pos + length]
                else:  # overlapping copy: repeat the tail pattern
                    span = op - m_pos
                    chunk = out[m_pos:op]
                    reps, rem = divmod(length, span)
                    out += chunk * reps + chunk[:rem]
                state = "match_done"
            if state == "match_done":
                t = src[ip - 2] & 3
                if t == 0:
                    state = "run"
                else:
                    out += src[ip : ip + t]
                    ip += t
                    t = src[ip]
                    ip += 1
                    state = "match"
            if max_out is not None and len(out) - base > max_out:
                raise LzoError("output exceeds expected size")
    except IndexError:
        raise LzoError(f"truncated LZO stream at byte {ip} of {n}") from None
    return bytes(out[base:])


def decompress_segmented(src: bytes, total: int, segment: int = 0x4000) -> bytes:
    """Retro's segmented form: repeated (s16 size, payload); a negative size means the
    payload is stored raw. Each payload decodes to `segment` bytes (the last one less)."""
    out = bytearray()
    ip = 0
    while len(out) < total:
        if ip + 2 > len(src):
            raise LzoError("segment table truncated")
        size = int.from_bytes(src[ip : ip + 2], "big", signed=True)
        ip += 2
        if size < 0:
            out += src[ip : ip - size]
            ip -= size
        elif size == 0:
            raise LzoError("zero-length segment")
        else:
            out += decompress(src[ip : ip + size], min(segment, total - len(out)))
            ip += size
    return bytes(out[:total])
