"""Neversoft / THUG GameCube plugin: PRE archives, .tex.ngc and .img.ngc on synthetic data."""

from __future__ import annotations

import struct

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
    tex = struct.pack(">II", 1, 1)
    tex += struct.pack(">6I", 0x1234, 8, 8, 1, 0, 0) + struct.pack(">I", 32) + cmpr_block_red()
    pre = build_pre([("Levels\\DJ\\DJ.tex.ngc", tex, None)])

    class Src:
        by_path = {}

        def get(self, path):
            assert path == "pre/DJscn.prg"
            return pre

    path = "pre/DJscn.prg/Levels/DJ/DJ.tex.ngc"
    assert plug.detect(path, pre[:64], len(tex))
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
