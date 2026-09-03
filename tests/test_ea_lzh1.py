"""EA GCMP.LIB LZH1 (TERF comp5): decoder against a reference encoder written from the spec."""

from __future__ import annotations

import struct
import zlib

import pytest

from gcrip.formats import ea_lzh1, ea_terf
from gcrip.plugins import ea


class _Writer:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def put(self, value: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def code(self, codes: dict[int, tuple[int, int]], sym: int) -> None:
        c, n = codes[sym]
        self.put(c, n)

    def bytes(self) -> bytes:
        bits = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8))


def _codes(lengths: list[int]) -> dict[int, tuple[int, int]]:
    counts = [0] * 16
    for n in lengths:
        counts[n] += 1
    counts[0] = 0
    code = 0
    nxt = [0] * 16
    for n in range(1, 16):
        code = (code + counts[n - 1]) << 1
        nxt[n] = code
    out = {}
    for sym, n in enumerate(lengths):
        if n:
            out[sym] = (nxt[n], n)
            nxt[n] += 1
    return out


def _find(base: list[int], extra: list[int], value: int, bare: int | None) -> tuple[int, int, int]:
    """Symbol index, extra-bit count and extra value for a length or distance."""
    if bare is not None and value == bare:
        return base.index(bare), 0, 0
    for i in range(len(base) - 1, -1, -1):
        if i < len(extra) and base[i] <= value < base[i] + (1 << extra[i]):
            return i, extra[i], value - base[i]
    raise ValueError(value)


def encode(plain: bytes, ops: list[tuple], blocks: int = 1) -> bytes:
    """Reference encoder.  ``ops`` is a list of ('lit', byte) or ('match', length, distance)
    that reproduces ``plain``; every alphabet symbol gets a 9-bit code so any op is codable."""
    lit_len = [9] * 285
    dist_len = [5] * 30
    lit = _codes(lit_len)
    dist = _codes(dist_len)
    w = _Writer()
    per_block = (len(ops) + blocks - 1) // blocks
    for b in range(blocks):
        w.put(0, 1)
        for n in lit_len:
            w.put(n, 4)
        for n in dist_len:
            w.put(n, 4)
        for op in ops[b * per_block : (b + 1) * per_block]:
            if op[0] == "lit":
                w.code(lit, op[1])
            else:
                _, length, distance = op
                if length < 11:
                    i, eb, ev = length - 3, 0, 0
                else:
                    i, eb, ev = _find(ea_lzh1.LEN_BASE, ea_lzh1.LEN_EXTRA, length, 227)
                w.code(lit, 257 + i)
                w.put(ev, eb)
                if distance <= 4:
                    d, eb, ev = distance - 1, 0, 0
                else:
                    d, eb, ev = _find(ea_lzh1.DIST_BASE, ea_lzh1.DIST_EXTRA, distance, None)
                w.code(dist, d)
                w.put(ev, eb)
        w.code(lit, 256)
    w.put(1, 1)
    w.put(zlib.adler32(plain), 32)
    return w.bytes()


def _ops_for(plain: bytes) -> list[tuple]:
    """A greedy LZ parse good enough to exercise matches of every shape."""
    ops: list[tuple] = []
    i = 0
    while i < len(plain):
        best = (0, 0)
        for d in range(1, min(i, 32768) + 1):
            n = 0
            while n < 227 and i + n < len(plain) and plain[i + n] == plain[i + n - d]:
                n += 1
            if n > best[0]:
                best = (n, d)
            if n == 227:
                break
        if best[0] >= 3:
            ops.append(("match", best[0], best[1]))
            i += best[0]
        else:
            ops.append(("lit", plain[i]))
            i += 1
    return ops


def test_literals_only_roundtrip():
    plain = bytes(range(256)) + b"TMdl"
    stream = encode(plain, [("lit", b) for b in plain])
    assert ea_lzh1.unpack(stream, len(plain)) == plain


