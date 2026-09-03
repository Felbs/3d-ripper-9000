"""EA's RenderWare stream container (gcrip.formats.ea_rws).

Call of Duty: Finest Hour and Harry Potter: Goblet of Fire are both full of files that open as
a RenderWare chunk and then refuse to walk, because the ids are EA's own.  The identity that
says the ids are being read right is that the walk covers the file exactly.
"""

from __future__ import annotations

import struct

from gcrip.formats import ea_rws

STAMP = 0x1802FFFF


def chunk(ident: int, body: bytes, version: int = STAMP) -> bytes:
    return struct.pack("<3I", ident, len(body), version) + body


def name_field(text: str) -> bytes:
    raw = text.encode("latin-1") + b"\x00"
    raw += b"\xbf" * (-len(raw) % 4)
    return struct.pack(">I", len(raw)) + raw


def descriptor(name: str, kind: str, path: str) -> bytes:
    body = struct.pack(">I", 0xC0)
    body += name_field(name) + b"\x11" * ea_rws.IDENT_BYTES + name_field(kind) + name_field(path)
    return chunk(ea_rws.DESCRIPTOR, body)


def type_table(names) -> bytes:
    body = bytearray()
    for n in names:
        body += struct.pack(">I", 1)
        raw = n.encode("latin-1") + b"\x00"
        body += raw + b"\xbf" * (-len(raw) % 4)
    return chunk(ea_rws.TYPE_TABLE, bytes(body))


def stream() -> bytes:
    return (
        type_table(["RenderTrigger", "WorldLight", "LevelInfo"])
        + descriptor("Texture Dictionary", "rwID_TEXDICTIONARY", "ps:\\cod\\build\\{x}.txd")
        + descriptor("Bridge_JDB", "rwID_SPLINE", "ps:\\cod\\build\\{y}.spl")
        + chunk(0x0704, b"\x33" * 64)
    )


def test_the_walk_covers_the_file_exactly():
    data = stream()
    got = ea_rws.chunks(data)
    assert len(got) == 4
    assert got[-1].end == len(data)


def test_a_walk_that_does_not_land_on_the_end_returns_nothing():
    """The size identity is the whole reason to believe the ids: a stream one byte long is
    not a stream that was read correctly."""
    assert ea_rws.chunks(stream() + b"\x00") == []


def test_a_chunk_whose_size_runs_past_the_file_is_refused():
    data = bytearray(stream())
    struct.pack_into("<I", data, 4, 1 << 24)
    assert ea_rws.chunks(bytes(data)) == []


def test_assets_come_out_named_and_typed():
    got = ea_rws.assets(stream())
    assert [(a.name, a.kind) for a in got] == [
        ("Texture Dictionary", "rwID_TEXDICTIONARY"),
        ("Bridge_JDB", "rwID_SPLINE"),
    ]
    assert got[0].path.startswith("ps:\\cod\\build")


def test_the_type_table_reads_back():
    assert ea_rws.type_names(stream()) == ["RenderTrigger", "WorldLight", "LevelInfo"]


def test_a_file_without_a_renderware_stamp_is_not_claimed():
    """`GodData.dff` on the same disc walks with the same header shape but carries version 0;
    it is a different container and is not claimed here."""
    other = struct.pack("<3I", 0x0719, 36, 0) + b"\x00" * 36
    assert not ea_rws.is_ea_rws(other)
    assert ea_rws.chunks(other) == []


def test_both_identities_hold_and_can_fail():
    from gcrip import identities

    results = {r.identity.name: r for r in identities.check(ea_rws, stream())}
    assert results["the chunk walk covers the file"].held is True
    assert results["every asset names its type"].held is True

    hurt = bytearray(stream())
    struct.pack_into("<I", hurt, 4, len(hurt))  # a size that swallows the rest
    broken = {r.identity.name: r for r in identities.check(ea_rws, bytes(hurt))}
    assert broken["the chunk walk covers the file"].held is False


# -- the Goblet of Fire variant, which writes a sentinel where a size belongs -----------------


def test_a_chunk_with_no_declared_length_is_bounded_by_the_next_header():
    """Goblet of Fire writes 0xFABB00B5 where Call of Duty writes a size - the same constant
    in every file and every chunk that carries it, so it is a sentinel, not a length."""
    body = b"\x44" * 40
    sized = chunk(0x0704, b"\x55" * 32)
    data = (
        type_table(["RenderTrigger"])
        + struct.pack("<3I", ea_rws.DESCRIPTOR, ea_rws.NO_SIZE, STAMP)
        + body
        + sized
    )
    got = ea_rws.chunks(data)
    assert [c.ident for c in got] == [ea_rws.TYPE_TABLE, ea_rws.DESCRIPTOR, 0x0704]
    assert got[1].size == len(body)
    assert got[-1].end == len(data)


def test_a_sentinel_chunk_at_the_end_takes_the_rest_of_the_file():
    data = type_table(["X"]) + struct.pack("<3I", 0x0704, ea_rws.NO_SIZE, STAMP) + b"\x77" * 64
    got = ea_rws.chunks(data)
    assert len(got) == 2
    assert got[-1].end == len(data)


def test_a_walk_that_cannot_reach_the_end_still_returns_nothing():
    """One Goblet of Fire member ends 24 bytes short on a chunk id that is not one; a partial
    read of an archive is worse than none."""
    data = type_table(["X"]) + chunk(0x0704, b"\x99" * 16) + b"\xbf" * 24
    assert ea_rws.chunks(data) == []
