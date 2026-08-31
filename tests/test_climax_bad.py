"""Climax .bad - ring-buffer LZSS (ATV: Quad Power Racing 2, Hot Wheels, The Italian Job)."""

import struct

from gcrip.formats import climax_bad
from gcrip.plugins import climax_bad as plugin


def pack(text):
    """Emit `text` as literals only - eight to a flag byte, low bit first."""
    out = bytearray()
    for i in range(0, len(text), 8):
        chunk = text[i : i + 8]
        out.append((1 << len(chunk)) - 1)
        out += chunk
    return bytes(out)


def test_a_flag_byte_of_all_literals_copies_eight_bytes():
    assert climax_bad.decompress(pack(b"CUBAN 1.")) == b"CUBAN 1."


def test_a_clear_flag_bit_is_a_two_byte_match():
    """position is absolute in the ring, not a distance back from the cursor."""
    start = climax_bad.RING - climax_bad.MAX_MATCH
    stream = bytes([0xFF]) + b"abcdefgh" + bytes([0x00, start & 0xFF, (start >> 4) & 0xF0])
    assert climax_bad.decompress(stream) == b"abcdefgh" + b"abc"


def test_the_ring_starts_zero_filled_not_space_filled():
    """A match reaching untouched ring is what tells the two apart, and zero is what makes
    ATV's header read as clean big-endian words."""
    got = climax_bad.decompress(bytes([0xFE, 0x00, 0x00]))
    assert got == bytes(3)  # a space-filled ring would give b"   " here


def test_the_underscore_in_the_old_build_tag_was_a_flag_byte():
    """`CUBAN 1._02` was a header read without decompressing it: 0x5f is the flag byte that
    follows the first eight literals, so the text is `CUBAN 1.02`."""
    stream = bytes([0xFF]) + b"CUBAN 1." + bytes([0x5F]) + b"02\0\0@"
    assert climax_bad.decompress(stream).startswith(b"CUBAN 1.02")


def test_the_stream_is_found_after_a_leading_uncompressed_block():
    """Hot Wheels puts a 728-byte block in front; ATV and The Italian Job start at +8."""
    body = pack(b"//\r\n// P")
    plain = struct.pack(">2I", 1, 99) + body
    assert climax_bad.stream_start(plain) == climax_bad.HEADER
    skipped = struct.pack(">2I", 0, 16) + bytes(16) + plain
    assert climax_bad.stream_start(skipped) == 24 + climax_bad.HEADER


def test_detection_does_not_need_to_reach_the_stream():
    """Hot Wheels' stream starts at +744, well past the 64 bytes classify sniffs - a
    detector that looked for it would refuse the largest of the three archives."""
    head = struct.pack(">2I", 0, 728) + bytes(56)
    assert climax_bad.looks_like(head)
    assert plugin.is_container("harchive.bad", head)
    assert not plugin.is_container("harchive.arc", head)


def test_a_stream_yielding_almost_nothing_is_not_claimed():
    data = struct.pack(">2I", 1, 4) + pack(b"tiny")
    assert plugin.expand(data) == []
