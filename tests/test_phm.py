"""Neversoft PHM models - Spawn: Armageddon, The Scorpion King."""

import struct

import numpy as np

from gcrip.formats import phm
from gcrip.plugins import phm as plugin


def vertex(pos, nrm, uv=(512, 512)):
    """One 20-byte record: uv, position, normal/4096, then -1, -1."""
    n = [int(round(c * phm.NORMAL_SCALE)) for c in nrm]
    return struct.pack(">10h", uv[0], uv[1], *pos, *n, -1, -1)


def build(verts, indices, header_extra=b"", names=b"SPAWNTPAGE02\0"):
    head = bytearray(64)
    struct.pack_into(">3I", head, 0, 0, 1, 64)
    body = b"".join(vertex(p, n) for p, n in verts)
    idx = struct.pack(f">{len(indices)}H", *indices)
    # a small table, then the index array, then the vertices - offsets are discovered, not fixed
    table_at = 64
    pad = bytes(256 - table_at - 16) + names
    idx_off = 512
    vert_off = idx_off + len(idx)
    tbl = struct.pack(">2I", len(indices), idx_off) + struct.pack(">2I", len(verts), vert_off)
    out = bytearray(head + tbl + pad)
    out += bytes(idx_off - len(out)) + idx + body
    return bytes(out)


def _quad():
    verts = [((0, 0, 0), (0, 0, 1)), ((100, 0, 0), (0, 0, 1)),
             ((0, 100, 0), (0, 0, 1)), ((100, 100, 0), (0, 0, 1))]
    return build(verts, [0, 1, 2, 3])


def test_the_vertex_array_is_found_by_its_unit_normals():
    """The identity that pins stride, offset and field position at once: on the real file the
    normals are unit length for every one of 1,987 vertices, and a wrong stride smears them."""
    m = phm.mesh(_quad())
    assert m is not None
    assert len(m.positions) == 4
    assert np.allclose(np.linalg.norm(m.normals, axis=1), 1.0, atol=0.01)


def test_the_index_array_is_found_by_its_range():
    """Its values run exactly 0 .. vertices-1, which is what tells it apart from the vertices."""
    m = phm.mesh(_quad())
    assert m.indices.max() == 3
    assert m.indices.shape[1] == 3


def test_uvs_and_positions_come_out_separately():
    m = phm.mesh(_quad())
    assert m.uvs.shape == (4, 2) and 0.0 <= m.uvs.min() <= m.uvs.max() <= 1.0
    assert m.positions[1].tolist() == [100.0, 0.0, 0.0]


def test_degenerate_strip_triangles_are_dropped():
    verts = [((0, 0, 0), (0, 0, 1))] * 4
    # max index must still reach vertices-1, which is how the array is recognised
    data = build(verts, [0, 0, 1, 3])   # the first strip triangle repeats an index
    m = phm.mesh(data)
    assert all(len(set(t.tolist())) == 3 for t in m.indices)


def test_a_file_that_is_not_a_phm_is_declined():
    assert not phm.is_phm(b"RIFF" + bytes(20))
    assert phm.mesh(b"RIFF" + bytes(200)) is None
    assert not plugin.detect("x.phm", b"RIFF" + bytes(20), 200)


def test_the_material_is_named_from_the_file():
    """PHM names its textures inline, so a model arrives with its material named after the TIM
    the disc ships rather than as an anonymous slot."""
    (scene,) = plugin.extract(_quad(), "global.wad/SPAWN.PHM", None)
    assert scene.materials[0].name == "SPAWNTPAGE02"
    assert scene.extras["textures_named"][0] == "SPAWNTPAGE02"


def test_the_primitive_matches_the_export_contract():
    (scene,) = plugin.extract(_quad(), "global.wad/SPAWN.PHM", None)
    p = scene.primitives[0]
    assert isinstance(p.material, int) and 0 <= p.material < len(scene.materials)
    assert p.indices.ndim == 1 and len(p.indices) % 3 == 0
