"""FutureTactics: The Uprising's files.pak - no magic, recognised by its table arithmetic."""

import struct

from gcrip.formats import ft_pak
from gcrip.plugins import ft_pak as plugin

NAMES = ("FRONTEND\\ALIENGICON(1).PNG", "LEVELS\\L1.DFF", "TEX\\SKY.DDS")
BODIES = (b"png member bytes", b"dff member", b"dds")


def build(flag_second=True, count=None):
    n = count if count is not None else len(NAMES)
    table_end = ft_pak.TABLE_AT + n * ft_pak.ENTRY
    head = struct.pack("<I", n)
    body = b""
    offsets = []
    for blob in BODIES:
        offsets.append(table_end + len(body))
        body += blob
        body += bytes(-len(body) % 4)  # the real archive pads members to four bytes
    table = b""
    for i, (name, off) in enumerate(zip(NAMES, offsets, strict=True)):
        word = len(BODIES[i])
        if flag_second and i == 1:
            word |= 1 << 31
        table += name.encode().ljust(ft_pak.NAME, b"\0") + struct.pack("<2I", off, word)
    return head + table + body


def test_recognised_by_the_first_offset_being_the_table_end():
    data = build()
    assert ft_pak.is_ft_pak(data[:64])
    count = struct.unpack_from("<I", data, 0)[0]
    first = struct.unpack_from("<I", data, ft_pak.TABLE_AT + ft_pak.NAME)[0]
    assert first == ft_pak.TABLE_AT + count * ft_pak.ENTRY


def test_a_table_whose_arithmetic_does_not_close_is_refused():
    data = bytearray(build())
    struct.pack_into("<I", data, ft_pak.TABLE_AT + ft_pak.NAME, 999)
    assert not ft_pak.is_ft_pak(bytes(data)[:64])
    assert ft_pak.members(bytes(data)) == []


def test_bit_31_of_the_size_is_a_flag_not_a_size():
    """Read plain, a flagged entry lands two gigabytes past the end of a 143 MB file - which
    reads as a broken table and cost a first pass 56% of the archive."""
    data = build(flag_second=True)
    got = ft_pak.members(data)
    assert [m.name for m in got] == [n.replace("\\", "/") for n in NAMES]
    assert [m.size for m in got] == [len(b) for b in BODIES]
    assert [m.flagged for m in got] == [False, True, False]


def test_members_come_back_whole_and_slash_separated():
    got = dict(plugin.expand(build()))
    assert got["FRONTEND__ALIENGICON(1).PNG"] == BODIES[0]
    assert got["LEVELS__L1.DFF"] == BODIES[1]


def test_an_entry_reaching_past_the_file_is_dropped_not_fatal():
    data = bytearray(build())
    at = ft_pak.TABLE_AT + 2 * ft_pak.ENTRY + ft_pak.NAME
    struct.pack_into("<2I", data, at, 1 << 30, 16)
    got = ft_pak.members(bytes(data))
    assert len(got) == 2  # the other two survive


def test_container_claims_it_without_a_magic():
    data = build()
    assert plugin.is_container("files.pak", data[:64])
    assert not plugin.is_container("other.pak", bytes(64))
