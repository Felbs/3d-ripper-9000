"""Yuke's YOBJ meshes - the .ymg files of the WWE discs."""

import struct

import numpy as np

from gcrip.formats import yukes_yobj
from gcrip.plugins import yukes_yobj as plugin

QUAD = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
# distinct unit vectors: identical ones stay unit under a shifted read, so they cannot
# show that the +8 convention matters
VARIED = [(0.6, 0.8, 0.0), (0.8, 0.0, 0.6), (0.0, 0.6, 0.8), (0.28, 0.96, 0.0)]
MARKER_AT = 32
POS_BLOCK = 64


def build(
    positions=QUAD,
    normal=(0.0, 0.0, 1.0),
    strip=(0, 1, 2, 3),
    count=None,
    skip=yukes_yobj.BLOCK_SKIP,
    gap=0,
    normals=None,
):
    """A YOBJ with one record.  `skip` is where the arrays sit relative to their offset -
    the format's own answer is 8, and the tests use it to show what other values do."""
    n = len(positions)
    pos_at = POS_BLOCK
    nrm_at = pos_at + (count if count is not None else n) * yukes_yobj.STRIDE + gap
    idx_at = nrm_at + n * yukes_yobj.STRIDE
    strips_at = idx_at + yukes_yobj.INDEX_SKIP
    end = strips_at + 4 + len(strip) * 2
    data = bytearray(end + 16)
    data[0:4] = yukes_yobj.MAGIC
    struct.pack_into(">I", data, 12, MARKER_AT - 8)
    struct.pack_into(">H", data, MARKER_AT + yukes_yobj.COUNT_AT, count if count is not None else n)
    struct.pack_into(">I", data, MARKER_AT, yukes_yobj.MARKER)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.POS_AT, pos_at)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.NRM_AT, nrm_at)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.IDX_AT, idx_at)
    for i, p in enumerate(positions):
        struct.pack_into(">3f", data, pos_at + skip + i * yukes_yobj.STRIDE, *p)
    for i in range(n):
        one = normals[i] if normals else normal
        struct.pack_into(">3f", data, nrm_at + skip + i * yukes_yobj.STRIDE, *one)
    struct.pack_into(">I", data, strips_at, len(strip))
    for i, v in enumerate(strip):
        struct.pack_into(">H", data, strips_at + 4 + i * 2, v)
    return bytes(data)


def test_detection_is_the_magic():
    data = build()
    assert yukes_yobj.is_yobj(data[:64])
    assert plugin.detect("0_2.ymg", data[:64], len(data))
    assert not plugin.detect("0_2.ymg", b"DUMY" + bytes(60), 64)


def test_a_mesh_round_trips():
    (mesh,) = yukes_yobj.meshes(build())
    assert len(mesh.positions) == 4 and len(mesh.indices) == 6
    assert np.allclose(mesh.positions[3], (1.0, 1.0, 0.0))
    assert mesh.unsigned_agreement > 0.99


def test_every_offset_points_eight_bytes_before_its_data():
    """Read the arrays at the offset itself and the normals come out non-unit - which reads
    like an off-by-one in the count rather than a block header, and is how the layout was
    first misread."""
    assert yukes_yobj.meshes(build(skip=0, normals=VARIED)) == []
    assert yukes_yobj.meshes(build(skip=yukes_yobj.BLOCK_SKIP, normals=VARIED)) != []


def test_the_normal_array_must_start_exactly_one_position_array_later():
    """`normals - positions == count * 12` is what ties the record's count to its data."""
    assert yukes_yobj.meshes(build(gap=4)) == []


def test_normals_that_are_not_unit_length_are_refused():
    assert yukes_yobj.meshes(build(normal=(0.0, 0.0, 0.5))) == []


def test_an_index_outside_the_vertex_count_ends_the_strip():
    assert yukes_yobj.meshes(build(strip=(0, 1, 2, 9))) == []


def test_triangles_are_flipped_to_agree_with_their_own_normals():
    """Winding is inconsistent here as it is in Terminal Reality's _smf and A2M's .gc."""
    (mesh,) = yukes_yobj.meshes(build(normal=(0.0, 0.0, -1.0)))
    tri = mesh.indices.reshape(-1, 3).astype(np.int64)
    a, b, c = mesh.positions[tri[:, 0]], mesh.positions[tri[:, 1]], mesh.positions[tri[:, 2]]
    face = np.cross(b - a, c - a)
    face /= np.linalg.norm(face, axis=1)[:, None]
    assert (face @ np.array([0.0, 0.0, -1.0]) > 0.99).all()


def test_the_plugin_builds_one_primitive_a_mesh():
    (scene,) = plugin.extract(build(), "files/bg/0_2.ymg", None)
    assert len(scene.primitives) == 1 and scene.triangles == 2
    assert scene.primitives[0].normals is not None


def test_a_file_that_is_not_yobj_yields_nothing():
    assert yukes_yobj.meshes(b"DUMY" + bytes(256)) == []
    assert plugin.extract(b"DUMY" + bytes(256), "x/point.ymg", None) == []
