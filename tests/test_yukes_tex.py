"""Yuke's .tex texture directories - WWE Day of Reckoning 1 and 2, WrestleMania XIX."""

import struct

from gcrip.formats import tpl as tplfmt
from gcrip.formats import yukes_tex
from gcrip.plugins import yukes_tex as plugin

ENTRIES = (("tooth", 64), ("blood", 96))


def tpl_blob(size):
    return tplfmt.MAGIC + bytes(size - len(tplfmt.MAGIC))


def build(entries=ENTRIES, swap=False, overlap=False, count=None):
    payloads = [(name, tpl_blob(size)) for name, size in entries]
    table_end = yukes_tex.HEADER + len(payloads) * yukes_tex.ENTRY
    head = bytearray(table_end)
    struct.pack_into(
        "<4I", head, 0, len(payloads) if count is None else count, 0x100, 0, yukes_tex.HEADER
    )
    body = b""
    for i, (name, blob) in enumerate(payloads):
        at = yukes_tex.HEADER + i * yukes_tex.ENTRY
        head[at : at + len(name)] = name.encode()
        head[at + yukes_tex.TYPE_AT : at + yukes_tex.TYPE_AT + 3] = yukes_tex.KIND
        offset = table_end + len(body)
        if overlap:
            offset = table_end
        pair = (offset, len(blob)) if swap else (len(blob), offset)
        struct.pack_into("<2I", head, at + yukes_tex.SIZE_AT, *pair)
        body += blob
    return bytes(head) + body


def test_detection_is_the_type_tag_at_thirty_two():
    """It is inside the 64 bytes classify sniffs, which is what makes it usable."""
    data = build()
    assert yukes_tex.is_tex(data[:64])
    assert plugin.is_container("036_0.tex", data[:64])
    assert not plugin.is_container("036_0.pac", data[:64])
    bad = bytearray(data)
    bad[yukes_tex.HEADER + yukes_tex.TYPE_AT] = ord("x")
    assert not yukes_tex.is_tex(bytes(bad)[:64])


def test_members_come_out_named_and_tiling():
    got = yukes_tex.members(build())
    assert [m.name for m in got] == ["tooth", "blood"]
    assert got[0].size == 64 and got[1].size == 96
    assert got[0].offset + got[0].size == got[1].offset


def test_the_size_comes_before_the_offset():
    """Read the other way round the entries overlap and point into their neighbours.  The
    numbers stay plausible - offsets inside the file, sizes under its length - so the swap
    does not announce itself; the overlap check is what catches it."""
    assert yukes_tex.members(build(swap=True)) == []


def test_overlapping_members_are_refused():
    assert yukes_tex.members(build(overlap=True)) == []


def test_an_entry_pointing_past_the_end_is_skipped():
    data = bytearray(build())
    at = yukes_tex.HEADER + yukes_tex.ENTRY  # the second record
    struct.pack_into("<I", data, at + yukes_tex.OFFSET_AT, 1 << 30)
    got = yukes_tex.members(bytes(data))
    assert [m.name for m in got] == ["tooth"]


def test_expand_hands_over_tpl_payloads():
    got = dict(plugin.expand(build()))
    assert set(got) == {"tooth.tpl", "blood.tpl"}
    assert got["tooth.tpl"][:4] == tplfmt.MAGIC
    assert len(got["blood.tpl"]) == 96


def test_two_members_sharing_a_name_do_not_collide():
    got = plugin.expand(build(entries=(("eye", 64), ("eye", 96))))
    assert [n for n, _ in got] == ["eye.tpl", "eye_1.tpl"]
