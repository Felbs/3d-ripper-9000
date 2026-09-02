"""Terminal Reality ``_dfm`` header and part table (gcrip.formats.tr_dfm)."""

from __future__ import annotations

import struct

from gcrip.formats import tr_dfm

BAADF00D = bytes.fromhex("0df0adba") * 24


def make_dfm(parts: list[tuple[str, int, tuple]], bones: int = 82,
             skeleton: str = "SOLDIER_DEFAULT.SKL") -> bytes:
    out = bytearray(struct.pack("<6I", 2, 1, len(parts), bones, 1, 0))
    raw = skeleton.encode("latin-1")
    field = raw + b"\0" + BAADF00D[: tr_dfm.HEADER - 24 - len(raw) - 1]
    out += field[: tr_dfm.HEADER - 24]
    assert len(out) == tr_dfm.HEADER
    for name, bone, box in parts:
        nm = name.encode("latin-1")
        out += (nm + b"\0" * (tr_dfm.NAME - len(nm)))[: tr_dfm.NAME]
        out += struct.pack("<I", bone)
        out += struct.pack("<6f", *box)
    return bytes(out)


PARTS = [
    ("binoculars2", 68, (-0.499, -0.519, -0.206, -0.270, 0.008, 0.303)),
    ("canteen", 32, (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0)),
    ("gasmask", 5, (0.0, 0.0, 0.0, 0.5, 0.25, 0.125)),
]


def test_reads_the_part_table():
    m = tr_dfm.mesh(make_dfm(PARTS))
    assert m is not None
    assert m.bone_count == 82
    assert m.skeleton == "SOLDIER_DEFAULT.SKL"
    assert [p.name for p in m.parts] == ["binoculars2", "canteen", "gasmask"]
    assert [p.bone for p in m.parts] == [68, 32, 5]


def test_every_box_is_a_box():
    """min <= max on all three axes, on every record - the check that pins the 58-byte stride."""
    m = tr_dfm.mesh(make_dfm(PARTS))
    for p in m.parts:
        for lo, hi in zip(p.box_min, p.box_max):
            assert lo <= hi


def test_an_inverted_box_is_rejected():
    bad = list(PARTS)
    bad[1] = ("canteen", 32, (1.0, 1.0, 1.0, -1.0, -1.0, -1.0))
    assert tr_dfm.mesh(make_dfm(bad)) is None


def test_a_bone_outside_the_skeleton_is_rejected():
    bad = list(PARTS)
    bad[0] = ("binoculars2", 999, PARTS[0][2])
    assert tr_dfm.mesh(make_dfm(bad)) is None


def test_detection_and_truncation():
    data = make_dfm(PARTS)
    assert tr_dfm.is_dfm(data[:16])
    assert not tr_dfm.is_dfm(struct.pack("<4I", 7, 1, 3, 82))
    assert tr_dfm.mesh(data[:-10]) is None


def test_the_stride_is_fifty_eight():
    """30-byte name, u32 bone, six floats - and 59 parts end at 3,526 on soldier.dfm."""
    assert tr_dfm.NAME + 4 + 24 == tr_dfm.STRIDE
    assert tr_dfm.HEADER + 59 * tr_dfm.STRIDE == 3526
