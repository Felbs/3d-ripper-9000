"""YZ2: Yamazaki Satoshi's "yz2" compressor (2002), as used by Capcom for the
Resident Evil 4 stage room packs (St?/r???.das slot 0, tagged 0xCE2843DD).

Port of the decoder in JADERLINK/RE4_DASYZ2_TOOL (YZ2_TOOLS/YZ2/yz2Code), which
wraps the original yz2Decode.cxx / yz2RangeDec.cxx / RangeCode sources.  The
scheme is an adaptive range coder over an LZ-ish "keyed dictionary":

  header   32 ASCII bytes: "<packed hex>\\t<unpacked hex>\\n", NUL padded
  stream   range coded (15-bit frequency tables, 32-bit work registers, carry
           propagated into already-emitted bytes) symbols from two adaptive
           tables that start uniform, double their scale at each power-of-two
           symbol count and halve when they saturate at 2^15:
             codes  1280 symbols:   0..511  match on dictionary slot, explicit length
                                   512..1023 match on dictionary slot, the slot's own length
                                  1024..1279 literal byte
             length 256 symbols: n -> n - 3 (+2) bytes, with 0 / 1 / 2 escaping to
                                 4 / 3 / 2 more bytes (big-endian)
  dictionary  256 keys (the byte before the current position) x 512 ring slots of
           (pointer into the output, length); after every symbol the run just
           produced is registered under the byte preceding it.

The encoder here is a simple greedy one for round-trip tests; the game's data was
packed with the original tool (better match selection, same bitstream rules).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from itertools import accumulate

TAG = b"\xce\x28\x43\xdd"

_SHIFT = 15
_DIC_SIZE = 512
_KEYS = 256
_N_CODES = _DIC_SIZE * 2 + _KEYS  # 1280
_N_LENGTH = 256
_MASK32 = 0xFFFFFFFF
_WORK_FULL = 0x80000000


class Yz2Error(ValueError):
    pass


# ---------------------------------------------------------------------------
# adaptive frequency table (Frequency4Tbl)
# ---------------------------------------------------------------------------


class _Freq:
    """Symbol counts and the range table derived from them.  `lows` has size+1
    entries (cumulative), the range of code i is [lows[i], lows[i+1])."""

    __slots__ = ("size", "counts", "lows", "total", "bit", "check")

    def __init__(self, size: int) -> None:
        self.size = size
        # the constructor spreads 2^15 evenly (round robin) and builds the range
        # table from that; ReSet() then resets the counts but keeps the table
        base, extra = divmod(1 << _SHIFT, size)
        widths = [base + 1 if i < extra else base for i in range(size)]
        self.lows = [0] + list(accumulate(widths))
        self.reset()

    def reset(self) -> None:
        self.counts = [1] * self.size
        self.total = self.size
        bit = 0
        while bit < _SHIFT and self.total >= (1 << bit):
            bit += 1
        self.bit = bit
        self.check = 1 << bit

    def count(self, code: int) -> None:
        self.counts[code] += 1
        self.total += 1
        if self.bit < _SHIFT:
            if self.total == self.check:
                x = 1 << (_SHIFT - self.bit)
                self.lows = [0] + list(accumulate(c * x for c in self.counts))
                self.bit += 1
                self.check = 1 << self.bit
        elif self.total >= (1 << _SHIFT):
            self.lows = [0] + list(accumulate(self.counts))
            self.counts = [max(c >> 1, 1) for c in self.counts]
            self.total = sum(self.counts)


# ---------------------------------------------------------------------------
# decoder
# ---------------------------------------------------------------------------


class _RangeDecoder:
    __slots__ = ("src", "ip", "n", "low", "width")

    def __init__(self, src: bytes) -> None:
        self.src = src
        self.n = len(src)
        self.ip = 1
        self.low = src[0] if src else 0
        self.width = 1 << 7

    def decode(self, tbl: _Freq) -> int:
        low, width = self.low, self.width
        if width <= 0x800000:
            src, ip, n = self.src, self.ip, self.n
            while width <= 0x800000:
                low = ((low << 8) | (src[ip] if ip < n else 0)) & _MASK32
                ip += 1
                width <<= 8
            self.ip = ip
        w = width >> (_SHIFT - 1)
        lows = tbl.lows
        code = bisect_right(lows, low // w) - 1
        if code >= tbl.size:
            code = tbl.size - 1
        self.low = (low - w * lows[code]) & _MASK32
        self.width = (w * (lows[code + 1] - lows[code])) >> 1
        tbl.count(code)
        return code


def _length(rd: _RangeDecoder, tbl: _Freq) -> int:
    v = rd.decode(tbl)
    if v == 0:
        v = rd.decode(tbl) << 24
        v |= rd.decode(tbl) << 16
        v |= rd.decode(tbl) << 8
        v |= rd.decode(tbl)
    elif v == 1:
        v = rd.decode(tbl) << 16
        v |= rd.decode(tbl) << 8
        v |= rd.decode(tbl)
    elif v == 2:
        v = rd.decode(tbl) << 8
        v |= rd.decode(tbl)
    return v - 3


def decode_stream(src: bytes, out_size: int) -> bytes:
    """Decode a headerless yz2 stream into exactly `out_size` bytes."""
    out = bytearray(out_size)
    rd = _RangeDecoder(src)
    codes = _Freq(_N_CODES)
    lengths = _Freq(_N_LENGTH)
    ptr = [-1] * (_KEYS * _DIC_SIZE)
    lng = [0] * (_KEYS * _DIC_SIZE)
    cnt = [0] * _KEYS
    pos = 0
    key_pos = 0
    decode = rd.decode
    while pos < out_size:
        code = decode(codes)
        if code >= _DIC_SIZE * 2:
            out[pos] = code - _DIC_SIZE * 2
            pos += 1
            size = 1
        else:
            key = out[key_pos]
            if code < _DIC_SIZE:
                size = _length(rd, lengths) + 2
                slot = key * _DIC_SIZE + ((code + cnt[key]) & (_DIC_SIZE - 1))
            else:
                slot = key * _DIC_SIZE + ((code + cnt[key]) & (_DIC_SIZE - 1))
                size = lng[slot]
            moto = ptr[slot]
            if pos + size > out_size:
                raise Yz2Error(f"match of {size} at {pos} overruns {out_size}")
            if moto < 0 or moto >= out_size:
                raise Yz2Error(f"bad dictionary reference at {pos}")
            if moto + size <= pos:
                out[pos : pos + size] = out[moto : moto + size]
            else:
                for i in range(size):
                    out[pos + i] = out[moto + i]
            pos += size
        if key_pos < pos - 1:
            key = out[key_pos]
            c = cnt[key]
            slot = key * _DIC_SIZE + c
            ptr[slot] = key_pos + 1
            lng[slot] = size
            cnt[key] = (c + 1) & (_DIC_SIZE - 1)
            key_pos = pos - 1
    return bytes(out)


_HEADER = re.compile(rb"^([0-9a-fA-F]{1,8})\t([0-9a-fA-F]{1,8})\n")


def header_sizes(data: bytes) -> tuple[int, int] | None:
    """(packed, unpacked) from the 32-byte ASCII header, or None."""
    m = _HEADER.match(data[:32])
    if not m:
        return None
    return int(m.group(1), 16), int(m.group(2), 16)


def is_yz2(data: bytes) -> bool:
    return header_sizes(data) is not None and len(data) > 32


def decode(data: bytes) -> bytes:
    """Decode a headered yz2 blob (as found in a DAS slot)."""
    sizes = header_sizes(data)
    if sizes is None:
        raise Yz2Error("no yz2 header")
    packed, unpacked = sizes
    return decode_stream(data[32 : 32 + packed + 8], unpacked)


# ---------------------------------------------------------------------------
# encoder (greedy; for tests and round-trips)
# ---------------------------------------------------------------------------


class _RangeEncoder:
    __slots__ = ("out", "low", "width")

    def __init__(self) -> None:
        self.out = bytearray()
        self.low = 0
        self.width = _WORK_FULL

    def _carry(self) -> None:
        out = self.out
        i = len(out) - 1
        while i >= 0:
            v = (out[i] + 1) & 0xFF
            out[i] = v
            if v:
                break
            i -= 1

    def _flush(self) -> None:
        while self.width <= 0x800000:
            self.out.append(self.low >> 24)
            self.low = (self.low << 8) & _MASK32
            self.width <<= 8

    def encode(self, tbl: _Freq, code: int) -> None:
        self._flush()
        r = self.width >> (_SHIFT - 1)
        lows = tbl.lows
        low = self.low + r * lows[code]
        if low > _MASK32:
            self._carry()
            low &= _MASK32
        self.low = low
        self.width = (r * (lows[code + 1] - lows[code])) >> 1
        tbl.count(code)

    def finish(self) -> bytes:
        self._flush()
        low = self.low + self.width
        if low > _MASK32:
            self._carry()
            low &= _MASK32
        self.low = low
        self.width >>= 1
        self._flush()
        if self.width < _WORK_FULL:
            self.out.append(self.low >> 24)
        return bytes(self.out)


def _put_length(enc: _RangeEncoder, tbl: _Freq, value: int) -> None:
    v = value + 3
    if v < 256:
        enc.encode(tbl, v)
    elif v < 1 << 16:
        enc.encode(tbl, 2)
        enc.encode(tbl, v >> 8)
        enc.encode(tbl, v & 0xFF)
    elif v < 1 << 24:
        enc.encode(tbl, 1)
        enc.encode(tbl, v >> 16)
        enc.encode(tbl, (v >> 8) & 0xFF)
        enc.encode(tbl, v & 0xFF)
    else:
        enc.encode(tbl, 0)
        for s in (24, 16, 8, 0):
            enc.encode(tbl, (v >> s) & 0xFF)


def encode_stream(data: bytes, max_match: int = 0x10000) -> bytes:
    """Greedy yz2 encoder producing a headerless stream decode_stream() accepts."""
    n = len(data)
    enc = _RangeEncoder()
    codes = _Freq(_N_CODES)
    lengths = _Freq(_N_LENGTH)
    ptr = [-1] * (_KEYS * _DIC_SIZE)
    lng = [0] * (_KEYS * _DIC_SIZE)
    cnt = [0] * _KEYS
    used = [0] * _KEYS
    pos = 0
    key_pos = 0
    while pos < n:
        best_len = 0
        best_slot = -1
        if pos > 0:
            key = data[key_pos]
            base = key * _DIC_SIZE
            for s in range(base, base + used[key]):
                p = ptr[s]
                limit = min(n - pos, max_match)
                k = 0
                while k < limit and data[p + k] == data[pos + k]:
                    k += 1
                if k > best_len:
                    best_len, best_slot = k, s
        if best_len >= 2:
            key = data[key_pos]
            rel = (best_slot - key * _DIC_SIZE - cnt[key]) & (_DIC_SIZE - 1)
            if lng[best_slot] == best_len:
                enc.encode(codes, _DIC_SIZE + rel)
            else:
                enc.encode(codes, rel)
                _put_length(enc, lengths, best_len - 2)
            size = best_len
        else:
            enc.encode(codes, _DIC_SIZE * 2 + data[pos])
            size = 1
        pos += size
        if key_pos < pos - 1:
            key = data[key_pos]
            c = cnt[key]
            slot = key * _DIC_SIZE + c
            ptr[slot] = key_pos + 1
            lng[slot] = size
            cnt[key] = (c + 1) & (_DIC_SIZE - 1)
            used[key] = min(used[key] + 1, _DIC_SIZE)
            key_pos = pos - 1
    return enc.finish()


def encode(data: bytes) -> bytes:
    """Headered yz2 blob (32-byte ASCII sizes + stream), as a DAS slot holds it."""
    stream = encode_stream(data)
    header = f"{len(stream):x}\t{len(data):x}\n".encode().ljust(32, b"\0")
    return header + stream
