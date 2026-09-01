"""EA OBG terrain - the ter members of the Tiger Woods SHOC archives."""

import struct

import numpy as np

from gcrip.formats import ea_obg
from gcrip.plugins import ea_obg as plugin


def chunk(tag, payload):
    """OBG's size excludes the header - the same convention as TXG, the opposite of SHOC."""
    return tag + struct.pack(">I", len(payload)) + payload


def arra(kind, comps, values):
    head = struct.pack(">2I", (kind << 24) | len(values), comps << 18)
    return chunk(b"ARRA", head + values.astype(">f4").tobytes())


def elda(indices):
    return chunk(b"ELDA", bytes(8) + np.asarray(indices, ">u2").tobytes())


GRID = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0]], "f4")


def build(strips=((0, 1, 2, 3),), extra=b""):
    body = ea_obg.MAGIC + bytes(4) + arra(2, 3, GRID)
    for s in strips:
        body += elda(s)
    return body + extra


def test_the_walk_lands_on_the_last_byte():
    data = build()
    assert sum(8 + c.size for c in ea_obg.chunks(data)) + 8 == len(data)


def test_the_array_header_gives_count_and_components():
    got = ea_obg.positions(build())
    assert got is not None and got.shape == (5, 3)


def test_strips_become_triangles_with_alternating_winding():
    tri = ea_obg.triangles(build(strips=((0, 1, 2, 3),)), 5)
    assert tri.tolist() == [[0, 1, 2], [3, 2, 1]]


def test_a_restart_splits_the_strip_rather_than_joining_it():
    """0xffff is the primitive-restart marker.  Forty of the disc's 1,855 elements reach it,
    and reading it as an index makes them look like overruns."""
    tri = ea_obg.triangles(build(strips=((0, 1, 2, ea_obg.RESTART, 1, 2, 3),)), 5)
    assert tri.tolist() == [[0, 1, 2], [1, 2, 3]]


def test_degenerate_triangles_are_dropped():
    tri = ea_obg.triangles(build(strips=((0, 0, 0, 1, 2),)), 5)
    assert all(len(set(t)) == 3 for t in tri.tolist())


def test_an_out_of_range_strip_is_skipped_not_clamped():
    tri = ea_obg.triangles(build(strips=((0, 1, 900),)), 5)
    assert tri.size == 0


def test_the_plugin_builds_one_scene_with_a_material():
    long_strip = (0, 1, 2, 3, 4, 2, 1, 0)
    (scene,) = plugin.extract(build(strips=(long_strip,)), "hole.hog/ter.bin", None)
    assert len(scene.primitives) == 1
    assert scene.primitives[0].positions.shape == (5, 3)
    assert scene.materials and scene.extras["format"] == "ea_obg"


def test_a_member_with_almost_no_geometry_is_not_claimed():
    """A couple of triangles is noise, not terrain."""
    assert plugin.extract(build(strips=((0, 1, 2),)), "hole.hog/ter.bin", None) == []
