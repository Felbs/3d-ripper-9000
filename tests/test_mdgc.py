"""MDGC0200 level meshes (Superman: Shadow of Apokolips)."""

import struct

import numpy as np

from gcrip.formats import mdgc
from gcrip.plugins import mdgc as plugin

# a unit square as two strips' worth of corners, plus a spare vertex
VERTS = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0)]


def build(strip=(0, 1, 2, 3), subheader: int = 40, prim: int = 0x98) -> bytes:
    n = len(VERTS)
    positions = b"".join(struct.pack(">3f", *v) for v in VERTS)
    dl = bytes(subheader) + bytes([prim]) + struct.pack(">H", len(strip))
    dl += b"".join(struct.pack(">3H", i, i, i) for i in strip)
    colours = bytes(n * 4)
    head = bytearray(mdgc.HEADER)
    struct.pack_into(">I", head, 4, mdgc.TAG)
    struct.pack_into(">I", head, 6 * 4, n)  # w6 vertex count
    struct.pack_into(">I", head, 5 * 4, len(strip))  # w5 corner count
    struct.pack_into(">I", head, 13 * 4, len(positions))  # w13 colours
    struct.pack_into(">I", head, 11 * 4, len(positions) + len(colours))  # w11 display list
    return MAGIC_HEAD + bytes(head) + positions + colours + dl


MAGIC_HEAD = mdgc.MAGIC + bytes(56)


def test_reads_a_strip_through_the_display_list():
    d = build()
    ms = mdgc.meshes(d)
    assert len(ms) == 1
    m = ms[0]
    assert len(m.positions) == 5
    assert len(m.indices) == 6  # a four-vertex strip is two triangles
    assert m.colors is not None and len(m.colors) == 5
    # the strip indexes the block's own vertex array
    assert int(m.indices.max()) < len(m.positions)


def test_the_list_is_found_after_a_variable_sub_header():
    """w11 does not point at the first opcode - a sub-header of varying length sits in front."""
    for pad in (40, 52, 56):
        assert len(mdgc.meshes(build(subheader=pad))[0].indices) == 6


def test_strip_stitching_triangles_are_dropped():
    # repeating a vertex is how strips join runs; those triangles have no area
    d = build(strip=(0, 1, 2, 2, 2, 3))
    m = mdgc.meshes(d)[0]
    p = m.positions[m.indices].reshape(-1, 3, 3)
    area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    assert (area > 1e-9).all()


def test_other_primitives_are_understood():
    assert len(mdgc.meshes(build(strip=(0, 1, 2, 3), prim=0x90))[0].indices) == 3  # triangles
    assert len(mdgc.meshes(build(strip=(0, 1, 2, 3), prim=0x80))[0].indices) == 6  # quads


def test_rejects_junk_and_bad_indices():
    assert mdgc.meshes(b"nope") == []
    assert not mdgc.is_mdgc(b"MDGC0100")
    # a position index past the vertex array must stop the walk, not be trusted
    assert mdgc.meshes(build(strip=(0, 1, 99))) == []


def test_plugin_makes_one_scene_per_block():
    scenes = plugin.extract(build(), "files/L95.dgc", None)
    assert len(scenes) == 1
    assert scenes[0].name == "L95"
    assert scenes[0].triangles == 2
    assert plugin.detect("files/L95.dgc", mdgc.MAGIC, 4096) is True
    assert plugin.extract(b"nope", "x.dgc", None) == []
