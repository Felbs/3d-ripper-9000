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


def test_a_tiny_block_is_still_a_member():
    """Every block is one member now (cLZSS::Decompress takes exactly one), so a small one is
    a small file, not noise."""
    data = struct.pack(">2I", 1, 4) + pack(b"tiny")
    assert plugin.expand(data) == [("00000_tiny.bin", b"tiny")]


def block(payload: bytes, raw: bool = False) -> bytes:
    """One archive block: kind, inflated size, then the bytes (packed as literals)."""
    if raw:
        return struct.pack(">2I", 0, len(payload)) + payload
    body = pack(payload)
    return struct.pack(">2I", 1, len(payload)) + body


def bah(entries) -> bytes:
    """A one-directory .bah: (path, offset, stored, size) a file."""
    out = bytearray(b"Bark 1.06\0\0\0")
    out += struct.pack(">4I", 0, len(entries), 1, 0)
    for name, offset, stored, size in entries:
        out += struct.pack(">5I", len(name) + 1, offset, stored, size, 0) + name.encode() + b"\0"
    out += struct.pack(">4I", 5, 0, 0, 0) + b"cars\0"  # an empty subdirectory
    return bytes(out)


def test_blocks_follow_each_other_four_byte_aligned():
    a = block(b"ROM 1.26 model bytes")
    b = block(b"BOG 1.01 texture", raw=True)
    data = a + bytes(-len(a) % 4) + b
    got = plugin.expand(data)
    assert [n for n, _ in got] == ["00000_ROM_1.bin", "00001_BOG_1.bin"]
    assert got[0][1] == b"ROM 1.26 model bytes" and got[1][1] == b"BOG 1.01 texture"


def test_the_bah_names_the_members_and_bounds_each_block():
    a = block(b"ROM 1.27 body")
    b = block(b"BOG 1.02 skin")
    data = a + bytes(-len(a) % 4) + b
    off_b = len(a) + (-len(a) % 4)
    index = bah([("body.rom", 0, len(a), 13), ("skin.bog", off_b, len(b), 13)])
    entries = climax_bad.directory(index)
    assert [e.path for e in entries] == ["body.rom", "skin.bog"]
    got = plugin.expand_with(data, "harchive.bad", lambda n: index if n == "harchive.bah" else None)
    assert got == [("body.rom", b"ROM 1.27 body"), ("skin.bog", b"BOG 1.02 skin")]
    # a size that does not match the block's count is refused rather than trusted
    wrong = bah([("body.rom", 0, len(a), 99)])
    assert plugin.expand_with(data, "harchive.bad", lambda n: wrong) == []


def test_a_match_stops_at_the_block_count():
    """cLZSS::read_data emits exactly `count` bytes: a match reaching past it is cut."""
    body = pack(b"abcdefgh") + bytes([0x00, 0xEE, 0xFF])  # an 18-byte match from ring 0xfee
    data = struct.pack(">2I", 1, 12) + body
    ((name, out),) = plugin.expand(data)
    assert out == b"abcdefghabcd"


def test_output_limit_scales_with_the_input():
    """A flat 1<<28 default silently truncated ATV: its 98.8 MB stream stopped at exactly
    268,435,466 bytes - the cap plus one match - and the tail was lost with nothing to say so."""
    from gcrip.formats import climax_bad as cb

    assert cb.output_limit(1024) == cb.DEFAULT_LIMIT  # small streams keep the old floor
    assert cb.output_limit(98_812_344) > 1 << 28  # ATV gets room to finish
    assert cb.output_limit(98_812_344) == 98_812_344 * cb.MAX_EXPANSION
    assert cb.output_limit(1 << 30) == cb.LIMIT_CEILING  # and memory stays bounded


def test_hit_limit_detects_truncation():
    """The loop tests the limit before emitting, so a truncated result overshoots it by up to
    one match - which is why the check is >= and not ==."""
    from gcrip.formats import climax_bad as cb

    assert cb.hit_limit(b"x" * (1 << 28), 1024)
    assert cb.hit_limit(b"x" * ((1 << 28) + 10), 1024)
    assert not cb.hit_limit(b"x" * 4096, 1024)
