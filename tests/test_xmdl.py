"""XMDL models (Home Run King data.afs)."""

import struct

import numpy as np

from gcrip.formats import xmdl
from gcrip.plugins import xmdl as plugin


# a unit quad in the XZ plane with +Y normals, extended with a spare row for bigger fixtures
def _corner(i: int):
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    x, z = ring[i % 4]
    return x + i // 4, z


def build(nverts: int = 4, tris=((0, 1, 2), (0, 2, 3)), pad: int = 0) -> bytes:
    """One XMDL model laid out the way the game does: GRPV points at VRTX and INDX."""
    verts = b""
    for i in range(nverts):
        x, z = _corner(i)
        verts += struct.pack(">8f", x, 0.0, z, 0.0, 1.0, 0.0, i / 8, 0.5)
    idx = bytes(b for t in tris for b in t)

    body = bytearray()
    body += b"MDEL" + bytes(76)
    grpv_at = len(body)
    body += b"GRPV" + bytes(36)
    vtx_at = len(body)
    body += b"VRTX" + verts
    idx_at = len(body)
    body += b"INDX" + idx + bytes(pad)
    # GRPV offsets are relative to the model start + 12, and the body starts at 16
    struct.pack_into(
        ">6I", body, grpv_at + 12,
        nverts, 0, vtx_at + xmdl.HEADER - xmdl.SECTION_BASE, 0,
        idx_at + xmdl.HEADER - xmdl.SECTION_BASE, len(idx),
    )
    struct.pack_into(">I", body, grpv_at + 4, 0x0E)
    head = bytearray(xmdl.HEADER)
    head[0:4] = xmdl.MAGIC
    head[4:8] = xmdl.PLATFORM
    struct.pack_into(">2H", head, 8, 4, 3)
    struct.pack_into(">I", head, 12, len(body))
    out = bytes(head) + bytes(body)
    return out + bytes((-len(out)) % xmdl.ALIGN)


def test_reads_one_model():
    ms = xmdl.models(build())
    assert len(ms) == 1
    m = ms[0]
    assert len(m.positions) == 4
    assert len(m.indices) == 6
    assert np.allclose(m.normals[0], [0.0, 1.0, 0.0])
    assert np.allclose(m.positions[2], [1.0, 0.0, 1.0])
    # every surviving triangle faces the way its stored normals say
    p = m.positions[m.indices].reshape(-1, 3, 3)
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    assert (face[:, 1] > 0).all()
    assert xmdl.is_xmdl(build()[:8])


def test_models_are_packed_back_to_back_on_a_32_byte_boundary():
    d = build() + build(nverts=8, tris=((0, 1, 2),))
    ms = xmdl.models(d)
    assert [len(m.positions) for m in ms] == [4, 8]
    assert ms[1].offset % xmdl.ALIGN == 0
    assert ms[1].offset == len(build())


def test_padding_after_the_index_list_is_ignored():
    ms = xmdl.models(build(pad=7))
    assert len(ms[0].indices) == 6


def test_degenerate_triangles_are_dropped():
    # a triangle that repeats a vertex has no area and must not reach the exporter
    ms = xmdl.models(build(tris=((0, 1, 2), (0, 1, 1))))
    assert len(ms[0].indices) == 3


def test_rejects_junk_and_out_of_range_indices():
    assert xmdl.models(b"nope") == []
    assert not xmdl.is_xmdl(b"XMDLxxxx")  # wrong platform tag
    assert xmdl.models(build(nverts=4, tris=((0, 1, 9),))) == []


def test_plugin_emits_one_scene_per_model():
    d = build() + build(nverts=8, tris=((0, 1, 2),))
    scenes = plugin.extract(d, "data.afs/xmdl_0000.bin", None)
    assert [s.name for s in scenes] == ["xmdl_0000_000", "xmdl_0000_001"]
    assert scenes[0].triangles == 2
    assert plugin.detect("x.bin", d[:8], len(d)) is True
    assert plugin.extract(b"nope", "x.bin", None) == []
