"""Tomb Raider: Legend DRM units - sections, relocations, and the GX-shaped models."""

import struct

import numpy as np

from gcrip.formats import tr_legend
from gcrip.plugins import tr_legend as plugin

SCALE = 0.5
# a quad as one 4-vertex triangle strip; positions are s16, the rest single-entry arrays
POSITIONS = ((0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 2))


def build(model_size_delta=0):
    """A minimal DRM unit: one geometry section and one model-header section."""
    # geometry: [strip packet][NOP pad][pos s16*3][nrm s8*3][col u8*4][uv u8*2]
    packet = bytes([0x99]) + struct.pack(">H", 4)
    for i in range(4):
        packet += bytes([0]) + struct.pack(">4H", i, 0, 0, 0)
    dl = packet + bytes(1)  # a NOP, as real lists pad with
    pos_off = len(dl)
    nrm_off = pos_off + 4 * 6
    col_off = nrm_off + 3
    uv_off = col_off + 4
    geo = bytearray(dl)
    for x, y, z in POSITIONS:
        geo += struct.pack(">3h", x, y, z)
    geo += struct.pack("3b", 0, 0, 127)
    geo += bytes((255, 128, 64, 255))
    geo += bytes((16, 32))

    # model header: magic, scale at +0x10, vertex count at +0x20, pointers at +0x64..
    model = bytearray(0x84 + model_size_delta)
    model[0:4] = tr_legend.MODEL_MAGIC
    struct.pack_into(">3f", model, 0x10, SCALE, SCALE, SCALE)
    struct.pack_into(">I", model, 0x20, 4)
    slots = (0x64, 0x68, 0x6C, 0x70)
    for slot, val in zip(slots, (pos_off, nrm_off, col_off, uv_off), strict=True):
        struct.pack_into(">I", model, slot, val)
    # 4 relocations, all into section 0 (the geometry): high u16 is (target+1)*8,
    # low u16 deliberately junk - the engine leaves build-path fragments there
    relocs = b"".join(
        struct.pack(">2I", (1 * 8) << 16 | 0x3A5C, slot) for slot in (0x64, 0x68, 0x6C, 0x70)
    )

    recs = [
        struct.pack(">5I", tr_legend.SENTINEL, len(geo), 0, 0, 7),
        struct.pack(">5I", tr_legend.SENTINEL, len(model), 0, 4 << 8, 8),
    ]
    unit_header = struct.pack(">2I", 0x10000000, 0x00800000)  # never parses as a pair
    out = struct.pack(">6I", 14, len(recs) + 1, len(unit_header), 0, 0x800, 0)
    out += b"".join(recs)
    out += struct.pack(">I", tr_legend.SENTINEL)
    out += unit_header
    out += bytes(geo)
    out += relocs + bytes(model)
    return out


def test_detection_fits_in_the_sniffed_head():
    data = build()
    assert tr_legend.is_drm(data[:64])
    assert plugin.detect("cafebabe", data[:64], len(data))
    assert not tr_legend.is_drm(b"\x00\x00\x00\x0d" + data[4:64])


def test_the_tiling_must_land_byte_exact():
    """Header + records + pairs + unit header + relocs + payloads == member length is
    the identity that proved the layout on 16/16 real units; a trailing byte breaks it."""
    data = build()
    secs = tr_legend.sections(data)
    assert secs is not None and len(secs) == 2
    assert tr_legend.sections(data + b"\x00") is None


def test_sections_carry_their_relocations():
    secs = tr_legend.sections(build())
    assert secs[0].relocs == []
    assert [(t, o) for t, o in secs[1].relocs] == [(0, 0x64), (0, 0x68), (0, 0x6C), (0, 0x70)]


def test_the_model_comes_out_scaled_and_triangulated():
    got = tr_legend.models(build())
    assert len(got) == 1
    m = got[0]
    # a 4-vertex strip is two triangles, none degenerate
    assert m.indices.shape == (2, 3)
    want = np.array(POSITIONS, np.float32) * SCALE
    assert np.allclose(m.positions, want)
    assert np.allclose(m.normals, [[0, 0, 1]] * 4)
    assert m.declared_vertices == 4


def test_the_plugin_yields_a_scene_per_model():
    data = build()
    scenes = plugin.extract(data, "cafebabe", None)
    assert len(scenes) == 1
    assert scenes[0].triangles == 2
    assert scenes[0].extras["format"] == "tr_legend"
