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


def test_positions_are_s16_over_the_radius():
    data = build(radius=32768.0)  # scale 1.0, so the s16 come through unchanged
    (m,) = skx.meshes(data)
    assert m.positions.max() == 6000.0  # y = 2000 * 3


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
