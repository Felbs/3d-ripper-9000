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
    assert not frd_gcr.is_gcr(data[:12], len(data) + 4)
    assert not plugin.detect("x.bin", bytes(64), 4096)
    # an EA TERF archive's header (a tag, then small offsets) must not read as an array block
    terf = b"TERF" + bytes(3) + b"@" + bytes([2, 2, 1, 6, 0, 0x40, 1, 0x79]) + bytes(48)
    assert not plugin.detect("PLADATA.DAT", terf, 5969280)
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


def build_level(sectors=1, textures=(3231, 3237)):
    """A level: the eight-word header, texture slots at 0x20, then one block a sector - a
    batch table, f32 positions, f32 uvs, RGBA colours, a strip of 6-byte vertices, its
    (pointer, size) pair and the 0xa0 record whose +0x9c names the word before it."""
    out = bytearray(0x20)
    for t in textures:
        out += struct.pack(">4I", t, 0, 0, 0)
    out += struct.pack(">I", frd_gcr.LEVEL_NONE) + bytes(12)
    for k in range(sectors):
        table = len(out)
        out += struct.pack(">5H", k % len(textures), 0, 0, 4, 0)
        out += struct.pack(">5H", 0, 0, 0, 0, 0xFFFF)
        out += bytes(-len(out) % 4)
        pos_at = len(out)
        for p in QUAD:
            out += struct.pack(">3f", p[0] + 10 * k, p[1], p[2])
        uv_at = len(out)
        for u in UV:
            out += struct.pack(">2f", *u)
        clr_at = len(out)
        for i in range(4):
            out += bytes([200, 100 + i, 50, 255])
        dl_at = len(out)
        out += bytes([0x99]) + struct.pack(">H", 4)
        for i in range(4):
            out += struct.pack(">3H", i, i, i)
        dl_size = len(out) - dl_at
        out += bytes(-len(out) % 32)
        pairs = len(out)
        out += struct.pack(">2I", dl_at, dl_size)
        out += bytes(4)  # the word +0x9c points at
        rec = bytearray(frd_gcr.RECORD)
        struct.pack_into(">I", rec, 0x14, table)
        struct.pack_into(">5I", rec, 0x24, 0, pos_at, uv_at, clr_at, 0)
        struct.pack_into(">f", rec, 0x8C, 1.0)
        struct.pack_into(">I", rec, 0x90, pairs)
        struct.pack_into(">I", rec, 0x9C, len(out) - 4)
        out += rec
    rooms = len(out)
    out += bytes(72)
    struct.pack_into(">8I", out, 0, 0x20, rooms, rooms, rooms, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    return bytes(out)


def test_levels_are_sector_records_found_by_their_back_pointer():
    data = build_level(sectors=3)
    assert frd_gcr.is_level(data[:0x20], len(data)) and not frd_gcr.is_gcr(data[:12], len(data))
    assert plugin.detect("bg/level11/level11.gcr", data[:64], len(data))
    m = frd_gcr.parse_level(data)
    assert m is not None and m.warnings == [] and m.records == 3 and m.textures == [3231, 3237]
    assert len(m.batches) == 3 and [b.slot for b in m.batches] == [0, 1, 0]
    b = m.batches[1]
    # 6-byte vertices: position, colour, uv - no normals in a level
    assert b.normals is None and len(b.indices) == 6
    assert np.allclose(b.positions[:, 0].min(), 10.0) and np.allclose(b.uvs, UV)
    assert b.colors is not None and b.colors[3].tolist() == [200, 103, 50, 255]
    src = _Src({"files/data/story/l_11_ST.pak/textures__3237.gct": _gct_i8()})
    (scene,) = plugin.extract(data, "files/data/story/l_11_ST.pak/bg__level11__level11.gcr", src)
    assert scene.extras["flavour"] == "level" and scene.triangles == 6
    assert [mat.texture for mat in scene.materials] == [None, "tex_3237"]
    assert not frd_gcr.is_level(build()[:0x20], len(build()))


def build_fp(s16=True, embedded=True, matrix_flag=False, kind=0, order_fp=True):
    """A Future Perfect / Second Sight prop: slot table at 12, an s16 (or f32) QUAD, s16 uvs
    (the pointer's bit 1 says so), normals by palette index, one strip, the 0xc0 record and
    the trailer at +4.  ``order_fp`` picks the batch-entry field order."""
    out = bytearray(12)
    slot_at = len(out)
    out += bytes(16) + struct.pack(">I", frd_gcr.END32) + bytes(12)
    pos_at = len(out)
    for p in QUAD:
        out += struct.pack(">3h", *(int(v * 1024) for v in p)) if s16 else struct.pack(">3f", *p)
    out += bytes(-len(out) % 4)
    uv_at = len(out)
    for u in UV:
        out += struct.pack(">2h", *(int(v * 1024) for v in u))
    out += bytes(-len(out) % 4)
    dl_at = len(out)
    out += bytes([0x9D]) + struct.pack(">H", 4)
    for i in range(4):
        if kind or matrix_flag:
            out += bytes([3])
        out += struct.pack(">3H", i, 7 + i, i)  # position, palette normal, uv
    dl_size = len(out) - dl_at
    out += bytes(-len(out) % 32)
    pairs = len(out)
    out += struct.pack(">2I", dl_at, dl_size)
    table = len(out)
    if order_fp:
        out += struct.pack(">HBBHH", 0, 4, 3, 0, 0) + struct.pack(">HBBHH", 0, 0, 0xFF, 0, 0)
    else:
        out += struct.pack(">3HBB", 0, 0, 0, 4, 3) + struct.pack(">3HBB", 0, 0, 0, 0, 0xFF)
    out += bytes(-len(out) % 4)
    tex_at = len(out)
    out += _gct_i8()
    out += bytes(-len(out) % 4)
    rec = bytearray(frd_gcr.RECORD_FP)
    struct.pack_into(">5I", rec, 0, 0, pos_at, uv_at | 2, 1, 0)  # hdr, pos, uv, nrm, clr
    rec[0x3C] = kind
    struct.pack_into(">I", rec, 0x54, table)
    struct.pack_into(">f", rec, 0xAC, 1.0)
    struct.pack_into(">I", rec, 0xB0, pairs)
    struct.pack_into(">I", rec, 0xBC, len(out) - 4)
    out += rec
    trailer = len(out)
    flags = (0x10 if s16 else 0) | 0x40 | (0x10000 if matrix_flag else 0)
    out += struct.pack(">4I", 1, 1, 1, flags) + bytes(48)
    if embedded:
        struct.pack_into(">4I", out, slot_at, tex_at, 0x1234, 0, 0x10000000)
    else:
        struct.pack_into(">4I", out, slot_at, 0x6BB088, 0x6BB088, 0, 0)
    struct.pack_into(">3I", out, 0, 12, trailer, tex_at)
    return bytes(out)


def test_future_perfect_props_quantise_and_index_the_normal_palette():
    palette = frd_gcr.normal_palette()
    assert palette is not None and palette.shape == (4096, 3)
    assert np.allclose(np.linalg.norm(palette, axis=1), 1.0, atol=1e-3)
    data = build_fp()
    assert frd_gcr.is_fp(data[:12], len(data)) and not frd_gcr.is_gcr(data[:12], len(data))
    assert frd_gcr.b_block(data) is None
    m = frd_gcr.parse_fp(data)
    assert m is not None and m.warnings == [] and m.records == 1 and len(m.batches) == 1
    (b,) = m.batches
    assert np.allclose(b.positions, QUAD) and np.allclose(b.uvs, UV)
    assert np.allclose(b.normals, palette[7:11])
    assert b.colors is None and b.bones is None and len(b.indices) == 6
    # f32 positions when the trailer flag is clear; the other batch-entry order; the
    # trailer's matrix flag adds the byte even on a rigid node
    (b,) = frd_gcr.parse_fp(build_fp(s16=False)).batches
    assert np.allclose(b.positions, QUAD)
    (b,) = frd_gcr.parse_fp(build_fp(order_fp=False)).batches
    assert len(b.indices) == 6
    (b,) = frd_gcr.parse_fp(build_fp(matrix_flag=True)).batches
    assert b.bones is not None and b.bones.tolist() == [3, 3, 3, 3]


def test_future_perfect_plugin_uses_embedded_or_hashed_textures():
    data = build_fp()
    (scene,) = plugin.extract(data, "files/pak/stream/lv5/prop4.pak/d7a0229a_0000", None)
    assert scene.extras["flavour"] == "future_perfect" and scene.triangles == 2
    assert scene.materials[0].texture == "slot_0" and scene.textures["slot_0"].shape == (8, 8, 4)
    data = build_fp(embedded=False)
    src = _Src({"files/pak/stream/lv5/tex1.pak/006bb088_0004": _gct_i8()})
    (scene,) = plugin.extract(data, "files/pak/stream/lv5/prop4.pak/d7a0229a_0000", src)
    assert scene.materials[0].texture == "tex_006bb088"
    (bare,) = plugin.extract(data, "d7a0229a_0000", None)
    assert bare.materials[0].texture is None and bare.materials[0].name == "tex_006bb088"


def build_arrays(fp=False):
    """The array-block flavour: TimeSplitters 2's f32 layout (block at +4, positions at 8)
    or Future Perfect's s16 one (block at +8, positions at 12); one group, one entry, one
    strip of QUAD whose second triangle is wound against the normals."""
    out = bytearray(8 if not fp else 12)
    pos_at = len(out)
    for p in QUAD:
        if fp:
            out += struct.pack(">3h", *(int(v * 1024) for v in p))
        else:
            out += struct.pack(">3f", *p) + bytes(4)
    uv_at = len(out)
    for u in UV:
        out += struct.pack(">2h", *(int(v * 1024) for v in u)) if fp else struct.pack(">2f", *u)
    nrm_at = len(out)
    for _ in QUAD:
        out += struct.pack(">3hH", 0, 0, 16384, 0) if fp else struct.pack(">3f", 0, 0, 1) + bytes(4)
    dl_at = len(out)
    out += bytes([0x9E]) + struct.pack(">H", 4)
    for i in range(4):
        out += bytes([0]) + (
            struct.pack(">4H", i, i, 0, i) if not fp else struct.pack(">3H", i, i, i)
        )
    dl_size = len(out) - dl_at
    out += bytes(-len(out) % 32)
    entries = len(out)
    out += struct.pack(">5I", 1, 0, 4, dl_at, dl_size)
    xblock = len(out)
    out += struct.pack(">If", 0, 1.0)
    groups = len(out)
    if fp:
        out += struct.pack(">6I", 0, entries, 1, xblock, 1, 0)
    else:
        out += struct.pack(">5I", entries, 1, xblock, 1, 0)
    tree = len(out)
    out += struct.pack(">4i", 0, -1, -1, -1)
    block = len(out)
    if fp:
        out += struct.pack(">12I", pos_at, uv_at, nrm_at, 7, groups, tree, 1, 1, 0, 0, 0, 0)
        out += struct.pack(">3f", 0.0, 0.0, 0.0)
    else:
        out += struct.pack(">12I", pos_at, uv_at, nrm_at, groups, tree, 1, 1, 0, 0, 0, 0, 0)
    slots = len(out)
    tex_at = slots + 32 + 16
    out += struct.pack(">4I", tex_at, 0, 0, 0x10000000) + struct.pack(
        ">4I", tex_at, 0, 0, 0x10000000
    )
    out += struct.pack(">I", frd_gcr.END32) + bytes(12)
    assert len(out) == tex_at
    out += _gct_i8()
    nodes = len(out)
    out += bytes(48)
    if fp:
        struct.pack_into(">3I", out, 0, slots, nodes, block)
    else:
        struct.pack_into(">2I", out, 0, slots, block)
    return bytes(out)


def test_array_block_characters_read_in_both_layouts():
    for fp in (False, True):
        data = build_arrays(fp)
        assert frd_gcr.is_b(data[:64], len(data))
        assert frd_gcr.b_block(data) == (struct.unpack_from(">I", data, 8 if fp else 4)[0], fp)
        assert not frd_gcr.is_gcr(data[:12], len(data)) and not frd_gcr.is_level(
            data[:0x20], len(data)
        )
        m = frd_gcr.parse_b(data)
        assert m is not None and m.warnings == [] and m.records == 1 and len(m.batches) == 1
        (b,) = m.batches
        assert np.allclose(b.positions, QUAD) and np.allclose(b.uvs, UV)
        assert np.allclose(b.normals, [[0, 0, 1]] * 4) and b.slot == 1
        # every triangle re-wound to face its normals
        t = b.indices.reshape(-1, 3)
        face = np.cross(
            b.positions[t[:, 1]] - b.positions[t[:, 0]], b.positions[t[:, 2]] - b.positions[t[:, 0]]
        )
        assert (face[:, 2] > 0).all()
        (scene,) = plugin.extract(data, "ob/chrs/chr01.gcr", None)
        assert scene.extras["flavour"] == "arrays" and scene.triangles == 2
        assert scene.materials[0].texture == "slot_1"
