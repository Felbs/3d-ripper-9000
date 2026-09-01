"""FSYS archives - Pokemon Colosseum and Pokemon XD."""

import struct

from gcrip.formats import fsys
from gcrip.plugins import fsys as plugin

ENTRIES = (("sensei_b1", b"model bytes here", False), ("hunter_f_b2", b"more bytes", False))


def compress(payload):
    """Encode with the same scheme the reader decodes: literals only, which is valid LZSS."""
    out = bytearray()
    for i in range(0, len(payload), 8):
        chunk = payload[i : i + 8]
        out.append((1 << len(chunk)) - 1)  # every item a literal
        out += chunk
    return bytes(out)


def build(entries=ENTRIES, count=None):
    names_at = 96 + len(entries) * 4
    names = b""
    name_off = {}
    for name, _b, _c in entries:
        name_off[name] = names_at + len(names)
        names += name.encode() + b"\x00"
    details_at = names_at + len(names)
    details_at += -details_at % 32
    data_at = details_at + len(entries) * 80
    data_at += -data_at % 32

    body = b""
    records = []
    for name, payload, comp in entries:
        offset = data_at + len(body)
        if comp:
            packed = compress(payload)
            blob = fsys.LZSS + struct.pack(">3I", len(payload), len(packed) + 16, 0) + packed
            stored = len(blob)
            unpacked = len(payload)
        else:
            stored = len(payload) + 4
            unpacked = stored
            blob = struct.pack(">I", stored) + payload
        records.append((offset, stored, unpacked, name))
        body += blob

    head = bytearray(data_at)
    head[0:4] = fsys.MAGIC
    struct.pack_into(">I", head, 4, 0x102)
    struct.pack_into(">I", head, fsys.COUNT_AT, len(entries) if count is None else count)
    struct.pack_into(">I", head, 20, fsys.POINTERS)
    struct.pack_into(">I", head, fsys.POINTERS_AT, 64)
    struct.pack_into(">I", head, fsys.LENGTH_AT, data_at + len(body))
    struct.pack_into(">3I", head, 64, 96, details_at, data_at)
    for i, (offset, stored, unpacked, name) in enumerate(records):
        at = details_at + i * 80
        struct.pack_into(">I", head, 96 + i * 4, at)
        struct.pack_into(">I", head, at + fsys.OFFSET_AT, offset)
        struct.pack_into(">I", head, at + fsys.UNPACKED_AT, unpacked)
        struct.pack_into(">I", head, at + fsys.SIZE_AT, stored)
        struct.pack_into(">I", head, at + fsys.NAME_AT, name_off[name])
    head[names_at : names_at + len(names)] = names
    return bytes(head) + body


def test_detection_is_the_magic():
    data = build()
    assert fsys.is_fsys(data[:64])
    assert plugin.is_container("people_archive.fsys", data[:64])
    assert not plugin.is_container("people_archive.fsys", b"FSY " + bytes(60))


def test_members_come_out_named():
    got = fsys.members(build())
    assert [m.name for m in got] == ["sensei_b1", "hunter_f_b2"]
    assert not any(m.compressed for m in got)


def test_the_unpacked_size_is_at_eight_and_the_stored_one_at_twenty():
    """They are equal on an uncompressed member, so reading them the wrong way round is
    invisible on the archive you would check first.  A compressed member is where it shows."""
    data = build(entries=(("zap", b"x" * 40, True),))
    (m,) = fsys.members(data)
    assert m.compressed and m.unpacked == 40 and m.size > 40


def test_a_member_that_is_neither_stored_nor_lzss_is_refused():
    """That shape is what says the detail table was read correctly; without it a wrong table
    would carve the archive at invented offsets."""
    data = bytearray(build())
    (m,) = fsys.members(bytes(data))[:1]
    struct.pack_into(">I", data, m.offset, 0xDEADBEEF)
    assert [x.name for x in fsys.members(bytes(data))] == ["hunter_f_b2"]


def test_expand_decompresses_the_lzss_members():
    data = build(entries=(("kept", b"plain data", False), ("zap", b"packed!!", True)))
    got = dict(plugin.expand(data))
    assert got["kept.bin"] == b"plain data"
    assert got["zap.bin"] == b"packed!!"


def test_a_literal_only_stream_round_trips():
    payload = bytes(range(256)) * 3
    assert fsys.decompress(compress(payload), len(payload)) == payload


def test_a_match_reads_the_window_and_the_length_bias_is_three():
    """A clear bit is a two-byte match: twelve bits of window position, four of length + 3."""
    pos = fsys.RING_START
    match = bytes([pos & 0xFF, ((pos >> 4) & 0xF0) | 0])  # length nibble 0 -> three bytes
    stream = bytes([0xFF]) + b"ABCDEFGH" + bytes([0xFE]) + match
    assert fsys.decompress(stream, 11) == b"ABCDEFGHABC"


def test_a_stream_that_cannot_reach_the_declared_length_is_refused():
    assert fsys.decompress(b"A", 100) is None


def test_a_count_larger_than_the_file_is_refused():
    assert fsys.members(build(count=1 << 20)) == []


def test_two_members_sharing_a_name_do_not_collide():
    got = plugin.expand(build(entries=(("same", b"aaaa", False), ("same", b"bbbb", False))))
    assert [n for n, _ in got] == ["same.bin", "same_1.bin"]
