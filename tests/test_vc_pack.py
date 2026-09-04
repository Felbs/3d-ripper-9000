"""The Visual Concepts `.IFF` codec (gcrip.formats.vc_pack).

A 24-bit match word split 10:14 - length on top, distance underneath.  Every earlier attempt
read the two spare bits as a control sitting beside an 8-bit length, which is why nine members
appeared to need different lengths from identical bytes.

The stream is input-driven: it is decoded to the end of the member, because the u32 at +21 is
the first record's size field and a member may hold several records.  The encoder trims
trailing zero-producing ops - sometimes mid-match-word - and the decoder gives the zeros back
by padding to the record tiling the output itself declares.

Three real members from NBA 2K3's ``game.dat`` are embedded below, one for each way a real
stream ends: exactly (LINES.IFF), cleanly trimmed between ops (CTIME.IFF, one zero short) and
trimmed inside a match word (AH999.IFF, the stale first byte of the cut match still present).
AH999 is one of the nine members whose identical bytes once appeared to need different
lengths - the contradiction that suggested hidden adaptive state, dissolved by the 10:14 split.
"""

from __future__ import annotations

import struct

import pytest

from gcrip.formats import vc_pack


def pack(header: bytes, tag: bytes, items) -> bytes:
    """Build a member: 16 verbatim bytes, then flag bytes and items.

    `items` are ``bytes`` for a literal run and ``(length, distance)`` for a match.
    """
    assert len(header) == vc_pack.VERBATIM
    ops = []
    for item in items:
        if isinstance(item, bytes):
            ops.extend(("l", b) for b in item)
        else:
            length, distance = item
            ops.append(("m", (length << 14) | (distance - 1)))
    body = bytearray()
    for i in range(0, len(ops), 8):
        group = ops[i : i + 8]
        flags = 0
        payload = bytearray()
        for k, (kind, val) in enumerate(group):
            if kind == "l":
                payload.append(val)
            else:
                flags |= 1 << k
                payload += struct.pack(">I", val)[1:]
        body.append(flags)
        body += payload
    return header + bytes(body)


def expected(header: bytes, items) -> bytes:
    out = bytearray(header)
    for item in items:
        if isinstance(item, bytes):
            out += item
        else:
            length, distance = item
            for _ in range(length):
                out.append(out[-distance])
    return bytes(out)


def real(items, tag: bytes = b"RTXT"):
    """A member shaped like the real ones: sixteen verbatim bytes, then a flag byte, then the
    tag and the payload length as eight literals - which is where the reader takes both from.

    Two passes, because the length the member declares is part of its own output.
    """
    def build(size: int):
        first = [tag + struct.pack(">I", size)]
        return pack(b"\x00" * vc_pack.VERBATIM, tag, first + list(items)), expected(
            b"\x00" * vc_pack.VERBATIM, first + list(items)
        )

    _, out = build(0)
    body, out = build(len(out) - vc_pack.VERBATIM)
    return body, out


def test_a_literal_run_comes_back_unchanged():
    body, want = real([b"hello world"])
    assert vc_pack.unpack(body) == want


def test_a_match_copies_from_the_output():
    body, want = real([b"abcd", (4, 4)])
    got = vc_pack.unpack(body)
    assert got == want
    assert got[-8:] == b"abcdabcd"


def test_an_overlapping_match_runs_like_a_ring():
    """distance 1 is how a run of one byte is stored, so the copy must be byte at a time."""
    body, want = real([b"z", (10, 1)])
    assert vc_pack.unpack(body)[-11:] == b"z" * 11


def test_the_length_uses_the_top_two_bits_of_the_second_byte():
    """A length of 5 sets a bit that a control-field reading would take for itself; this is
    the case every earlier attempt got wrong."""
    body, want = real([b"abcdefgh", (5, 8)])
    got = vc_pack.unpack(body)
    assert got == want
    assert got[-5:] == b"abcde"


def test_a_ten_bit_length_survives():
    body, want = real([b"abcdefgh", (1000, 8)])
    got = vc_pack.unpack(body)
    assert len(got) - len(want) == 0
    assert got[-8:] == want[-8:]


def test_the_fourteen_bit_distance_reaches_the_top_of_its_range():
    filler = bytes((i * 7 + 3) & 0xFF for i in range(vc_pack.DISTANCE_MASK + 1))
    body, want = real([filler, (4, vc_pack.DISTANCE_MASK + 1)])
    assert vc_pack.unpack(body) == want


def test_a_trimmed_zero_tail_comes_back_as_zeros():
    """The encoder drops ops that only produce zeros; the record size still counts them."""
    body, want = real([b"abcd", (4, 4)])
    hurt = bytearray(body)
    struct.pack_into(">I", hurt, vc_pack.DECLARED_AT, len(want) - vc_pack.VERBATIM + 64)
    got = vc_pack.unpack(bytes(hurt))
    assert len(got) == len(want) + 64
    assert got[len(want) :] == b"\x00" * 64


def test_a_shortfall_beyond_any_real_trim_is_refused():
    """A stream ending kilobytes before its own record tiling is a mis-decode, not a trim."""
    body, want = real([b"abcd", (4, 4)])
    hurt = bytearray(body)
    huge = len(want) - vc_pack.VERBATIM + vc_pack.MAX_PAD + 64
    struct.pack_into(">I", hurt, vc_pack.DECLARED_AT, huge)
    with pytest.raises(vc_pack.PackError, match="short of its own record tiling"):
        vc_pack.unpack(bytes(hurt))


