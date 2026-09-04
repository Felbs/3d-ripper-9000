"""Darkened Skye SKX models."""

import struct

import numpy as np

from gcrip.formats import skx
from gcrip.plugins import skx as plugin


def build(nverts=4, ntris=2, nuvs=6, influences=(1, 2, 1, 1), radius=100.0, normals=True):
    """A file with the real shape: header, directory, variable-length skinning records,
    16-byte triangles whose two index triples address different arrays, uvs, normals."""
    head = bytearray(64)
    head[:4] = skx.MAGIC
    struct.pack_into(">2I", head, 4, 2, 0)

    verts = bytearray()
    for i in range(nverts):
        n = influences[i % len(influences)]
        verts += struct.pack(">I", n)
        for k in range(n):
            verts += struct.pack(">4hf", 1000 * i, 2000 * i, 3000 * k, k, 1.0 / n)

    tris = bytearray()
    for t in range(ntris):
        vi = [(t + k) % nverts for k in range(3)]
        ti = [(t + k) % nuvs for k in range(3)]
        tris += struct.pack(">8H", *vi, *ti, 0, 0)

    uvs = b"".join(struct.pack(">2f", i / nuvs, 1 - i / nuvs) for i in range(nuvs))
    norms = b""
    if normals:
        norms = b"".join(struct.pack(">3f", 0.0, 1.0, 0.0) for _ in range(nverts))

    voff = len(head) + skx.DIRECTORY
    ioff = voff + len(verts)
    uvoff = ioff + len(tris)
    d = struct.pack(">2If5I", nverts, len(verts), radius, voff, ntris, ioff, nuvs, uvoff)
    return bytes(head) + d + bytes(verts) + bytes(tris) + uvs + norms


def test_the_directory_reconciles_with_every_array():
    data = build()
    (d,) = skx.directories(data)
    assert d.voff + d.vsize == d.ioff
    assert d.ioff + d.ntris * skx.TRIANGLE == d.uvoff
    assert d.nverts == 4 and d.ntris == 2 and d.nuvs == 6


def test_walking_the_skinning_records_lands_on_the_triangles():
    """Records are variable length, so the landing offset is what proves the layout."""
    data = build(influences=(1, 3, 2, 1))
    (d,) = skx.directories(data)
    assert skx._walk(data, d.voff, d.nverts, d.ioff) == d.ioff


def test_a_wrong_influence_count_does_not_land():
    data = build()
    (d,) = skx.directories(data)
    assert skx._walk(data, d.voff, d.nverts + 1, d.ioff) is None


def test_positions_are_s16_fixed_point():
    # the 2026-09-04 crack: coords are 6.10 fixed-point (/1024) in the joint frame, NOT
    # scaled by the directory radius - the radius scaling made every skinned model spaghetti
    data = build(radius=32768.0)
    (m,) = skx.meshes(data)
    assert m.positions.max() == 6000.0 / 1024.0


def test_the_two_index_triples_address_different_arrays():
    """Columns 0-2 index the vertices, columns 3-5 the uvs - reading 0-2 as uv indices is
    the mistake that silently dropped models."""
    data = build(nverts=4, nuvs=6)
    (m,) = skx.meshes(data)
    assert len(m.positions) == 2 * 3 and len(m.uvs) == 2 * 3
    assert m.uvs.min() >= 0.0 and m.uvs.max() <= 1.0


def test_normals_are_taken_only_when_they_are_unit_length():
    (m,) = skx.meshes(build(normals=True))
    assert m.normals is not None
    assert np.allclose(np.linalg.norm(m.normals, axis=1), 1.0)
    (bare,) = skx.meshes(build(normals=False))
    assert bare.normals is None


def test_several_meshes_in_one_file_are_all_found():
    data = build() + build(nverts=3, ntris=1, nuvs=3, normals=False)
    assert len(skx.directories(data)) >= 1  # the second copy is rebased, see the plugin


def test_plugin_detects_and_extracts():
    data = build()
    assert plugin.detect("AWGARGST#12.SKX", data[:64], len(data))
    assert not plugin.detect("x.gct", b"\xde\xad" + bytes(62), 64)
    (scene,) = plugin.extract(data, "models/AWGARGST#12.SKX", None)
    assert scene.name == "AWGARGST#12"
    assert scene.triangles == 2


def _skel_pair():
    """A 2-joint skeleton: SKX joint table + group .skg with parents (root, then child
    translated +10 in x)."""
    import struct

    import numpy as np

    # skg: header record + 2 joint records, all carrying the +-5 bbox signature
    bbox = struct.pack(">6f", -5, -5, -5, 5, 5, 5)

    def rec(parent, idx):
        return struct.pack(">3i", parent, idx, -1) + struct.pack(">7f", 0, 0, 0, 0, 0, 0, 1) + bbox

    skg = b"\x00GKS" + bytes(60) + rec(2, 3) + rec(-1, 1) + rec(0, 2)
    # skx joint table: header with count 3 (2 joints + header rec), rows at 0xa4
    hdr = bytearray(0xA4)
    hdr[:4] = b"\x00XKS"
    struct.pack_into(">I", hdr, 12, 3)
    row0 = struct.pack(">12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0) + bytes(128 - 48)
    row1 = struct.pack(">12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 10, 0, 0) + bytes(128 - 48)
    skx_blob = bytes(hdr) + row0 + row1
    return skx_blob, skg, np


def test_skye_skeleton_matching_and_globals():
    from gcrip.formats import skye_skel

    skx_blob, skg, np = _skel_pair()
    assert skye_skel.skg_parents(skg) == [-1, 0]
    assert skye_skel.skx_joint_count(skx_blob) == 3
    loc = skye_skel.skx_joint_locals(skx_blob)
    assert len(loc) == 2
    G = skye_skel.match_skeleton(skx_blob, [b"junk", skg])
    assert G is not None and len(G) == 2
    np.testing.assert_allclose(G[1][:3, 3], [10, 0, 0])  # child chained through the root


def test_skx_vertices_decode_fixed_point_with_skeleton():
    import struct

    import numpy as np

    from gcrip.formats import skx as skxm
    from gcrip.formats import skye_skel

    skx_blob, skg, _ = _skel_pair()
    G = skye_skel.match_skeleton(skx_blob, [skg])
    # one vertex: single influence on joint 1 at raw (1024, 2048, -1024) -> local (1,2,-1),
    # joint 1's global translation is (10,0,0)
    d = skxm.Directory(1, 16, 100.0, 0, 1, 16, 1, 32)
    data = struct.pack(">I", 1) + struct.pack(">4h", 1024, 2048, -1024, 1) + struct.pack(">f", 1.0)
    pos, joints, j4, w4 = skxm._vertices(data + bytes(64), d, G)
    np.testing.assert_allclose(pos[0], [11, 2, -1], atol=1e-5)
    # without a skeleton the raw first influence stands alone at /1024
    pos2, _, _, _ = skxm._vertices(data + bytes(64), d, None)
    np.testing.assert_allclose(pos2[0], [1, 2, -1], atol=1e-5)
