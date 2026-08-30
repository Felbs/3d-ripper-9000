"""Free Radical P4CK / P5CK / P8CK archives - TimeSplitters 2, Future Perfect, Second Sight."""

import gzip
import struct

from gcrip.formats import frd_pak
from gcrip.plugins import frd_pak as plugin

BODIES = (b"first member data", b"second member data!!")


def sized(magic=b"P4CK", shape="named", compress=False):
    """The layout where the three header words are byte counts."""
    payloads = []
    for blob in BODIES:
        payloads.append(gzip.compress(blob, mtime=0) if compress else blob)

    body = bytearray(frd_pak.HEADER)
    offsets = []
    for blob in payloads:
        offsets.append(len(body))
        body += blob
        body += bytes(-len(body) % 4)

    names = b""
    table = b""
    for i, (blob, offset) in enumerate(zip(payloads, offsets, strict=True)):
        stored = len(blob) if compress else 0
        size = len(BODIES[i]) if compress else len(blob)
        if shape == "named":
            table += struct.pack("<4I", len(table) + 0, offset, size, stored)  # patched below
        elif shape == "hashed":
            table += struct.pack("<4I", 0xABCD0000 + i, offset, size, stored)
        else:
            name = f"data/member{i}.war".encode().ljust(frd_pak.INLINE_NAME, b"\0")
            table += name + struct.pack("<3I", offset, size, stored)

    if shape == "named":
        table = b""
        cursor = 0
        for i, (blob, offset) in enumerate(zip(payloads, offsets, strict=True)):
            stored = len(blob) if compress else 0
            size = len(BODIES[i]) if compress else len(blob)
            at = len(payloads) * frd_pak.NAMED + cursor
            table += struct.pack("<4I", at, offset, size, stored)
            cursor += len(f"data/member{i}.war") + 1
        names = b"".join(f"data/member{i}.war".encode() + b"\0" for i in range(len(payloads)))

    struct.pack_into("<4s3I", body, 0, magic, len(body), len(table), len(names))
    return bytes(body) + table + names


def counted():
    """The layout where the words are a table offset, an entry count and a name offset."""
    body = bytearray(frd_pak.HEADER)
    offsets = []
    for blob in BODIES:
        offsets.append(len(body))
        body += blob
        body += bytes(-len(body) % 4)
    names_at = len(body)
    names = b"".join(f"game/demos/demo{i}.raw".encode() + b"\0" for i in range(len(BODIES)))
    body += names
    table_at = len(body)
    cursor = 0
    table = b""
    for blob, offset in zip(BODIES, offsets, strict=True):
        table += struct.pack("<3I", cursor, len(blob), offset)
        cursor += len("game/demos/demo0.raw") + 1
    struct.pack_into("<4s3I", body, 0, b"P8CK", table_at, len(BODIES), names_at)
    return bytes(body) + table


def test_the_sized_layout_sums_to_the_file_length():
    data = sized()
    body, table, names = struct.unpack_from("<3I", data, 4)
    assert body + table + names == len(data)
    got = frd_pak.members(data)
    assert [m.name for m in got] == ["data/member0.war", "data/member1.war"]


def test_a_name_offset_is_measured_from_the_table_not_the_name_block():
    data = sized()
    body, table, _names = struct.unpack_from("<3I", data, 4)
    first = struct.unpack_from("<I", data, body)[0]
    assert first == table  # the first name sits exactly at the end of the table


def test_inline_entries_carry_the_name_in_place_of_the_offset():
    got = frd_pak.members(sized(shape="inline"))
    assert [m.name for m in got] == ["data/member0.war", "data/member1.war"]


def test_hashed_entries_fall_back_to_the_key():
    got = frd_pak.members(sized(shape="hashed"))
    assert all(m.name.startswith("abcd") for m in got)


def test_the_counted_layout_is_told_apart_by_arithmetic_not_the_magic():
    data = counted()
    body, table, _names = struct.unpack_from("<3I", data, 4)
    assert body + table * frd_pak.TRAILING == len(data)
    got = frd_pak.members(data)
    assert [m.name for m in got] == ["game/demos/demo0.raw", "game/demos/demo1.raw"]
    assert [m.size for m in got] == [len(b) for b in BODIES]


def test_the_fourth_word_is_the_stored_length_and_gzip_members_are_unpacked():
    """Reading the third word as the stored length walks off the end of the data region."""
    data = sized(compress=True)
    got = frd_pak.members(data)
    assert all(m.stored != m.size for m in got)  # the two words disagree once it is packed
    out = dict(plugin.expand(data))
    assert list(out.values()) == list(BODIES)


def test_the_gzip_header_supplies_a_name_the_table_does_not_have():
    body = bytearray(frd_pak.HEADER)
    blob = gzip.compress(BODIES[0], mtime=0)
    blob = blob[:3] + bytes([blob[3] | 0x08]) + blob[4:10] + b"prop_all_gcas.war\0" + blob[10:]
    offset = len(body)
    body += blob
    table = struct.pack("<4I", 0x12345678, offset, len(BODIES[0]), len(blob))
    struct.pack_into("<4s3I", body, 0, b"P5CK", len(body), len(table), 0)
    got = dict(plugin.expand(bytes(body) + table))
    assert "prop_all_gcas.war" in got


def test_container_detects_on_the_magic_only():
    assert plugin.is_container("l_50_AR.pak", b"P8CK" + bytes(60))
    assert not plugin.is_container("DATA.PAK", b"pack" + bytes(60))
