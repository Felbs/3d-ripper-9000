"""High Voltage FSTA .jam archives (Billy & Mandy, Kids Next Door)."""

import struct

from gcrip.formats import fsta
from gcrip.plugins import fsta as plugin

NAMES = [b"ART", b"BBAY4", b"FROG"]
EXTS = [b"", b"TPL", b"MNG"]


def build(members=((1, 1), (2, 2)), pad_entries: int = 3) -> bytes:
    names_at = fsta.NAMES_AT
    ext_at = names_at + len(NAMES) * fsta.NAME_LEN
    table = ext_at + len(EXTS) * fsta.EXT_LEN
    directory = fsta.SECTOR
    head = bytearray(directory)
    head[:4] = fsta.MAGIC
    struct.pack_into("<2H", head, 28, len(NAMES), len(EXTS))
    for i, n in enumerate(NAMES):
        head[names_at + i * fsta.NAME_LEN : names_at + i * fsta.NAME_LEN + len(n)] = n
    for i, e in enumerate(EXTS):
        head[ext_at + i * fsta.EXT_LEN : ext_at + i * fsta.EXT_LEN + len(e)] = e
    body = bytearray()
    rows = bytearray()
    rows += bytes(pad_entries * 4)  # the per-group index this reader does not decode
    for ni, ei in members:
        offset = directory + len(body)
        payload = b"%s payload" % NAMES[ni]
        body += payload + bytes((-len(payload)) % fsta.SECTOR)
        rows += struct.pack("<2H2I", ni, ei, offset, len(payload))
    head[table : table + len(rows)] = rows
    struct.pack_into("<I", head, 8, directory)
    return bytes(head) + bytes(body)


def test_members_are_named_from_the_two_tables():
    d = build()
    es = fsta.entries(d)
    assert [(e.name, e.ext) for e in es] == [("BBAY4", "TPL"), ("FROG", "MNG")]
    assert [e.filename for e in es] == ["BBAY4.TPL", "FROG.MNG"]
    assert plugin.is_container("Bbay4.JAM", d[:64])
    assert [n for n, _ in plugin.expand(d)] == ["BBAY4.TPL", "FROG.MNG"]
    assert plugin.expand(d)[0][1].startswith(b"BBAY4 payload")


def test_entries_are_found_despite_the_unknown_group_index():
    """The table is not uniform, so entries are validated rather than walked at a fixed stride."""
    a = fsta.entries(build(pad_entries=3))
    b = fsta.entries(build(pad_entries=7))
    assert [e.filename for e in a] == [e.filename for e in b]


def test_offsets_must_be_sector_aligned_and_inside_the_file():
    d = bytearray(build())
    # point the first entry somewhere unaligned: it must be rejected, not trusted
    names_at = fsta.NAMES_AT + len(NAMES) * fsta.NAME_LEN + len(EXTS) * fsta.EXT_LEN + 12
    struct.pack_into("<I", d, names_at + 4, fsta.SECTOR + 1)
    assert all(e.offset % fsta.SECTOR == 0 for e in fsta.entries(bytes(d)))


def test_rejects_junk():
    assert not fsta.is_fsta(b"FSTA" + bytes(28))  # zero counts
    assert not fsta.is_fsta(b"nope")
    assert fsta.entries(b"nope") == []
    assert plugin.detect("x.jam", b"FSTA", 4) is False
    assert plugin.extract(b"", "x.jam", None) == []


def test_repeated_names_are_kept_apart():
    d = build(members=((1, 1), (1, 1)))
    assert [n for n, _ in plugin.expand(d)] == ["BBAY4.TPL", "BBAY4_001.TPL"]
