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


def test_the_primitive_matches_what_the_exporter_expects():
    """`Primitive.material` is an index into `scene.materials`, not the material's name.

    Passing the name raised inside the exporter on every mesh and cost Tiger Woods 06 all 665
    of its terrain meshes - 0 triangles from 1,031 models - while every test here passed,
    because none of them touched the export contract.
    """
    long_strip = (0, 1, 2, 3, 4, 2, 1, 0)
    (scene,) = plugin.extract(build(strips=(long_strip,)), "hole.hog/ter.bin", None)
    prim = scene.primitives[0]
    assert isinstance(prim.material, int)
    assert 0 <= prim.material < len(scene.materials)
    assert prim.indices.ndim == 1 and len(prim.indices) % 3 == 0


def test_a_scene_survives_a_real_gltf_export(tmp_path):
    from ripcore.gltf import export

    long_strip = (0, 1, 2, 3, 4, 2, 1, 0)
    (scene,) = plugin.extract(build(strips=(long_strip,)), "hole.hog/ter.bin", None)
    export(scene, tmp_path / scene.name, thumbnail=False)
    assert any(tmp_path.iterdir())


def _arra(kind, count, comps, payload):
    body = struct.pack(">2I", (kind << 24) | count, comps << 18) + payload
    return b"ARRA" + struct.pack(">I", len(body)) + body


def build_named():
    """A RotK-shaped member: colour, uv and position arrays, and one ELDA of two named
    elements whose corners are (position, uv, colour) triples."""
    pos = struct.pack(">12f", 0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1)
    uv = struct.pack(">8h", 0, 0, 1024, 0, 1024, 1024, 0, 1024)
    col = bytes([255, 0, 0, 255] * 4)
    head = b"HEAD" + struct.pack(">I", 8) + bytes(8)
    strip = b"".join(struct.pack(">3H", i, i, i) for i in (0, 1, 3, 2))
    el = bytes(0x1C) + b"\x00\x02dirt9\x00" + b"\x00\x00\x00\x05\xb1\xe0\xb1\xe0\x00\x00\x00\x01"
    el += ea_obg.NAMED_ATTRS + struct.pack(">H", 4) + strip
    el += b"\x00\x02rock\x00" + b"\x01" + ea_obg.NAMED_ATTRS + struct.pack(">H", 3) + strip[:18]
    elda = b"ELDA" + struct.pack(">I", len(el)) + el
    return (
        b"OBG \x01\x05\x00\x00"
        + _arra(0, 4, 1, col)
        + _arra(1, 4, 1, uv)
        + _arra(2, 4, 3, pos)
        + head
        + elda
    )


def test_named_elements_read_rotk_strips():
    data = build_named()
    found = ea_obg.chunks(data)
    named = ea_obg.named_elements(data, found)
    assert [e.name for e in named] == ["dirt9", "rock"]
    assert named[0].corners.shape == (4, 3) and named[1].corners.shape == (3, 3)
    assert ea_obg.typed_array(data, 1, found)[1:] == (4, 1)
    scenes = plugin.extract(data, "ter_1", None)
    assert len(scenes) == 1 and scenes[0].extras["named"]
    sc = scenes[0]
    assert [m.name for m in sc.materials] == ["dirt9", "rock"]
    assert len(sc.primitives[0].indices) == 6 and len(sc.primitives[1].indices) == 3
    assert np.allclose(sc.primitives[0].uvs[3], (1.0, 1.0))  # corner 3 is vertex 2
    assert sc.primitives[0].colors[0].tolist() == [1.0, 0.0, 0.0, 1.0]