def test_matches_including_overlap_and_longest():
    plain = b"abc" * 100 + b"x" * 300 + bytes(range(64)) * 3 + b"\0" * 5000
    ops = _ops_for(plain)
    assert any(op[0] == "match" and op[1] == 227 for op in ops), "the bare-227 symbol is exercised"
    assert any(op[0] == "match" and op[2] < op[1] for op in ops), "overlapping copies are exercised"
    assert ea_lzh1.unpack(encode(plain, ops), len(plain)) == plain


def test_far_distances_use_extra_bits():
    head = bytes((i * 7919) & 0xFF for i in range(20000))
    plain = head + head[:500]
    ops = [("lit", b) for b in head] + [("match", 227, 20000), ("match", 227, 20000), ("match", 46, 20000)]
    assert ea_lzh1.unpack(encode(plain, ops), len(plain)) == plain


def test_several_blocks():
    plain = b"hello world " * 40
    stream = encode(plain, _ops_for(plain), blocks=3)
    assert ea_lzh1.unpack(stream) == plain


def test_checksum_and_declared_size_are_checked():
    plain = b"checked" * 50
    stream = bytearray(encode(plain, _ops_for(plain)))
    stream[-1] ^= 0xFF
    with pytest.raises(ea_lzh1.Lzh1Error):
        ea_lzh1.unpack(bytes(stream))
    assert ea_lzh1.unpack(bytes(stream), verify=False) == plain
    with pytest.raises(ea_lzh1.Lzh1Error):
        ea_lzh1.unpack(encode(plain, _ops_for(plain)), len(plain) + 1)


def test_distance_before_start_is_refused():
    with pytest.raises(ea_lzh1.Lzh1Error):
        ea_lzh1.unpack(encode(b"abc", [("match", 3, 1)]))


def _terf_with_comp(members: list[tuple[bytes, int, int]], align: int = 64) -> bytes:
    def pad(b: bytes) -> bytes:
        return b + b"\0" * (-len(b) % align)

    dir_body = bytearray()
    comp_body = bytearray()
    data = bytearray(b"DATA" + b"\0\0\0\0")
    data += b"\0" * (-len(data) % align)
    for blob, ctype, unpacked in members:
        dir_body += struct.pack(">II", len(data), len(blob))
        comp_body += struct.pack(">II", ctype, unpacked)
        data += blob
        data += b"\0" * (-len(data) % align)
    struct.pack_into(">I", data, 4, len(data))
    dir1 = pad(b"DIR1" + struct.pack(">I", 8 + len(dir_body)) + dir_body)
    comp = pad(b"COMP" + struct.pack(">I", 8 + len(comp_body)) + comp_body)
    head = b"TERF" + struct.pack(">I", align) + bytes([2, 2, 1, 6])
    head += struct.pack(">HH", align, len(members))
    head += b"\0" * (align - len(head))
    return head + dir1 + comp + bytes(data)


def test_terf_decodes_comp5_members_and_names_them_by_magic():
    model = b"TMdl" + bytes(range(60))
    stored = b"MMAP" + b"\0" * 40
    packed = encode(model, [("lit", b) for b in model])
    arc = _terf_with_comp([(packed, ea_terf.LZH1, len(model)), (stored, 0, 0), (b"\x12\x34\x56\x78", 3, 99)])
    names = dict(ea.expand(arc))
    assert names["0000.tmdl"] == model
    assert names["0001.mmap"] == stored
    assert names["0002.comp3"] == b"\x12\x34\x56\x78", "other GCMP codecs keep their packed bytes"


def test_terf_keeps_packed_bytes_when_the_stream_is_corrupt():
    packed = bytearray(encode(b"TMdl" * 8, [("lit", b) for b in b"TMdl" * 8]))
    packed[-1] ^= 0xFF
    arc = _terf_with_comp([(bytes(packed), ea_terf.LZH1, 32)])
    names = dict(ea.expand(arc))
    assert list(names) == ["0000.comp5"]