def test_a_distance_reaching_before_the_output_is_refused():
    """A distance longer than the output so far is the check that catches a wrong split of
    the 24-bit word: read the length bits into the distance and it goes off the front."""
    # a whole number of eight-item groups, so the appended flag byte is read as a flag
    body, want = real([b"abcdefgh"])
    word = (4 << 14) | (9999 - 1)
    hurt = bytearray(body + bytes([0x01]) + struct.pack(">I", word)[1:])
    with pytest.raises(vc_pack.PackError, match="reaches before the output"):
        vc_pack.unpack(bytes(hurt))


def test_a_packed_member_is_told_from_a_stored_one_by_the_tag_position():
    body, want = real([b"abcd"])
    assert vc_pack.is_packed(body[:64])
    stored = b"\x00" * 16 + b"RTXT" + b"\x00" * 44
    assert not vc_pack.is_packed(stored)


def test_both_identities_hold_on_a_well_formed_member():
    from gcrip import identities

    body, want = real([b"abcdefgh", (12, 8), b"tail"])
    results = identities.check(vc_pack, body)
    assert not identities.failures(results), "\n".join(str(r) for r in results)
    assert any(r.held is True for r in results)


def test_the_identity_fails_when_the_stream_is_damaged():
    """An identity that cannot fail is not evidence."""
    from gcrip import identities

    body, want = real([b"abcdefgh", (12, 8), b"tail"])
    hurt = bytearray(body)
    huge = len(want) - vc_pack.VERBATIM + vc_pack.MAX_PAD + 128
    struct.pack_into(">I", hurt, vc_pack.DECLARED_AT, huge)
    results = identities.check(vc_pack, bytes(hurt))
    assert any(r.held is False for r in results)


# -- three real members from NBA 2K3's game.dat, one for each way a real stream ends --------

# ends exactly at the end of its own bytes
LINES_MEMBER = bytes.fromhex(
    "e3080100000000000000000000000000004253554100000080f00000000001000302000701000401c01b20110000002d"
    "0200136c6f0061646d0000005041c04444494e472a02000702000f2101401f2e62696e05c02100004000011e25756601"
    "000700180056220100050240700d4948"
)
LINES_DECODED = bytes.fromhex(
    "e30801000000000000000000000000004253554100000080000000000000000000000000000000000000000042535541"
    "000000110000002d00000000000000006c6f61646d00000050414444494e472a50414444494e472a50414444494e472a"
    "6c6f61646d2e62696e0050414444494e472a50414444494e472a50414444494e000000011e2575660000000100005622"
    "000100000000000000000000000d4948"
)

# trimmed cleanly between ops, one zero short of LINES's length
CTIME_MEMBER = bytes.fromhex(
    "000504aba80000000000000000000000004253554100000080f00000000001000302000701000401c01b20110000002d"
    "020013637700646c6f6f70005041c04444494e472a02000702000f2101c01f2e62696e0540230000000001f0ef0b9500"
    "0000000200002b1100011102c0700cf4"
)
CTIME_DECODED = bytes.fromhex(
    "000504aba800000000000000000000004253554100000080000000000000000000000000000000000000000042535541"
    "000000110000002d00000000000000006377646c6f6f700050414444494e472a50414444494e472a50414444494e472a"
    "6377646c6f6f702e62696e0050414444494e472a50414444494e472a5041444400000001f0ef0b950000000200002b11"
    "000100000000000000000000000cf4"
)

# trimmed inside a match word - the stale start of the cut match ends the stream
AH999_MEMBER = bytes.fromhex(
    "00000000000000000000000000000000004253554100000080f00000000001000302000701000401c01b20110000002d"
    "02001361694073747265657401000b5080414444494e472a0200074301000702001f2e62696e05002000000000012fb5"
    "72d5000000000200002b1100220102c0"
)
AH999_DECODED = bytes.fromhex(
    "000000000000000000000000000000004253554100000080000000000000000000000000000000000000000042535541"
    "000000110000002d000000000000000061697374726565740000000050414444494e472a50414444494e472a50414444"
    "61697374726565742e62696e0050414444494e472a50414444494e472a504144000000012fb572d50000000200002b11"
    "0001"
)


def test_a_real_member_that_ends_exactly():
    got = vc_pack.unpack(LINES_MEMBER)
    assert got == LINES_DECODED
    assert got[16:20] == b"BSUA"
    assert b"loadm.bin" in got and b"PADDING*" in got


def test_a_real_member_with_a_trimmed_zero_tail():
    """CTIME's stream stops cleanly one byte before its sibling LINES's length - the final
    zero was trimmed.  It still covers its first record, so nothing is padded."""
    got = vc_pack.unpack(CTIME_MEMBER)
    assert got == CTIME_DECODED
    assert len(got) == len(LINES_DECODED) - 1
    assert b"cwdloop.bin" in got


def test_a_real_member_cut_inside_a_match_word():
    """AH999's trim cut at the container's alignment and left part of a match behind; the
    cut ends the stream.  This member is one of the nine whose identical bytes once seemed
    to need different lengths - the artifact that suggested adaptive state."""
    got = vc_pack.unpack(AH999_MEMBER)
    assert got == AH999_DECODED
    assert b"aistreet.bin" in got
