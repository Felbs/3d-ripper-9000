"""Neko Entertainment LZ - the Cocoto level files."""

import struct

from gcrip.formats import neko_lz
from gcrip.plugins import neko_lz as plugin


def _match(raw: bytes, i: int) -> tuple[int, int]:
    """Longest match for ``raw[i:]`` inside the window as (length, distance)."""
    best = (0, 0)
    for dist in range(1, min(i, neko_lz.RING - neko_lz.MAX_MATCH) + 1):
        length = 0
        limit = min(neko_lz.MAX_MATCH, len(raw) - i)
        while length < limit and raw[i + length - dist] == raw[i + length]:
            length += 1
        if length > best[0]:
            best = (length, dist)
    return best


def pack(raw: bytes) -> bytes:
    """A greedy encoder in the file's own dialect: flags LSB-first, 1 = literal, references
    as absolute ring indices with the ring written from 4,078."""
    out = bytearray()
    i = 0
    while i < len(raw):
        flags = 0
        items = []
        for k in range(8):
            if i >= len(raw):
                break
            length, dist = _match(raw, i)
            if length >= 3:
                idx = (i - dist + neko_lz.RING - neko_lz.MAX_MATCH) % neko_lz.RING
                items.append(bytes([idx & 0xFF, ((idx >> 8) << 4) | (length - 3)]))
                i += length
            else:
                flags |= 1 << k
                items.append(raw[i : i + 1])
                i += 1
        out.append(flags)
        out += b"".join(items)
    return struct.pack(">2I", len(out), len(raw)) + bytes(out)


def test_round_trip_with_references():
    raw = b"cocoto kart racer cocoto kart racer " * 5 + bytes(range(256)) * 3
    packed = pack(raw)
    assert len(packed) < len(raw)
    assert neko_lz.is_packed(packed[:8], len(packed))
    assert neko_lz.unpack(packed) == raw


def test_rejects_a_header_that_does_not_match_the_size():
    packed = pack(b"abcabcabcabc")
    assert not neko_lz.is_packed(packed[:8], len(packed) + 1)
    assert neko_lz.unpack(packed[:-1]) is None


def test_plugin_expands_to_one_member():
    packed = pack(b"level data " * 20)
    assert plugin.is_container("data/L1/L1.GCN", packed[:64])
    assert not plugin.is_container("data/L1/L1.cp2", packed[:64])
    assert plugin.expand(packed) == [("unpacked.bin", b"level data " * 20)]


def test_a_reference_before_the_start_copies_zeros():
    # the ring is written from 4078: a reference at 4070 reads the zero fill, one at 4078
    # reads the first literals back (and overlaps itself, the classic LZSS way)
    src = bytes([0b00000111, 1, 2, 3]) + bytes([4070 & 0xFF, ((4070 >> 8) << 4) | 0])
    assert neko_lz.lzss(src) == bytes([1, 2, 3, 0, 0, 0])
    src = bytes([0b00000111, 1, 2, 3]) + bytes([4078 & 0xFF, ((4078 >> 8) << 4) | 2])
    assert neko_lz.lzss(src) == bytes([1, 2, 3, 1, 2, 3, 1, 2])
