"""Konami KCEO ARCDT archives (Evolution Snowboarding)."""

import struct

from gcrip.formats import kceo
from gcrip.plugins import kceo as plugin


def build(members=(("FL_STG21_00.BPX", 2, 0x400), ("FL_STG21_01.BPX", 3, 0x200))) -> bytes:
    table = kceo.SECTOR
    end = max(s * kceo.SECTOR + sz for _n, s, sz in members)
    head = bytearray(max(end, table + len(members) * kceo.ENTRY))
    head[: len(kceo.MAGIC)] = kceo.MAGIC
    head[len(kceo.MAGIC) : 16] = b" 1.0B\0"[: 16 - len(kceo.MAGIC)]
    struct.pack_into(">2I", head, kceo.HEADER, len(members), table)
    for i, (name, sector, size) in enumerate(members):
        p = table + i * kceo.ENTRY
        head[p : p + len(name)] = name.encode()
        struct.pack_into(">4I", head, p + kceo.NAME, 0, sector, size, 0)
    for name, sector, _size in members:
        at = sector * kceo.SECTOR
        if at + len(name) <= len(head):
            head[at : at + len(name)] = name.encode()
    return bytes(head)


def test_members_are_named_and_sector_addressed():
    d = build()
    ms = kceo.members(d)
    assert [(m.name, m.offset, m.size) for m in ms] == [
        ("FL_STG21_00.BPX", 2 * kceo.SECTOR, 0x400),
        ("FL_STG21_01.BPX", 3 * kceo.SECTOR, 0x200),
    ]
    assert plugin.is_container("FL_STG21.ARC", d[:64])
    got = plugin.expand(d)
    assert [n for n, _ in got] == ["FL_STG21_00.BPX", "FL_STG21_01.BPX"]
    assert got[0][1].startswith(b"FL_STG21_00.BPX")


def test_a_member_running_past_the_end_is_dropped():
    # truncate the archive so the second member's sector no longer exists
    d = build(members=(("A.BPX", 2, 0x400), ("B.BPX", 4, 0x400)))
    assert [m.name for m in kceo.members(d)] == ["A.BPX", "B.BPX"]
    assert [m.name for m in kceo.members(d[: 4 * kceo.SECTOR])] == ["A.BPX"]


def test_rejects_junk():
    assert not kceo.is_kceo(b"nope")
    assert kceo.members(b"KCEO ARCDT" + bytes(64)) == []  # zero count
    assert plugin.detect("x.arc", b"", 0) is False
    assert plugin.extract(b"", "x.arc", None) == []
