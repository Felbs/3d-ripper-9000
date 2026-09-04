"""Neversoft / THUG GameCube plugin: PRE archives, .tex.ngc / .img.ngc and the
model files on synthetic data."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import neversoft as nv
from gcrip.plugins import neversoft as plug


def build_pre(entries: list[tuple[str, bytes, bytes | None]]) -> bytes:
    """entries: (name, data, packed or None)."""
    body = b""
    for name, data, packed in entries:
        nm = name.encode() + b"\0"
        nm = nm.ljust((len(nm) + 3) & ~3, b"\0")
        blob = packed if packed is not None else data
        body += struct.pack(">IIHHI", len(data), len(packed) if packed else 0, len(nm), 0, 0)
        body += nm + blob.ljust((len(blob) + 3) & ~3, b"\0")
    return struct.pack(">III", 12 + len(body) - 4, nv.PRE_VERSION, len(entries)) + body


def test_lzss_and_pre():
    packed = bytes([0x0F]) + b"abcd" + bytes([0xEE, 0xF1])  # 4 literals then a 4-byte match
    assert nv.lzss_decompress(packed, 8) == b"abcdabcd"
    pre = build_pre(
        [("Levels\\DJ\\DJ.tex.ngc", b"raw-bytes", None), ("x\\y.scn.ngc", b"abcdabcd", packed)]
    )
    assert nv.is_pre(pre) and plug.is_container("DJscn.prg", pre[:32])
    got = plug.expand(pre)
    assert got == [("Levels/DJ/DJ.tex.ngc", b"raw-bytes"), ("x/y.scn.ngc", b"abcdabcd")]


def cmpr_block_red() -> bytes:
    # one 4x4 DXT1 sub-block, colour 0 = red, all indices 0; a CMPR 8x8 tile is four of them
    return (struct.pack(">HH", 0xF800, 0x0000) + b"\0" * 4) * 4


def build_tex(crc: int = 0x1234) -> bytes:
    tex = struct.pack(">II", 1, 1)
    tex += struct.pack(">6I", crc, 8, 8, 1, 0, 0) + struct.pack(">I", 32) + cmpr_block_red()
    return tex


def test_tex_parse_decode_and_extra_chain():
    tex = struct.pack(">II", 1, 2)
    tex += struct.pack(">6I", 0x1234, 8, 8, 1, 1, 0) + struct.pack(">I", 32) + cmpr_block_red()
    tex += struct.pack(">I", 32) + cmpr_block_red()  # extra chain without a header
    tex += struct.pack(">6I", 0x5678, 0, 0, 0, 0, 0)  # empty placeholder
    assert nv.is_tex(tex) and plug.detect("models/a/a.tex.ngc", tex[:64], len(tex))
    texs = nv.parse_tex(tex)
    assert [t.checksum for t in texs] == [0x1234, 0x5678]
    img = texs[0].decode()
    assert img.shape == (8, 8, 4) and tuple(img[0, 0]) == (255, 0, 0, 255)
    assert texs[1].decode() is None
    scenes = plug.extract(tex, "models/a/a.tex.ngc", None)
    assert len(scenes) == 1 and scenes[0].extras["textures_only"]
    assert list(scenes[0].textures) == ["00001234"]
    assert scenes[0].materials[0].texture == "00001234"


def test_pre_member_fetched_through_archive():
    pre = build_pre([("Levels\\DJ\\DJ.tex.ngc", build_tex(), None)])

    class Src:
        by_path = {}

        def get(self, path):
            assert path == "pre/DJscn.prg"
            return pre

    path = "pre/DJscn.prg/Levels/DJ/DJ.tex.ngc"
    assert plug.detect(path, pre[:64], len(build_tex()))
    scenes = plug.extract(pre[:64], path, Src())
    assert len(scenes) == 1 and list(scenes[0].textures) == ["00001234"]


def test_img_parse():
    hdr = struct.pack(">9I", 2, 0, 4, 4, 32, 0, 4, 4, 0)
    tile = b"\xff\x80" * 16 + b"\x40\x20" * 16  # AR halves then GB halves
    img = hdr + tile
    assert nv.is_img(img) and plug.detect("images/x.img.ngc", img[:64], len(img))
    t = nv.parse_img(img)
    dec = t.decode()
    assert dec.shape == (4, 4, 4) and tuple(dec[0, 0]) == (0x80, 0x40, 0x20, 0xFF)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

MAT_CRC = 0xAABBCCDD
TEX_CRC = 0x1234


def build_model(gap: bytes = b"", tables: int = 0) -> bytes:
    """One object, one strip of 3 vertices with position / normal / colour / uv
    indices; `gap` is the float block big levels put before the passes and
    `tables` the number of colour tables before the materials."""
    nmat = 1
    reg_block = bytes([0x61, 0x80, 0, 0, 0xD5, 0x61, 0, 0, 0x80, 0x11]).ljust(0xA0, b"\0")
    out = bytearray(0x20)  # header patched below
    out += struct.pack(">IIHH6H", len(reg_block), 0, 0, 0xFFFF, *([0xFFFF] * 6))
    out += b"\0" * (-len(out) % 32)
    out += reg_block
    for _ in range(tables):
        out += (struct.pack(">I", 2) + struct.pack(">II", 5, 0x7F7F7FFF) * 2).ljust(32, b"\0")
    mats = len(out)
    out += struct.pack(">IBBHfHHIIII", MAT_CRC, 1, 1, 0x8000, 0.0, 0, 0, 0, 0xFF, 0x11111111, 0)
    out += gap
    out += struct.pack(">IIII", TEX_CRC, 0x81110000, 0xFFFFFFFF, 0x808080FF)
    out += b"\0\0\x30\0\x30\0\0\0" + struct.pack(">II", 1 << 16, 0)
    for x, y, z in ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0)):
        out += struct.pack(">3f", x, y, z)
    out += bytes([0x80, 0x80, 0x80, 0xFF])
    for u, v in ((0, 0), (1024, 0), (0, 512)):
        out += struct.pack(">2h", u, v)
    for _ in range(3):
        out += struct.pack(">3h", 0, 0, 1 << 14)
    out += b"\0" * (-len(out) % 32)
    objects = len(out)
    out += struct.pack(">HHIHHHH", 1, 0, 0, 0, 0, 0, 0xFFFF) + b"\0" * 32
    out += struct.pack(">4f", 0.5, 0.5, 0.0, 1.5)
    dl = bytes([0x08, 0x50]) + struct.pack(">I", 0x7E00)
    dl += bytes([0x08, 0x60]) + struct.pack(">I", 3)
    dl += bytes([0x10, 0, 0, 0x10, 0x08]) + struct.pack(">I", 0x25)
    dl += bytes([0x9F, 0, 3])
    for i in range(3):
        dl += struct.pack(">4H", i, i, 0, i)
    dl = dl.ljust((len(dl) + 31) & ~31, b"\0")
    sphere = (0.5, 0.5, 0.0, 1.5)
    out += struct.pack(">IIII4f", len(dl), MAT_CRC, 0x80002003, 0, *sphere)
    out += struct.pack(">IHHHHIf", 0, 0x15, 3, 3, 0x100, len(dl), 0.0)
    out += b"\0" * 12 + dl
    struct.pack_into(">IIHHIHHIII", out, 0, 3, 3, 1, 3, objects - mats, 1, nmat, 0, tables, 1)
    return bytes(out)


def test_model_parse_and_scene():
    data = build_model()
    assert nv.is_model(data) and plug.detect("models/crown/Crown.mdl.ngc", data[:64], len(data))
    m = nv.parse_model(data)
    assert len(m.materials) == 1 and m.materials[0].textures == [TEX_CRC]
    assert len(m.objects) == 1 and len(m.objects[0].meshes) == 1 and m.triangle_count == 1
    mesh = m.objects[0].meshes[0]
    assert mesh.material == MAT_CRC and list(mesh.corners) == ["pos", "nrm", "col0", "tex0"]
    assert np.allclose(m.uvs[1], (1.0, 0.0)) and np.allclose(m.uvs[2], (0.0, 0.5))
    assert np.allclose(m.normals[0], (0.0, 0.0, 1.0))
    scene = plug.model_to_scene(m, "Crown", nv.parse_tex(build_tex(TEX_CRC)))
    assert scene.triangles == 1 and scene.vertices == 3
    assert scene.materials[0].texture == "00001234" and "00001234" in scene.textures
    p = scene.primitives[0]
    assert np.allclose(p.positions[2], (0.0, 2.0, 0.0)) and np.allclose(p.colors[0], (1, 1, 1, 1))


def test_model_layout_variants():
    """Big levels: colour tables before the materials, a float block before the passes."""
    data = build_model(gap=struct.pack(">8f", 70, 80, 1.3, 1, 5, 1, 0.4, 100) * 3, tables=2)
    m = nv.parse_model(data)
    assert m.triangle_count == 1 and m.materials[0].textures == [TEX_CRC]


def test_model_extracts_through_pre_with_sibling_tex():
    pre = build_pre(
        [
            ("Levels\\SP\\SP.scn.ngc", build_model(), None),
            ("Levels\\SP\\SP.tex.ngc", build_tex(TEX_CRC), None),
        ]
    )

    class Src:
        by_path = {}

        def get(self, path):
            assert path == "pre/SPscn.prg"
            return pre

    path = "pre/SPscn.prg/Levels/SP/SP.scn.ngc"
    assert plug.detect(path, pre[:64], len(build_model()))
    scenes = plug.extract(pre[:64], path, Src())
    assert len(scenes) == 1 and scenes[0].triangles == 1
    assert scenes[0].materials[0].texture == "00001234"
    assert not plug.detect("models/peds/a/a.skin.ngc", pre[:64], 4096)


def test_pre_version_2_has_twelve_byte_entries():
    """Tony Hawk's Pro Skater 4's archives: version 0xabcd0002, no checksum in the entry."""
    body = b""
    for name, data in ((r"Levels\kon\kon.tex.ngc", b"tex" * 10), ("a.scn.ngc", b"scn" * 5)):
        nm = name.encode() + b"\0"
        nm = nm.ljust((len(nm) + 3) & ~3, b"\0")
        body += struct.pack(">IIHH", len(data), 0, len(nm), 0) + nm
        body += data.ljust((len(data) + 3) & ~3, b"\0")
    data = struct.pack(">III", 12 + len(body), nv.PRE_VERSION_2, 2) + body
    assert nv.is_pre(data)
    out = nv.pre_entries(data)
    assert [n for n, _ in out] == ["Levels/kon/kon.tex.ngc", "a.scn.ngc"]
    assert out[0][1] == b"tex" * 10 and out[1][1] == b"scn" * 5


def test_gctx_pictures_of_pro_skater_3():
    from gcrip.formats import gx_texture
    from gcrip.plugins import neversoft as plugin

    w, h = 8, 8
    size = w * h
    head = nv.GCTX_MAGIC + struct.pack(">HHHHI", w, h, 8, 1, size)
    head = head.ljust(nv.GCTX_NAME_AT, b"\0") + b"deck.png\0"
    head = head.ljust(nv.GCTX_HEADER, b"\0")
    data = head + bytes([3] * size) + struct.pack(">256H", *([0x83E0] * 256))
    assert nv.is_gctx(data)
    rgba = nv.gctx(data)
    assert rgba.shape == (8, 8, 4) and rgba[0, 0].tolist() == [0, 255, 0, 255]
    assert plugin.detect("pre/x.pre/textures/deck.png", data[:64], len(data))
    scenes = plugin.extract(data, "pre/x.pre/textures/deck.png", None)
    assert scenes and scenes[0].extras["textures_only"] and "deck" in scenes[0].textures
    assert not plugin.detect("a/b.png", b"\x89PNG" + bytes(60), 64)
    assert gx_texture.encoded_size(9, 8, 8) == 64
