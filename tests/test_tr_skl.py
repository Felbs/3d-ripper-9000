"""Terminal Reality ``.SKL`` skeletons (gcrip.formats.tr_skl).

Built here rather than checked in.  The tests exercise the checks that identified the 36-byte
stride on the real files: names decode, one root, and no parent points forward.
"""

from __future__ import annotations

import struct

from gcrip.formats import tr_skl

BAADF00D = bytes.fromhex("0df0adba") * 8


def make_skl(bones: list[tuple[str, int]], version: int = 2) -> bytes:
    out = bytearray(struct.pack("<2I", version, len(bones)))
    for name, parent in bones:
        raw = name.encode("latin-1")
        # the real files pad with the debug fill, not zeroes - that is what made the records
        # look variable-length
        field = raw + b"\0" + BAADF00D[: tr_skl.NAME - len(raw) - 1]
        out += field[: tr_skl.NAME]
        out += struct.pack("<i", parent)
    return bytes(out)


BIPED = [
    ("Bip01 Pelvis", -1),
    ("Bip01 L Dress_B01", 0),
    ("Bip01 Spine", 0),
    ("Bip01 Spine1", 2),
    ("Bip01 R Thigh", 0),
    ("Bip01 R Calf", 4),
]


def test_reads_the_hierarchy_through_the_debug_fill():
    got = tr_skl.bones(make_skl(BIPED))
    assert [b.name for b in got] == [n for n, _ in BIPED]
    assert [b.parent for b in got] == [p for _, p in BIPED]
    assert got[5].name == "Bip01 R Calf"
    assert got[got[5].parent].name == "Bip01 R Thigh"


def test_the_table_is_in_topological_order():
    """No parent points forward on the real skeletons, so one pass suffices."""
    got = tr_skl.bones(make_skl(BIPED))
    for i, b in enumerate(got):
        assert b.parent < i


def test_a_forward_parent_is_rejected():
    """A wrong stride scatters the parents; a half-read skeleton is worse than none."""
    bad = [("Bip01 Pelvis", -1), ("Bip01 Spine", 5), ("a", 0), ("b", 0), ("c", 0), ("d", 0)]
    assert tr_skl.bones(make_skl(bad)) == []


def test_two_roots_are_rejected():
    bad = [("Bip01 Pelvis", -1), ("Other", -1)]
    assert tr_skl.bones(make_skl(bad)) == []


def test_a_parent_out_of_range_is_rejected():
    bad = [("Bip01 Pelvis", -1), ("Spine", 99)]
    assert tr_skl.bones(make_skl(bad)) == []


def test_detection_and_truncation():
    data = make_skl(BIPED)
    assert tr_skl.is_skl(data[:8])
    assert not tr_skl.is_skl(struct.pack("<2I", 7, 4))  # wrong version
    assert not tr_skl.is_skl(struct.pack("<2I", 2, 0))  # no bones
    assert tr_skl.bones(data[:-8]) == []


def test_the_stride_is_thirty_six():
    """82 bones end at byte 2,960 on SOLDIER_DEFAULT.SKL - the arithmetic that pinned it."""
    assert tr_skl.HEADER + 82 * tr_skl.STRIDE == 2960
    assert tr_skl.NAME + 4 == tr_skl.STRIDE
