"""THQ 'pack' archives (Avatar, Jimmy Neutron, Alien Hominid ...)."""

import struct

from gcrip.formats import thq_pack
from gcrip.plugins import thq_pack as plugin


def build() -> bytes:
    names = b"data/boot.rad\x00data/level.pak\x00"
    entries = 2
    names_off = thq_pack.TABLE + entries * thq_pack.ENTRY
    data_off = names_off + len(names)
    payloads = [b"first-member", b"second-member!!"]
    head = bytearray(data_off)
    body = bytearray()
    placed = []
    for p in payloads:
        placed.append((data_off + len(body), len(p)))
        body += p
    total = data_off + len(body)
    struct.pack_into(">4sIIIII", head, 0, thq_pack.MAGIC, 1, names_off, total, names_off, entries)
    for k, (off, size) in enumerate(placed):
        name_off = 0 if k == 0 else names.index(b"data/level.pak")
        struct.pack_into(">4I", head, thq_pack.TABLE + k * thq_pack.ENTRY, off, size, 0, name_off)
    head[names_off : names_off + len(names)] = names
    return bytes(head) + bytes(body)


def test_members():
    data = build()
    assert thq_pack.is_pack(data[: thq_pack.TABLE])
    mem = thq_pack.members(data)
    assert [(m.name, m.size) for m in mem] == [("data/boot.rad", 12), ("data/level.pak", 15)]
    out = dict(thq_pack.expand(data))
    assert out["data/boot.rad"] == b"first-member"
    assert out["data/level.pak"] == b"second-member!!"


def test_plugin_container_only():
    data = build()
    assert plugin.is_container("c2_DATA.PAK", data[:64])
    assert [n for n, _ in plugin.expand(data)] == ["data/boot.rad", "data/level.pak"]
    assert plugin.detect("x.pak", data[:64], len(data)) is False
    assert plugin.extract(data, "x.pak", None) == []
    assert not thq_pack.is_pack(b"PACK" + bytes(0x20))


def build_v0(names=("xbdspimage.raw", "data/boot.rad"), bodies=(b"raw member", b"rad0 object")):
    """The Jimmy Neutron layout: a 24-byte header and 12-byte entries whose end is the
    name-table offset."""
    table_end = thq_pack.TABLE_V0 + len(names) * thq_pack.ENTRY_V0
    name_blob = b"".join(n.encode() + b"\0" for n in names)
    data_at = table_end + len(name_blob)
    head = bytearray(thq_pack.TABLE_V0)
    head[:4] = thq_pack.MAGIC
    entries = b""
    body = b""
    cursor = 0
    for i, blob in enumerate(bodies):
        entries += struct.pack(">3I", cursor, data_at + len(body), len(blob))
        cursor += len(names[i]) + 1
        body += blob
    struct.pack_into(">5I", head, 4, 0, 0, data_at + len(body), table_end, len(names))
    return bytes(head) + entries + name_blob + body


def test_version_zero_entries_end_where_the_names_begin():
    data = build_v0()
    assert thq_pack.is_pack(data[: thq_pack.TABLE])
    names_off, count = struct.unpack_from(">2I", data, 0x10)
    assert names_off == thq_pack.TABLE_V0 + count * thq_pack.ENTRY_V0


def test_version_zero_members_are_named_and_whole():
    got = dict(thq_pack.expand(build_v0()))
    assert got == {"xbdspimage.raw": b"raw member", "data/boot.rad": b"rad0 object"}


def test_a_zero_size_version_zero_entry_is_skipped_not_fatal():
    """Several Jimmy Neutron entries alias another member's offset with size 0."""
    data = bytearray(build_v0())
    struct.pack_into(">I", data, thq_pack.TABLE_V0 + 8, 0)  # first entry's size
    got = dict(thq_pack.expand(bytes(data)))
    assert set(got) == {"data/boot.rad"}


def test_the_two_versions_are_told_apart_by_the_word_at_four():
    v0 = build_v0()
    assert struct.unpack_from(">I", v0, 4)[0] == 0
    assert thq_pack.is_pack(v0[: thq_pack.TABLE])
