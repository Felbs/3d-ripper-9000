"""Neko Entertainment LZ - the Cocoto level files."""

import struct

from gcrip.formats import neko_lz
from gcrip.plugins import neko_lz as plugin


def _match(raw: bytes, i: int) -> tuple[int, int]:
    best = (0, 0)
    for dist in range(1, min(i, 4096) + 1):
        length = 0
        while length < 18 and i + length < len(raw) and raw[i + length - dist] == raw[i + length]:
            length += 1
        if length > best[0]:
            best = (length, dist)
    # a zero run before the window is a reference past the start
    zeros = 0
    while i + zeros < len(raw) and raw[i + zeros] == 0 and zeros < 18:
        zeros += 1
    if zeros >= 3 and zeros > best[0]:
        best = (zeros, 4096)
    return best


def pack(raw: bytes) -> bytes:
    """A greedy encoder in the file's own dialect: flags LSB-first, 1 = literal."""
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
                d = dist - 1
                items.append(bytes([d & 0xFF, ((d >> 8) << 4) | (length - 3)]))
                i += length
            else:
                flags |= 1 << k
                items.append(raw[i : i + 1])
                i += 1
        out.append(flags)
        out += b"".join(items)
    return struct.pack(">2I", len(out), len(raw)) + bytes(out)


def test_round_trip_with_zero_window_and_references():
    raw = bytes(12) + b"cocoto kart racer cocoto kart racer " * 5 + bytes(range(256)) * 3
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
