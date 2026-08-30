"""Blitz Games .gcp archives: member directory and package splitting."""

import struct

from gcrip.formats import blitz_gcp
from gcrip.plugins import blitz


def make_archive() -> bytes:
    """Two members with a name table and an entry table, all in 0x800 sectors."""
    sector = blitz_gcp.SECTOR
    m1 = (
        b"\x01\x69\x07" + b"01/02/2005 at 03:04:05 by tester\0" + b"payload one".ljust(0x100, b"\0")
    )
    m2 = b"member two payload".ljust(0x200, b"\0")
    data = bytearray(sector * 6)
    struct.pack_into(">4I", data, 0, 0x47528D02, sector, 0, 2)
    struct.pack_into(">I", data, 0x10, 4)  # entry table sector
    struct.pack_into(">I", data, 0x28, 3)  # name table sector
    names = b"level_one.gcp\0level_two.gcp\0"
    struct.pack_into(">I", data, 0x2C, len(names))
    data[sector : sector + len(m1)] = m1
    data[sector * 2 : sector * 2 + len(m2)] = m2
    data[sector * 3 : sector * 3 + len(names)] = names
    struct.pack_into(">4I", data, sector * 4, 1, 0xAAAA, len(m1), 0)
    struct.pack_into(">4I", data, sector * 4 + blitz_gcp.ENTRY, 2, 0xBBBB, len(m2), 1)
    return bytes(data)


def test_archive_members():
    data = make_archive()
    assert blitz_gcp.is_pack("AllPaks.gcp", data[:64])
    assert blitz_gcp.is_archive(data[:0x40], len(data))
    mem = blitz_gcp.members(data)
    assert [m.name for m in mem] == ["level_one.gcp", "level_two.gcp"]
    assert [m.size for m in mem] == [292, 512]  # stamp + padded payloads
    out = blitz.expand(data)
    assert [n for n, _ in out] == ["level_one.gcp", "level_two.gcp"]
    assert out[0][1].startswith(b"\x01\x69\x07")


def test_member_splits_into_packages():
    sector = blitz_gcp.SECTOR
    stamp = b"\x01\x69\x07" + b"01/02/2005 at 03:04:05 by tester\0"
    member = bytearray(sector * 2)
    struct.pack_into(">3I", member, 0, 0x1234, 0x20, 0)
    member[0 : len(stamp)] = stamp
    member[sector : sector + len(stamp)] = stamp
    out = blitz.expand(bytes(member))
    assert [n for n, _ in out] == ["pkg000_tester.pkg", "pkg001_tester.pkg"]


def test_plugin_does_not_claim_models():
    data = make_archive()
    assert blitz.detect("files/AllPaks.gcp", data[:64], len(data)) is False
    assert blitz.extract(data, "files/AllPaks.gcp", None) == []
