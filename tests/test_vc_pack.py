"""The Visual Concepts `.IFF` codec (gcrip.formats.vc_pack).

A 24-bit match word split 10:14 - length on top, distance underneath.  Every earlier attempt
read the two spare bits as a control sitting beside an 8-bit length, which is why nine members
appeared to need different lengths from identical bytes.

The tests below pin the two things that settled it on real data: the stream **arrives** at the
declared length rather than being stopped there, and what comes out carries the tag the member
advertises.
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


def test_a_stream_that_stops_early_is_refused():
    body, want = real([b"abcd", (4, 4)])
    hurt = bytearray(body)
    struct.pack_into(">I", hurt, vc_pack.DECLARED_AT, len(want) - vc_pack.VERBATIM + 64)
    with pytest.raises(vc_pack.PackError, match="short of the declared"):
        vc_pack.unpack(bytes(hurt))


def test_a_distance_reaching_before_the_output_is_refused():
    """A distance longer than the output so far is the check that catches a wrong split of
    the 24-bit word: read the length bits into the distance and it goes off the front."""
    # a whole number of eight-item groups, so the appended flag byte is read as a flag
    body, want = real([b"abcdefgh"])
    word = (4 << 14) | (9999 - 1)
    hurt = bytearray(body + bytes([0x01]) + struct.pack(">I", word)[1:])
    struct.pack_into(">I", hurt, vc_pack.DECLARED_AT, len(want) - vc_pack.VERBATIM + 4)
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
    struct.pack_into(">I", hurt, vc_pack.DECLARED_AT, len(want) - vc_pack.VERBATIM + 128)
    results = identities.check(vc_pack, bytes(hurt))
    assert any(r.held is False for r in results)
