"""Free Radical gcr character models - TimeSplitters 2's ob/chrs/*.gcr."""

import struct

import numpy as np

from gcrip.formats import frd_gcr
from gcrip.plugins import frd_gcr as plugin

QUAD = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
UV = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]


def build(kinds=(0,), colours=False, textures=(775, 776)):
    """One node a kind, each drawing QUAD as one strip on texture slot ``kind % slots``."""
    out = bytearray(12)
    for t in textures:
        out += struct.pack(">4I", t, 0, 0, 0)
    out += struct.pack(">I", frd_gcr.END32) + bytes(12)
    records = []
    for node, kind in enumerate(kinds):
        rec = bytearray(frd_gcr.RECORD)
        rec[0] = kind
        rec[1] = node
        # batch table: one chunk of four vertices on a slot, then the end entry
        slot = kind % len(textures)
        table = len(out)
        out += struct.pack(">5H", slot, 0, 0, 4, 2) + struct.pack(">5H", 0, 0, 0, 0, 0xFFFF)
        out += bytes(-len(out) % 4)
        pos_at = len(out)
        for p in QUAD:
            out += struct.pack(">3f", *p)
        uv_at = len(out)
        for u in UV:
            out += struct.pack(">2f", *u)
        clr_at = 0
        if colours:
            clr_at = len(out)
            for i in range(4):
                out += bytes([255, 10 * i, 20, 255])
        nrm_at = len(out)
        for _ in range(4):
            out += struct.pack(">4b", 0, 0, 64, 0)
        dl_at = len(out)
        stride = 8 if kind == 0 else 9
        out += bytes([0x9B]) + struct.pack(">H", 4)
        for i in range(4):
            if stride == 9:
                out += bytes([3 + i % 2])
            out += struct.pack(">4H", i, i, i if colours else 0, i)
        dl_size = len(out) - dl_at
        out += bytes(-len(out) % 32)
        pairs = len(out)
        out += struct.pack(">2I", dl_at, dl_size)
        struct.pack_into(">I", rec, 0x14, table)
        struct.pack_into(">5I", rec, 0x24, 0, pos_at, uv_at, clr_at, nrm_at)
        struct.pack_into(">I", rec, 0x90, pairs)
        struct.pack_into(">f", rec, 0x8C, 1.0)
        records.append(bytes(rec))
    out += bytes(-len(out) % 4)
    for rec in records:
        out += rec
    trailer = len(out)
    out += struct.pack(">3I", len(kinds), 27, 1) + bytes(28) + struct.pack(">f", 0.97) + bytes(8)
    struct.pack_into(">3I", out, 0, 12, trailer, 0)
    return bytes(out)


def _gct_i8(width=8, height=8):
    """A format-5 (I8) gct: one level, every texel 0x80."""
    head = struct.pack(">4IHH", width, height, width, height, 1, 5) + bytes(12)
    return head + bytes([0x80]) * (width * height)


class _Src:
    def __init__(self, files):
        self.by_path = files

    def get(self, path):
        return self.by_path[path]


def test_detection_is_the_12_and_the_trailer_offset():
    data = build()
    assert frd_gcr.is_gcr(data[:12], len(data))
    assert plugin.detect("ob/chrs/chr01.gcr", data[:64], len(data))
    assert not plugin.detect("ob/chrs/chr01.gcr", data[:64], len(data) + 4)
    assert not plugin.detect("level.gcr", struct.pack(">3I", 327428, 327388, 1025884882), 387904)
    assert frd_gcr.parse(b"\0" * 64) is None


def test_rigid_and_skinned_nodes_read_with_their_strides():
    m = frd_gcr.parse(build(kinds=(0, 1, 2), textures=(775, 776, 777)))
    assert m is not None and m.warnings == []
    assert m.records == 3 and m.bones == 27 and m.textures == [775, 776, 777]
    assert [b.kind for b in m.batches] == [0, 1, 2] and [b.slot for b in m.batches] == [0, 1, 2]
    for b in m.batches:
        assert len(b.indices) == 6 and len(b.positions) == 4
        assert np.allclose(b.positions, QUAD) and np.allclose(b.uvs, UV)
        assert np.allclose(b.normals, [[0.0, 0.0, 1.0]] * 4)
    assert m.batches[0].bones is None
    assert m.batches[1].bones.tolist() == [3, 4, 3, 4]
    # the strip winds the way the normals point
    b = m.batches[0]
    t = b.indices.reshape(-1, 3)
    p = b.positions
    face = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
    assert (face[:, 2] > 0).all()


def test_colours_ride_the_third_index():
    (b,) = frd_gcr.parse(build(colours=True)).batches
    assert b.colors is not None and b.colors[2].tolist() == [255, 20, 20, 255]
    (b,) = frd_gcr.parse(build()).batches
    assert b.colors is None


def test_plugin_binds_the_paks_gct_by_id():
    data = build(kinds=(0, 1))
    src = _Src({"files/data/chr.pak/textures__0775.gct": _gct_i8()})
    (scene,) = plugin.extract(data, "files/data/chr.pak/ob__chrs__chr01.gcr", src)
    assert scene.triangles == 4 and len(scene.primitives) == 2 and len(scene.materials) == 2
    assert [m.name for m in scene.materials] == ["tex_0775", "tex_0776"]
    assert [m.texture for m in scene.materials] == ["tex_0775", None]
    assert scene.textures["tex_0775"].shape == (8, 8, 4)
    assert scene.extras["kinds"] == [0, 1] and scene.extras["textures"] == [775, 776]
    assert plugin.extract(data, "chr01.gcr", None)[0].textures == {}
