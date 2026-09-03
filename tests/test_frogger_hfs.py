"""Frogger: Ancient Shadow's `hfs\\n` archive (gcrip.formats.frogger_hfs).

An earlier pass read the first directory block and left the rest open.  The directory is a
contiguous run of 2,048-byte blocks, and three exact numbers close it: the table ends where the
data begins, the blocks chain by their spans, and the two together are the whole file.
"""

from __future__ import annotations

import struct

from gcrip.formats import frogger_hfs as hfs


def build(counts, spans, first_size=64):
    """An archive whose directory is `len(counts)` blocks and whose members follow."""
    n = len(counts)
    data_at = n * hfs.BLOCK
    directory = bytearray()
    offsets = []
    for i, (count, span) in enumerate(zip(counts, spans)):
        block = bytearray(hfs.BLOCK)
        struct.pack_into("<4s3I", block, 0, hfs.MAGIC, span, count, data_at)
        for k in range(count):
            struct.pack_into(
                "<2I", block, hfs.HEADER + k * hfs.ENTRY, k | hfs.SECTOR_FLAG, first_size
            )
            offsets.append(data_at + k * hfs.SECTOR)
        directory += block
        data_at += span
    body = bytearray(data_at - n * hfs.BLOCK)
    for off in offsets:
        at = off - n * hfs.BLOCK
        if at + 4 <= len(body):
            body[at : at + 4] = hfs.MEMBER_MAGIC
    return bytes(directory + body), offsets


def test_the_table_ends_where_the_data_begins():
    data, _ = build([8, 4, 2], [4096, 4096, 4096])
    got = hfs.blocks(data)
    assert len(got) == 3
    assert len(got) * hfs.BLOCK == got[0].data_at


def test_the_blocks_chain_by_their_spans():
    data, _ = build([2, 2, 2], [4096, 8192, 2048])
    got = hfs.blocks(data)
    assert [b.data_at for b in got] == [3 * hfs.BLOCK, 3 * hfs.BLOCK + 4096,
                                        3 * hfs.BLOCK + 4096 + 8192]
    held, detail = hfs._blocks_chain_by_span(data)
    assert held is True and "2 of 2" in detail


def test_the_table_and_the_spans_are_the_whole_file():
    data, _ = build([2, 2], [4096, 4096])
    held, detail = hfs._spans_and_table_account_for_the_file(data)
    assert held is True, detail


def test_a_span_that_does_not_reach_the_next_block_is_caught():
    data, _ = build([2, 2], [4096, 4096])
    hurt = bytearray(data)
    struct.pack_into("<I", hurt, 4, 2048)  # block 0 now covers half what it should
    held, _ = hfs._blocks_chain_by_span(bytes(hurt))
    assert held is False


def test_members_land_on_their_magic():
    data, offsets = build([4, 3], [8192, 8192])
    got = hfs.members(data)
    assert len(got) == 7
    assert [m.offset for m in got] == offsets
    for m in got:
        assert data[m.offset : m.offset + 4] == hfs.MEMBER_MAGIC


def test_the_walk_stops_at_the_first_block_without_the_magic():
    data, _ = build([2, 2], [4096, 4096])
    hurt = bytearray(data)
    hurt[hfs.BLOCK : hfs.BLOCK + 4] = b"xxxx"
    assert len(hfs.blocks(bytes(hurt))) == 1


def test_a_file_that_is_not_an_archive_is_declined():
    assert hfs.blocks(b"not an archive at all") == []
    assert not hfs.is_hfs(b"nope")
