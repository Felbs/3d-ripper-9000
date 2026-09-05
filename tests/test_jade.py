"""Jade engine (BG&E / PoP SoT) plugin: BF table, LZO blocks, texture pairing,
GEO parsing in both dialects, the object graph (GAO -> material -> texture),
world placement and the Montpellier load-order replay - all on synthetic data."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import jade, jade_bf, jade_lzo, jade_obj
from gcrip.plugins import jade as plug

# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def build_bf(files: list[tuple[str, int, bytes]], dirs: list[tuple[str, int]]) -> bytes:
    """files: (name, key, payload) all in dir 0; dirs: (name, parent)."""
    version = 34
    size_of_fat = max(len(files), len(dirs), 1)
    fi = 0x54
    fat_pos = jade_bf.HEADER_SIZE
    pos_fat = fat_pos + jade_bf.FAT_HEADER_SIZE
    table_end = pos_fat + size_of_fat * 8 + size_of_fat * fi + size_of_fat * jade_bf.DIR_INFO_SIZE
    data_pos = (table_end + 0xFF) & ~0xFF
    refs = b""
    infos = b""
    payloads = b""
    cur = data_pos
    for name, key, payload in files:
        refs += struct.pack("<II", cur, key)
        infos += struct.pack("<Iiiii", len(payload), -1, -1, 0, 0)
        infos += name.encode().ljust(0x40, b"\0")
        infos += b"\0" * (fi - 20 - 0x40)
        blob = struct.pack("<I", len(payload)) + payload
        payloads += blob
        cur += len(blob)
    refs = refs.ljust(size_of_fat * 8, b"\0")
    infos = infos.ljust(size_of_fat * fi, b"\0")
    dinfo = b""
    for name, parent in dirs:
        dinfo += struct.pack("<iiiii", -1, -1, -1, -1, parent) + name.encode().ljust(0x40, b"\0")
    dinfo = dinfo.ljust(size_of_fat * jade_bf.DIR_INFO_SIZE, b"\0")
    hdr = jade_bf.MAGIC + struct.pack(
        "<9I", version, len(files), len(dirs), 0, 0, 0xFFFFFFFF, 0xFFFFFFFF, size_of_fat, 1
    )
    hdr += struct.pack("<I", 0)
    fat = struct.pack("<IIIiII", len(files), len(dirs), pos_fat, -1, 0, size_of_fat - 1)
    out = hdr + fat + refs + infos + dinfo
    out = out.ljust(data_pos, b"\0") + payloads
    return out


def tex_header(typ: int, fmt: int, w: int, h: int, body: bytes, key: int | None = None) -> bytes:
    hdr = b"\xff\xff\xff\xff" + struct.pack("<HBBHH", 0, typ, fmt, w, h)
    hdr += struct.pack("<I", 0xFFFFFFFF) + struct.pack("<I", 0)  # colour, font descriptor
    hdr += b"\x34\x12\xd0\xca\xff\x00\xff\x00\xde\xc0\xde\xc0"
    assert len(hdr) == 32
    if key is not None:
        hdr = struct.pack("<I", key) + hdr
    return hdr + body


def montpellier_geo(nverts: int = 3) -> bytes:
    b = struct.pack("<I", jade.GRO_GEO)
    b += struct.pack("<IIII", nverts, nverts, nverts, 1)  # verts, colours, uvs, elements
    b += struct.pack("<II", 0, 0)  # mrm pointer, code_01
    for i in range(nverts):
        b += struct.pack("<3f", float(i), 0.0, float(i % 2))
    b += b"\xff\x80\x40\x80" * nverts
    for i in range(nverts):
        b += struct.pack("<2f", i / 3.0, 0.5)
    b += struct.pack("<IIII", 1, 7, 0, 0)  # 1 triangle, material 7
    b += struct.pack("<6H", 0, 1, 2, 0, 1, 2) + struct.pack("<II", 0, 0)
    b += struct.pack("<II", 0, 0)  # strip flag, sprite elements
    return b


def montreal_geo() -> bytes:
    b = struct.pack("<II", jade.GRO_GEO, 7)  # type, object version
    b += struct.pack("<II", 0, 2)  # flags (no normals, 16-bit indices), flags2 (GC optimised)
    b += struct.pack("<IIIII", 3, 0, 0, 3, 1)  # verts, colours, has colours, uvs, elements
    b += struct.pack("<II", 0, 0)  # code_01, has normals
    for i in range(3):
        b += struct.pack("<3f", float(i), 0.0, float(i % 2))
    for i in range(3):
        b += struct.pack("<2f", i / 3.0, 0.5)
    b += struct.pack("<II", 1, 2)  # 1 triangle, material 2
    b += struct.pack("<6H", 0, 1, 2, 0, 1, 2) + struct.pack("<I", 0)
    b += struct.pack("<II", 0, 0)  # strip flag, sprites
    b += struct.pack("<II", 1, 2)  # GC header: 1 element, material id 2
    b += struct.pack("<II", jade.DEADBABE, 0)  # content marker, flags
    b += struct.pack("<HH", 1, 0)  # 1 strip
    b += struct.pack("<H", 3) + struct.pack("<3H", 0, 0, 0) + struct.pack("<3H", 1, 0, 1)
    b += struct.pack("<3H", 2, 0, 2)
    return b


def montreal_geo_lightmap(index8: bool = False) -> bytes:
    """A PoP GEO with HasLightMap set (GC flags bit 21): every display-list point
    carries two u16 lightmap indices after its vertex / colour / uv indices.  Two
    triangles as one 4-point strip; the triangle list is the ground truth."""
    flags = (1 << 21) | (1 << 20 if index8 else 0)
    b = struct.pack("<II", jade.GRO_GEO, 7)
    b += struct.pack("<II", flags, 2)
    b += struct.pack("<IIIII", 4, 0, 0, 4, 1)
    b += struct.pack("<II", 0, 0)
    for i in range(4):
        b += struct.pack("<3f", float(i), float(i % 2), 0.0)
    for i in range(4):
        b += struct.pack("<2f", i / 4.0, 0.5)
    b += struct.pack("<II", 2, 0)
    b += struct.pack("<6H", 0, 1, 2, 0, 1, 2) + struct.pack("<I", 0)
    b += struct.pack("<6H", 1, 3, 2, 1, 3, 2) + struct.pack("<I", 0)
    b += struct.pack("<II", 0, 0)
    b += struct.pack("<II", 1, 0)
    b += struct.pack("<II", jade.DEADBABE, flags)
    b += struct.pack("<HH", 1, 0)
    b += struct.pack("<H", 4)
    idx = "B" if index8 else "H"
    for v in (0, 1, 2, 3):
        # index, colour, uv, then the lightmap pair - per point, not per strip
        b += struct.pack(f"<3{idx}", v, 0, v) + struct.pack("<HH", 0x1111, 0x2222)
    return b


def montreal_entry(key: int, body: bytes) -> bytes:
    return struct.pack("<I", len(body)) + jade.MARK + struct.pack("<I", key) + body


# ---------------------------------------------------------------------------


def test_lzo_stream_and_blocks():
    # 4 literals "abcd", an 8-byte match at distance 4, end marker
    stream = bytes([21]) + b"abcd" + bytes([0xEC, 0x00, 0x11, 0x00, 0x00])
    assert jade_lzo.lzo1x_decompress(stream) == b"abcdabcdabcd"
    packed = struct.pack("<II", 12, len(stream)) + stream
    raw = struct.pack("<II", 3, 3) + b"xyz"
    assert jade_lzo.decompress_blocks(packed + raw + struct.pack("<II", 0, 0)) == b"abcdabcdabcdxyz"
    assert jade_lzo.is_jade_blocks(packed)
    assert not jade_lzo.is_jade_blocks(b"BIG\0" + b"\0" * 8)


def test_bf_table_and_expand():
    bf = build_bf(
        [("ff001234.bin", 0xFF001234, b"MAPDATA"), ("song.wam", 0x26000001, b"\x01\x02")],
        [("ROOT", -1), ("Bin", 0)],
    )
    entries = jade_bf.parse(bf)
    assert [e.path for e in entries] == ["ROOT/ff001234.bin", "ROOT/song.wam"]
    assert [e.size for e in entries] == [7, 2]
    assert dict(jade_bf.expand(bf))["ROOT/ff001234.bin"] == b"MAPDATA"
    assert jade_bf.key_type(0xFF001234) == "map"
    assert jade_bf.key_type(0xFF801234) == "textures"
    assert jade_bf.key_type(0x26000001) is None
    assert plug.is_container("sally.bf", bf[:16])
    assert plug.detect("files/sally.bf/ROOT/Bin/ff001234.bin", b"", 100)
    assert plug.detect("files/prince.bf/ROOT/Bin/Level_wow_ff0f3e56.bin", b"", 100)
    assert not plug.detect("files/sally.bf/ROOT/Bin/ff401234.bin", b"", 100)  # sounds
    assert not plug.detect("files/sally.bf/ROOT/song.wam", b"", 100)


def test_montpellier_textures_pair_raw_with_palette():
    pal = bytes(b for i in range(256) for b in (i, i, i, i))  # 0x400 bytes BGRA
    raw = bytes(range(16))  # 4x4 8bpp indices
    slot = struct.pack("<III", 0x62000010, 0x62000020, 0xFFFFFFFF)
    entries = [
        tex_header(jade.TEX_RAWPAL, 0, 0, 0, slot),
        tex_header(jade.TEX_RAW, 0x40, 4, 4, b""),  # info of the raw texture
        pal,
        tex_header(jade.TEX_RAW, 0x40, 4, 4, raw),  # content
    ]
    dec = b"".join(struct.pack("<I", len(e)) + e for e in entries)
    tex = jade.textures_montpellier(jade.walk_montpellier(dec))
    assert list(tex) == ["62000010"]
    img = tex["62000010"]
    assert img.shape == (4, 4, 4)
    # palette entry i is (B=i, G=i, R=i, A=i): pixel 5 -> rgb 5, alpha 10 (Jade alpha is 0..128)
    assert tuple(img[1, 1]) == (5, 5, 5, 10)


def test_montreal_textures_jtx_and_geo_with_display_list():
    blocks = struct.pack("<HHI", 0xF800, 0x001F, 0)  # one DXT1 block: colour 0 = pure red
    jtx = struct.pack("<IIIIif", 3, jade.JTX_S3TC, 4, 4, 0, 0.0) + blocks + struct.pack("<i", 0)
    dec = montreal_entry(0x1B00D5A2, tex_header(jade.TEX_JTX, 0x10, 4, 4, jtx, key=0x1B00D5A2))
    dec += struct.pack("<I", 0x1234)  # a bare size request must be skipped
    dec += montreal_entry(0x3F001AB9, montreal_geo())
    assert jade.is_montreal(dec)
    entries = jade.walk_montreal(dec)
    assert [e.key for e in entries] == [0x1B00D5A2, 0x3F001AB9]
    tex = jade.textures_montreal(entries)
    assert tuple(tex["1b00d5a2"][0, 0]) == (255, 0, 0, 255)
    g = jade.parse_geo(entries[1].data, montreal=True)
    assert len(g.vertices) == 3 and len(g.elements) == 1
    assert len(g.elements[0].strips) == 1 and g.elements[0].strips[0].shape == (3, 4)
    assert g.elements[0].material == 2
    scene = plug.geo_to_scene(g, "geo")
    assert scene.triangles == 1 and scene.vertices == 3
    assert scene.materials[0].name == "mat2"


@pytest.mark.parametrize("index8", [False, True])
def test_montreal_lightmap_strip_points_carry_their_lightmap_indices(index8):
    # PoP SoT level walls (GC flags 0x?08084 + bit 21): the old decoder skipped the
    # lightmap pairs as a 4*len block after the strip, shearing every point after
    # the first (out-of-range indices, "spaghetti" walls in the quality audit)
    g = jade.parse_geo(montreal_geo_lightmap(index8), montreal=True)
    strip = g.elements[0].strips[0]
    assert strip.shape == (4, 4)
    assert strip[:, 0].tolist() == [0, 1, 2, 3]
    assert strip[:, 3].tolist() == [0, 1, 2, 3]
    scene = plug.geo_to_scene(g, "wall")
    assert scene.triangles == 2 and scene.vertices == 4
    prim = scene.primitives[0]

    def key(pts, tri):
        return tuple(sorted(tuple(pts[i].tolist()) for i in tri))

    got = {key(prim.positions, tri) for tri in prim.indices.reshape(-1, 3)}
    truth = {key(plug._to_yup(g.vertices), tri) for tri in [(0, 1, 2), (1, 3, 2)]}
    assert got == truth


def test_montpellier_geo_signature_scan_and_scene():
    geo = montpellier_geo()
    dec = b"\x01\x00\x00\x00" * 3 + struct.pack("<I", len(geo)) + geo + b"\x00" * 5
    found = jade.find_geos_montpellier(dec)
    assert len(found) == 1
    off, g = found[0]
    assert off == 16 and len(g.vertices) == 3 and g.colors is not None
    assert g.elements[0].material == 7 and g.triangle_count == 1
    scene = plug.geo_to_scene(g, "geo")
    assert scene.triangles == 1
    p = scene.primitives[0]
    # Z-up -> Y-up: vertex 1 was (1, 0, 1)
    assert np.allclose(p.positions[1], (1.0, 1.0, 0.0))
    assert p.colors is not None and abs(p.colors[0, 3] - 1.0) < 1e-6
    # a wrong size must not parse
    dec2 = struct.pack("<I", len(geo) + 4) + geo + b"\x00" * 4
    assert jade.find_geos_montpellier(dec2) == []


def test_extract_locates_pack_inside_big_file():
    packed = struct.pack("<II", len(montreal_geo()) + 12, len(montreal_geo()) + 12)
    packed += montreal_entry(0x3F001AB9, montreal_geo())
    bf = build_bf([("Bridge_wow_ff0f3e56.bin", 0xFF0F3E56, packed)], [("ROOT", -1)])

    class Src:
        by_path = {}

        def get(self, path):
            return bf

    path = "files/prince.bf/ROOT/Bridge_wow_ff0f3e56.bin"
    scenes = plug.extract(bf[:64], path, Src())  # wrong bytes: must fall back to the .bf
    assert len(scenes) == 1 and scenes[0].triangles == 1 and scenes[0].name == "3f001ab9"
    scenes = plug.extract(packed, path, Src())
    assert len(scenes) == 1


# ---------------------------------------------------------------------------
# object graph: GAO -> material -> texture (gcrip.formats.jade_obj)
# ---------------------------------------------------------------------------


def jade_matrix(tx=0.0, ty=0.0, tz=0.0, scale=1.0) -> bytes:
    """Jade_Matrix: I J K rows with the scale in the 4th column, T, w, type flags."""
    m = [1.0, 0, 0, scale, 0, 1.0, 0, scale, 0, 0, 1.0, scale, tx, ty, tz, 1.0]
    return struct.pack("<16f", *m) + struct.pack("<I", 2 | 4 | 8)


def montpellier_gao(name: str, geo: int, mat: int, tx=0.0, father: int | None = None) -> bytes:
    flags = jade_obj.F_BASE | jade_obj.F_VISU | jade_obj.F_OBBOX
    if father is not None:
        flags |= jade_obj.F_HIERARCHY
    b = b".gao" + struct.pack("<II", 0, flags) + struct.pack("<I", 7)
    b += bytes([0, 0x10, 0, 0, 0, 0])  # secto, visi coeff, lod vis/dist, design, fix flags
    b += jade_matrix(tx) + b"\0" * 48  # AABB + OBB
    b += struct.pack("<III", geo, mat, 0xFFBFFFFF) + b"\x10\xff\xff\xff" + struct.pack("<I", 0)
    if father is not None:
        b += struct.pack("<I", father) + jade_matrix()
    nm = name.encode() + b"\0"
    return b + struct.pack("<I", len(nm)) + nm


def montreal_gao(name: str, geo: int, mat: int, tx=0.0) -> bytes:
    flags = jade_obj.F_BASE | jade_obj.F_VISU
    nm = name.encode() + b"\0"
    b = b".gao" + struct.pack("<III", 10, 8, flags) + struct.pack("<I", len(nm)) + nm
    b += struct.pack("<I", 0) + bytes([0, 0x10, 0, 0, 0, 0])
    b += jade_matrix(tx) + b"\0" * 24
    # visual: geo, mat, draw mask, additional flags, light set, display order, unknown, pad
    b += struct.pack("<III", geo, mat, 0xFFFFFFFF) + bytes([0, 0, 0x10, 0, 0, 0])
    b += struct.pack("<I", 0)  # vertex colours
    b += struct.pack("<II", 0, 0xFFFFFFFF)  # ambient unknown, ambient texture (null)
    b += struct.pack("<II", 0xFFFFFFFF, 0xFFFFFFFF)  # ambient of GAO, local fog
    return b


def mtt_level(texture: int, flags=0x7, color_op=0, uv_source=0, tid=0) -> bytes:
    fl = (flags & 0xFFF) | (color_op << 12) | (uv_source << 20)
    return struct.pack("<HHIII", tid, 0, fl, 0, 0x3F800000) + struct.pack("<I", texture)


def montpellier_mtt(levels: list[bytes]) -> bytes:
    b = struct.pack("<I", jade.GRO_MAT_MTT)
    b += struct.pack("<IIII", 0, 0x00FF8040, 0, 0)  # ambient, diffuse (RGBA bytes), specular, exp
    b += struct.pack("<f", 1.0)  # opacity
    b += struct.pack("<III", 7, 0x04DF1FEC, 1)  # flags, first level pointer, validate mask
    return b + b"".join(levels)


def montreal_mtt(texture: int) -> bytes:
    b = struct.pack("<II", jade.GRO_MAT_MTT, 6) + struct.pack("<IIII", 0, 0, 0xFFFFFFFF, 0xD1)
    level = struct.pack("<HHIII", 0, 0x1800, 0x00010207, 0, 0x3F800000)
    return b + level + struct.pack("<II", 0, texture)


def msm(keys: list[int], montreal: bool) -> bytes:
    b = struct.pack("<I", jade.GRO_MAT_MSM) + (struct.pack("<I", 0) if montreal else b"")
    return b + struct.pack("<I", len(keys)) + struct.pack(f"<{len(keys)}I", *keys)


def montpellier_wow(name: str, objects: int) -> bytes:
    b = b".wow" + struct.pack("<III", 3, 1, 0xFFFFFF00) + name.encode().ljust(60, b"\0")
    b += jade_matrix() + struct.pack("<f", 1.0) + struct.pack("<III", 0, 0, 0)
    b += struct.pack("<IIII", 0xFFFFFFFF, 0xFFFFFFFF, objects, 0xFFFFFFFF)
    return b + struct.pack("<I", 0xFFFFFFFF) + b"\0" * 8


def test_parse_gao_both_dialects():
    data = montpellier_gao("Box_01.gao", 0x11, 0x22, tx=5.0, father=0x33)
    g = jade_obj.parse_gao(data, montreal=False)
    assert g.complete and g.name == "Box_01.gao" and g.geo == 0x11 and g.mat == 0x22
    assert g.father == 0x33 and g.matrix[0, 3] == 5.0 and g.local is not None
    refs = [r for r in g.refs if not jade_obj.is_null(r[1])]
    assert refs == [("geo", 0x11), ("mat", 0x22), ("gao", 0x33)]
    m = jade_obj.parse_gao(montreal_gao("Pillar.gao", 0x44, 0x55, tx=-2.0), montreal=True)
    assert m.complete and m.name == "Pillar.gao" and m.version == 10
    assert m.geo == 0x44 and m.mat == 0x55 and m.matrix[0, 3] == -2.0


def test_parse_materials_and_base_level():
    planar = mtt_level(0xAA, flags=0x5, color_op=4, uv_source=6, tid=1)
    diffuse = mtt_level(0xBB, flags=0x414, color_op=6, uv_source=0)
    m = jade_obj.parse_material(montpellier_mtt([planar, diffuse]), montreal=False)
    assert m.kind == jade.GRO_MAT_MTT and m.texture_keys() == [0xAA, 0xBB]
    assert m.base_level().texture == 0xBB  # object UVs beat a planar projection
    assert m.diffuse == (0x40 / 255, 0x80 / 255, 1.0, 0.0)
    m2 = jade_obj.parse_material(montreal_mtt(0x2E004FE4), montreal=True)
    assert m2.texture_keys() == [0x2E004FE4] and m2.base_level().flags & jade_obj.MTT_TILING_U
    m3 = jade_obj.parse_material(msm([1, 2, 3], montreal=True), montreal=True)
    assert m3.kind == jade.GRO_MAT_MSM and m3.subs == [1, 2, 3]
    with pytest.raises(jade.JadeError):
        jade_obj.parse_material(montreal_mtt(0x2E004FE4) + b"\0", montreal=True)  # size must match
    assert jade_obj.classify(b"\x03\x00\x00\x00" + b"\0" * 20, montreal=False)[0] == "raw"


def test_montreal_pack_links_geometry_to_textures_and_places_it():
    blocks = struct.pack("<HHI", 0x07E0, 0x001F, 0)  # DXT1 block: pure green
    jtx = struct.pack("<IIIIif", 3, jade.JTX_S3TC, 4, 4, 0, 0.0) + blocks + struct.pack("<i", 0)
    dec = montreal_entry(0x3F001AB9, montreal_geo())  # material slot 2
    dec += montreal_entry(0x1B00D5A2, tex_header(jade.TEX_JTX, 0x10, 4, 4, jtx, key=0x1B00D5A2))
    dec += montreal_entry(0x2E0051F1, montreal_mtt(0x1B00D5A2))
    dec += montreal_entry(0x3F001D5B, msm([0x2E0051F0, 0x2E0051F0, 0x2E0051F1], montreal=True))
    dec += montreal_entry(0x22022288, montreal_gao("Set_A.gao", 0x3F001AB9, 0x3F001D5B, tx=1.0))
    dec += montreal_entry(0x22022289, montreal_gao("Set_B.gao", 0x3F001AB9, 0x3F001D5B, tx=3.0))
    dec += montreal_entry(0x0F003E52, struct.pack("<II", 0x22022288, 0x22022289))  # object group
    wow = b".wow" + struct.pack("<II", 3, 2) + b"Bridge".ljust(60, b"\0")
    wow += struct.pack("<I", 0xFFFFFFFF) + jade_matrix() + struct.pack("<f", 1.0)
    wow += struct.pack("<III", 0, 0, 0xFFFFFFFF)  # background, lod cut, grids 0
    wow += struct.pack("<III", 0xFFFFFFFF, 0x0F003E52, 0xFFFFFFFF) + b"\0" * 8
    dec += montreal_entry(0x0F003E56, wow)
    entries = jade.walk_montreal(dec)
    w = jade_obj.index_montreal(entries)
    assert set(w.gaos) == {0x22022288, 0x22022289} and w.wows[0].gaos == [0x22022288, 0x22022289]
    assert jade_obj.geo_materials(w) == {0x3F001AB9: 0x3F001D5B}
    sm = jade_obj.resolve_slot(w, 0x3F001D5B, 2)
    assert sm.texture == 0x1B00D5A2 and sm.clamp_u is False
    textures = jade.textures_montreal(entries)
    scene = plug.geo_to_scene(w.geos[0x3F001AB9], "geo", w, 0x3F001D5B, textures)
    assert scene.materials[0].texture == "1b00d5a2"
    assert tuple(scene.textures["1b00d5a2"][0, 0]) == (0, 255, 0, 255)
    level = plug.world_scene(w, w.wows[0], "bridge", textures)
    assert level.extras["placed_objects"] == 2 and level.triangles == 2
    xs = sorted(float(p.positions[:, 0].min()) for p in level.primitives)
    assert xs == [1.0, 3.0]  # each object offset by its matrix
    packed = struct.pack("<II", len(dec), len(dec)) + dec
    bf = build_bf([("Bridge_wow_ff0f3e56.bin", 0xFF0F3E56, packed)], [("ROOT", -1)])

    class Src:
        by_path = {}

        def get(self, path):
            return bf

    scenes = plug.extract(bf[:64], "files/prince.bf/ROOT/Bin/Bridge_wow_ff0f3e56.bin", Src())
    names = {s.name for s in scenes}
    assert {"3f001ab9_Set_A", "ff0f3e56_Bridge", "ff0f3e56_textures"} <= names
    set_a = next(s for s in scenes if s.name == "3f001ab9_Set_A")
    assert all(m.texture == "1b00d5a2" for m in set_a.materials)


def test_montpellier_pack_replays_the_loader_order():
    """WOL, WOW, object list, the GAOs, then each GAO's GEO / material in request
    order (a material already loaded takes no file), then MSM sub-materials."""
    files = [
        struct.pack("<I", 0x9E000057) + b".wow",  # world list
        montpellier_wow("_basic", 0x9E000056),
        struct.pack("<II", 0x9E000072, 0x9E000073),  # WOR_GameObjectGroup
        montpellier_gao("A.gao", 0x35009088, 0x350091E7),
        montpellier_gao("B.gao", 0x54000164, 0x350091E7),
        montpellier_geo(),  # A's GEO
        msm([0x62001BD9], montreal=False),  # the shared material
        montpellier_geo(4),  # B's GEO (material already loaded)
        montpellier_mtt([mtt_level(0x62001BD9)]),  # MSM sub-material, requested last
    ]
    dec = b"".join(struct.pack("<I", len(f)) + f for f in files)
    w = jade_obj.index_montpellier(dec)
    assert w.stats["matched"] == 8 and w.stats["unexpected"] == 0 and w.wows[0].name == "_basic"
    assert w.gaos[0x9E000072].name == "A.gao" and w.wows[0].gaos == [0x9E000072, 0x9E000073]
    assert len(w.geos[0x35009088].vertices) == 3 and len(w.geos[0x54000164].vertices) == 4
    assert w.mats[0x350091E7].subs == [0x62001BD9] and w.tex_order == [0x62001BD9]
    assert jade_obj.resolve_slot(w, 0x350091E7, 0).texture == 0x62001BD9
    # a request whose file is missing (loaded from the fix) is skipped within its group
    w2 = jade_obj.index_montpellier(dec, preloaded={0x54000164})
    assert w2.stats["matched"] == 7 and 0x54000164 not in w2.geos and len(w2.unkeyed_geos) == 1


def test_texture_key_alignment_and_keyed_montpellier_textures():
    keys = jade.align_texture_keys([0x10, 0x20, None, 0x30], [0x11, 0x21, 0x99, 0x77, 0x31])
    assert keys == [0x11, 0x21, 0x99, 0x31]  # one unwalked reference inserted before the last
    pal = bytes(b for i in range(256) for b in (i, i, i, i))
    raw = bytes(range(16))
    slot = struct.pack("<III", 0x62000010, 0x62000020, 0xFFFFFFFF)
    entries = [
        tex_header(jade.TEX_RAWPAL, 0, 0, 0, slot),
        tex_header(jade.TEX_RAW, 0x40, 4, 4, b""),
        pal,
        tex_header(jade.TEX_RAW, 0x40, 4, 4, raw),
    ]
    dec = b"".join(struct.pack("<I", len(e)) + e for e in entries)
    tex = jade.textures_montpellier(jade.walk_montpellier(dec), [0x62000011])
    assert list(tex) == ["62000011"] and tuple(tex["62000011"][1, 1]) == (5, 5, 5, 10)
    assert list(jade.textures_montpellier(jade.walk_montpellier(dec))) == ["62000010"]
