import struct

import pytest

from gcrip.formats import yay0, yaz0

from .builders import yay0_literal, yaz0_literal


def test_yaz0_literals_roundtrip():
    data = bytes(range(256)) * 3 + b"tail"
    assert yaz0.decompress(yaz0_literal(data)) == data


def test_yaz0_backreference_short_and_long():
    # "abc" literal, then copy 3 back x3 (n=3 -> code nibble 1, dist 3 -> 0x002)
    # then long copy: n=0 -> third byte = count - 0x12; copy 20 bytes from dist 3.
    stream = bytes(
        [
            0b11100000,  # a b c literal, then 2 backrefs (bits 0), rest ignored
            ord("a"),
            ord("b"),
            ord("c"),
            0x10,
            0x02,  # n=1+2=3, dist=2+1=3 -> "abc"
            0x00,
            0x02,
            20 - 0x12,  # n=20, dist=3
        ]
    )
    expected = b"abc" + b"abc" + (b"abc" * 7)[:20]
    src = b"Yaz0" + struct.pack(">I", len(expected)) + b"\x00" * 8 + stream
    assert yaz0.decompress(src) == expected


def test_yaz0_overlapping_run():
    # 'x' then copy 15 bytes at distance 1 -> 'x' * 16
    stream = bytes([0b10000000, ord("x"), 0xD0, 0x00])
    src = b"Yaz0" + struct.pack(">I", 16) + b"\x00" * 8 + stream
    assert yaz0.decompress(src) == b"x" * 16


def test_yaz0_rejects_bad_magic():
    with pytest.raises(ValueError):
        yaz0.decompress(b"Nope" + b"\x00" * 12)


def test_yay0_literals_roundtrip():
    data = bytes(range(256)) * 2 + b"!"
    assert yay0.decompress(yay0_literal(data)) == data


def test_yay0_backreference():
    # literals "abcd" then link copying 4 bytes from distance 4, then long link (n=0)
    expected = b"abcd" + b"abcd" + (b"abcd" * 6)[: 0x12 + 1]
    mask = struct.pack(">I", 0b11110000 << 24)
    links = struct.pack(">HH", (2 << 12) | 3, (0 << 12) | 3)  # n=2+2=4 dist=4 ; n=0 dist=4
    chunk = b"abcd" + bytes([1])  # 1 + 0x12 = 19
    link_off = 16 + len(mask)
    chunk_off = link_off + len(links)
    src = b"Yay0" + struct.pack(">III", len(expected), link_off, chunk_off) + mask + links + chunk
    assert yay0.decompress(src) == expected
