"""EA rcmp (Tiger Woods ``Rdat``): decoder against a reference encoder written from the spec,
and the SHOC member reader assembling Rdat blocks."""

from __future__ import annotations

import struct

import pytest

from gcrip.formats import ea_rcmp, shoc
from tests.test_shoc import chunk, shdr, wrap


def lit(data: bytes) -> bytes:
    assert len(data) <= 0x7FF
    return struct.pack(">H", 0x8800 | len(data)) + data


def run(dist: int, n: int) -> bytes:
    assert 1 <= dist <= 63 and 3 <= n <= 258
    return struct.pack(">H", 0x8800 | ((dist & 7) << 12) | ((dist & 0x38) << 5) | (n - 3))


def copy(off: int, n: int, mirrored: bool = False) -> bytes:
    assert 1 <= off <= 0x7FF if mirrored else 1 <= off <= 0xFFF
    code = n - 3
    head = (0x8000 if mirrored else 0) | off
    if code < 7:
        return struct.pack(">H", head | (code << 12))
    assert code - 7 <= 255
    return struct.pack(">H", head | (7 << 12)) + bytes([code - 7])


def test_literals_runs_and_copies():
    plain = b"golf course!" + b"!" * 40 + b"golf course!" + b"abcdefgh" * 4
    stream = lit(b"golf course!") + run(1, 40) + copy(52, 12) + lit(b"abcdefgh") + copy(8, 24)
    assert ea_rcmp.unpack(stream, len(plain)) == plain


def test_long_copy_uses_the_extra_length_byte():
    head = bytes(range(256))
    plain = head + head[:200]
    stream = lit(head) + copy(256, 200)
    assert ea_rcmp.unpack(stream, len(plain)) == plain


def test_mirrored_copy_walks_backwards_from_two_past_the_offset():
    head = b"0123456789"
    stream = lit(head) + copy(6, 5, mirrored=True)
    # out - 6 + 2 is index 6 ('6'); five bytes backwards: 6 5 4 3 2
    assert ea_rcmp.unpack(stream, 15) == head + b"65432"


def test_run_distance_spans_both_bit_groups():
    head = bytes(range(1, 64))
    stream = lit(head) + run(63, 3) + run(9, 4)
    out = ea_rcmp.unpack(stream, 63 + 7)
    assert out[63:66] == b"\x01" * 3  # 63 back from the end of the head is byte 1
    assert out[66:70] == bytes([out[66 - 9]]) * 4


def test_short_stream_and_bad_references_raise():
    with pytest.raises(ea_rcmp.RcmpError):
        ea_rcmp.unpack(lit(b"abc"), 10)
    with pytest.raises(ea_rcmp.RcmpError):
        ea_rcmp.unpack(copy(4, 3), 3)
    with pytest.raises(ea_rcmp.RcmpError):
        ea_rcmp.unpack(lit(b"ab") + run(5, 3), 5)


def test_shoc_assembles_rdat_blocks_behind_their_chunk_headers():
    """An Rdat block: 40 bytes of chunk header after the inner tag's 8, then the u32 unpacked
    size, then the stream.  A stored SDAT block in the same member keeps its 40-byte prefix."""
    part1 = b"OBG " + bytes([1, 4, 0, 0]) + b"ARRA" + b"A" * 20
    part2 = b"terrain" * 10
    packed1 = lit(part1[:12]) + run(1, 20)
    packed2 = lit(b"terrain") + copy(7, 63)
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(b"ter ", 1, len(part1) + len(part2) + 8)
        + wrap(chunk(shoc.EALZ, bytes(40) + struct.pack(">I", len(part1)) + packed1))
        + wrap(chunk(shoc.STORED, bytes(40) + b"stored!!"))
        + wrap(chunk(shoc.EALZ, bytes(40) + struct.pack(">I", len(part2)) + packed2))
    )
    (m,) = shoc.members(data)
    assert m.kind == "ter" and m.data == part1 + b"stored!!" + part2


def test_shoc_declines_an_rdat_member_whose_blocks_do_not_reconcile():
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(b"sfx ", 10, 812)
        + wrap(chunk(shoc.EALZ, bytes(40) + struct.pack(">I", 812) + lit(b"x" * 100)))
    )
    assert shoc.members(data) == []


def test_a_word_padded_stored_tail_is_trimmed_to_the_declared_size():
    """Frodo's main rcb: two Rdat blocks and a stored tail whose payload is padded to a word
    boundary, assembling to 34,335 of a declared 34,332.  The member is byte-perfect up to
    the declared size (its relocation table ends exactly there), so the pad is trimmed
    rather than the member dropped."""
    part = b"skeleton" * 4
    tail = b"reloc table!"
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(b"rcb ", 35001, len(part) + len(tail))
        + wrap(
            chunk(
                shoc.EALZ,
                bytes(40) + struct.pack(">I", len(part)) + lit(part[:11]) + copy(8, 21),
            )
        )
        + wrap(chunk(shoc.STORED, bytes(40) + tail + b"\xb5\xa7\xbd"))
    )
    (m,) = shoc.members(data)
    assert m.kind == "rcb" and m.data == part + tail
