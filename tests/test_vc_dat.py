"""Visual Concepts DAT archives - NBA 2K2/2K3, NFL 2K3, NCAA Basketball/Football 2K3."""

import struct

from gcrip.formats import vc_dat
from gcrip.plugins import vc_dat as plugin

NAMES = ("PB00.IFF", "BUILD01.DAT", "TEAMS.BIN")
BODIES = (b"packed payload bytes", b"a build table", b"team rows")


def build(magic=b"DAT\x01", pad=12, giant=False):
    payloads = list(BODIES)
    if giant:
        payloads[1] = b"x" * (vc_dat.MAX_MEMBER + 1)
    head = bytearray(vc_dat.TABLE_AT)
    head[:4] = magic
    struct.pack_into(">I", head, vc_dat.COUNT_AT, len(NAMES))

    names = b"\xff" * pad + b"".join(n.encode() + b"\0" for n in NAMES)
    table_end = vc_dat.TABLE_AT + len(NAMES) * vc_dat.ENTRY
    list_end = table_end + len(names)
    base = (list_end + vc_dat.ALIGN - 1) & ~(vc_dat.ALIGN - 1)

    offsets, p = [], 0
    for blob in payloads:
        offsets.append(p)
        p += len(blob)

    table = b""
    for i, off in enumerate(offsets):
        kind = vc_dat.PACKED if NAMES[i].endswith(".IFF") else 0
        table += struct.pack(">6I", 47245 - 15 * i, 0xABCD0000 + i, kind, 0, off, len(payloads[i]))
    body = bytes(head) + table + names
    body += bytes(base - len(body))
    return body + b"".join(payloads)


def test_the_spans_tile_the_file():
    data = build()
    ms = vc_dat.members(data)
    assert [m.name for m in ms] == list(NAMES)
    assert ms[0].offset + sum(m.size for m in ms) == len(data)


def test_the_table_starts_at_36_and_the_word_at_32_is_the_count():
    data = build()
    assert struct.unpack_from(">I", data, vc_dat.COUNT_AT)[0] == len(NAMES)
    first = struct.unpack_from(">6I", data, vc_dat.TABLE_AT)
    assert first[4] == 0 and first[5] == len(BODIES[0])  # offset then size, not size first


def test_offsets_are_relative_to_the_padded_end_of_the_name_list():
    """Measured from the end of the table instead, entry 0 lands inside the names."""
    data = build()
    ms = vc_dat.members(data)
    assert ms and ms[0].offset % vc_dat.ALIGN == 0
    assert data[ms[0].offset : ms[0].offset + len(BODIES[0])] == BODIES[0]


def test_a_name_list_that_does_not_start_where_it_should_is_refused():
    data = bytearray(build())
    at = vc_dat.TABLE_AT + len(NAMES) * vc_dat.ENTRY + vc_dat.LIST_HEADER
    data[at] = 0x01  # unprintable first character
    assert vc_dat.members(bytes(data)) == []


def test_the_kind_word_marks_the_packed_members():
    ms = vc_dat.members(build())
    assert [m.packed for m in ms] == [True, False, False]


def test_both_magics_are_accepted():
    assert vc_dat.is_dat(build(magic=b"DAT\x00")[:64])
    assert vc_dat.is_dat(build(magic=b"DAT\x01")[:64])
    assert not vc_dat.is_dat(b"DAT2" + bytes(60))


def test_a_zero_count_is_refused():
    data = bytearray(build())
    struct.pack_into(">I", data, vc_dat.COUNT_AT, 0)
    assert not vc_dat.is_dat(bytes(data)[:64])
    assert vc_dat.members(bytes(data)) == []


def test_members_over_the_cap_are_skipped_not_emitted():
    """LINES.BIN and PLAYERS.BIN are 477 of NBA 2K3's 827 MB and hold neither geometry nor
    textures; carrying them would cost every worker half a gigabyte."""
    data = build(giant=True)
    assert len(vc_dat.members(data)) == 3
    got = dict(plugin.expand(data))
    assert set(got) == {"PB00.IFF", "TEAMS.BIN"}


def test_container_detects_and_expands():
    data = build()
    assert plugin.is_container("game.dat", data[:64])
    got = dict(plugin.expand(data))
    assert got["BUILD01.DAT"] == BODIES[1]
