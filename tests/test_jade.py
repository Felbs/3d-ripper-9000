"""Jade engine (BG&E / PoP SoT) plugin: BF table, LZO blocks, texture pairing,
GEO parsing in both dialects - all on synthetic data."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import jade, jade_bf, jade_lzo
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
