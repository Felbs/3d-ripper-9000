"""The Blitz Games tagged object stream inside a .gcp package."""

import struct

from gcrip.formats import blitz_obj


def u8(v):
    return bytes([0x01, v])


def nil(v):
    return bytes([0x00, v])


def f32(v):
    return b"\x06" + struct.pack("<f", v)


def text(s):
    return b"\x07" + s.encode() + b"\0"


def test_walks_a_mixed_stream():
    d = u8(4) + text("hubsectors") + b"\x03" + struct.pack("<H", 800) + f32(100.0) + text("")
    vals = blitz_obj.values(d)
    assert [(v.kind, v.value) for v in vals] == [
        ("i", 4),
        ("s", "hubsectors"),
        ("i", 800),
        ("f", 100.0),
        ("s", ""),
    ]
    assert vals[-1].offset == len(d) - 2


def test_tag_zero_carries_a_byte():
    """Treating 0x00 as a terminator stops the walk 0.1% into a real package."""
    d = u8(1) + nil(0xC0) + u8(2)
    assert [(v.kind, v.value) for v in blitz_obj.values(d)] == [("i", 1), ("i", 192), ("i", 2)]
    assert blitz_obj.SIZES[0x00] == 1


def test_walk_stops_on_an_unknown_tag():
    d = u8(1) + b"\xff\xff\xff" + u8(2)
    assert [v.value for v in blitz_obj.values(d)] == [1]
    # a string with no terminator inside the window is not returned either
    assert blitz_obj.values(b"\x07abc") == []
    assert blitz_obj.values(b"\x06\x00\x00") == []  # truncated float


def test_float_runs_are_labelled_by_the_preceding_string():
    d = text("Transworld Navigation Mesh Edge") + b"".join(f32(i) for i in range(30))
    d += text("after") + f32(1.0)  # too short to count
    runs = blitz_obj.float_runs(blitz_obj.values(d))
    assert len(runs) == 1
    label, run = runs[0]
    assert label == "Transworld Navigation Mesh Edge"
    assert len(run) == 30
    assert blitz_obj.strings(d) == ["Transworld Navigation Mesh Edge", "after"]


def test_a_run_at_the_very_end_still_counts():
    d = text("edges") + b"".join(f32(i) for i in range(blitz_obj.MIN_RUN))
    assert [len(r) for _l, r in blitz_obj.float_runs(blitz_obj.values(d))] == [blitz_obj.MIN_RUN]
