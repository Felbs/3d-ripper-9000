"""JAM2 archives - Charlie and the Chocolate Factory."""

import struct

from gcrip.formats import jam2
from gcrip.plugins import jam2 as plugin


def build(names=("FESPLASH", "DFE000AB"), exts=("", "TPL"), tail=b"\xff\x00\x00\x00", junk=True):
    payloads = [b"// Atlas Flash", b"\x00\x20\xaf\x30 texture bytes"]
    header = bytearray(jam2.NAMES_AT)
    header[:4] = jam2.MAGIC
    struct.pack_into("<2H", header, jam2.COUNTS_AT, len(names), len(exts))
    header[12:16] = b"none"

    table = b"".join(n.encode().ljust(jam2.NAME, b"\0") for n in names)
    table += b"".join(e.encode().ljust(jam2.EXT, b"\0") for e in exts)
    records_at = jam2.NAMES_AT + len(table) + jam2.GAP
    count = len(payloads) + (1 if junk else 0)
    body_at = records_at + count * jam2.RECORD

    offsets, p = [], body_at
    for blob in payloads:
        offsets.append(p)
        p += jam2.MEMBER_HEADER + len(blob)

    records = b""
    for i, off in enumerate(offsets):
        records += struct.pack("<2HI", i % len(names), 1, off)
    if junk:  # a record whose offset lands on something that is not a member header
        records += struct.pack("<2HI", 0, 1, body_at + 3)

    struct.pack_into("<I", header, 8, len(table) + jam2.GAP + len(records))
    out = bytes(header) + table + bytes(jam2.GAP) + records
    assert len(out) == body_at, (len(out), body_at)
    for blob in payloads:
        out += struct.pack("<2I", len(blob), len(blob)) + tail.ljust(24, b"\0") + blob
    return out


def test_members_are_named_from_the_two_tables():
    ms = jam2.members(build())
    assert [m.name for m in ms] == ["FESPLASH.TPL", "DFE000AB.TPL"]


def test_the_size_is_at_the_member_written_twice():
    data = build()
    (first, second) = jam2.members(data)
    assert data[first.offset : first.offset + 2] == b"//"
    assert data[second.offset : second.offset + 4] == b"\x00\x20\xaf\x30"
    assert first.size == len(b"// Atlas Flash")


def test_a_record_that_does_not_land_on_two_equal_words_is_rejected():
    """That repetition is the only thing separating a real record from a junk one."""
    assert len(jam2.members(build(junk=True))) == 2
    assert len(jam2.members(build(junk=False))) == 2


def test_the_bytes_after_the_two_sizes_are_not_always_zero():
    """They are zero on the archives tagged `safe` and carry flags on the ones tagged `none`;
    checking them throws away every member of the big level archives."""
    assert len(jam2.members(build(tail=b"\x00" * 4))) == 2
    assert len(jam2.members(build(tail=b"\xff\x00\x00\x00"))) == 2


def test_records_start_four_bytes_after_the_extension_table():
    data = bytearray(build())
    names_n, exts_n = struct.unpack_from("<2H", data, jam2.COUNTS_AT)
    at = jam2.NAMES_AT + names_n * jam2.NAME + exts_n * jam2.EXT
    struct.pack_into("<I", data, at, 0xDEADBEEF)  # the gap word is not a record
    assert len(jam2.members(bytes(data))) == 2


def test_container_detects_on_the_magic_only():
    assert plugin.is_container("FeSplash.JAM", jam2.MAGIC + bytes(60))
    assert not plugin.is_container("INTROUI.JAM", b"LJAM" + bytes(60))
    got = dict(plugin.expand(build()))
    assert got["DFE000AB.TPL"].startswith(b"\x00\x20\xaf\x30")
