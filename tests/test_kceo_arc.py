"""Konami KCEO ARCDT archives - Evolution Snowboarding, cluster 2's last disc."""

import struct

from gcrip.formats import kceo_arc
from gcrip.plugins import kceo_arc as plugin

ALIGN = 0x800


def build(entries, align=ALIGN, dirsize=None, tail=0):
    """entries: (name, payload).  Members are laid out on `align` boundaries, which is what the
    real archives do - with gaps of 64 to 2,048 bytes, so they are padded but not packed."""
    count = len(entries)
    data_start = -(-(align + count * kceo_arc.ENTRY) // align) * align
    out = bytearray(data_start)
    out[:16] = b"KCEO ARCDT 1.0B\0"
    struct.pack_into(">3I", out, 16, count, align,
                     count * kceo_arc.ENTRY if dirsize is None else dirsize)
    out[28:align] = b"-" * (align - 28)
    body = bytearray()
    for i, (name, payload) in enumerate(entries):
        off = data_start + len(body)
        at = align + i * kceo_arc.ENTRY
        out[at : at + kceo_arc.NAME] = name.encode().ljust(kceo_arc.NAME, b"\0")
        struct.pack_into(">3I", out, at + kceo_arc.NAME, off // align, len(payload), tail)
        body += payload + bytes(-len(payload) % align)
    return bytes(out + body)


def test_members_come_back_named():
    data = build([("A.BPX", b"AAA" * 100), ("B.BPX", b"BBB" * 50)])
    got = kceo_arc.members(data)
    assert [m.name for m in got] == ["A.BPX", "B.BPX"]
    assert data[got[0].offset : got[0].offset + got[0].size] == b"AAA" * 100


def test_the_directory_size_has_to_be_one_record_a_member():
    """`count * 36` held on every real archive - 1, 5, 75 and 74 entries - so a file whose
    header disagrees is not this format."""
    assert kceo_arc.members(build([("A.BPX", b"x" * 16)], dirsize=999)) == []


def test_a_member_reaching_past_the_file_is_dropped():
    """The sector and size are the only things saying where a member is; a truncated archive
    must yield nothing rather than a slice off the end."""
    data = build([("A.BPX", b"x" * 4096)])
    assert kceo_arc.members(data)
    assert kceo_arc.members(data[: len(data) // 2]) == []


def test_a_nonzero_third_word_is_rejected():
    assert kceo_arc.members(build([("A.BPX", b"x" * 16)], tail=7)) == []


def test_something_else_entirely_is_declined():
    assert not kceo_arc.is_kceo_arc(b"RARC" + bytes(20))
    assert kceo_arc.members(b"RARC" + bytes(200)) == []
    assert not plugin.is_container("x.arc", b"RARC" + bytes(20))


def test_the_plugin_hands_members_out():
    data = build([("A.BPX", b"AAA" * 100), ("B.BPX", b"BBB" * 50)])
    assert plugin.is_container("FL_STG13.ARC", data[:64])
    assert [n for n, _ in plugin.expand(data)] == ["A.BPX", "B.BPX"]


def test_repeated_names_do_not_collide():
    data = build([("A.BPX", b"x" * 32), ("A.BPX", b"y" * 32)])
    assert len({n for n, _ in plugin.expand(data)}) == 2
