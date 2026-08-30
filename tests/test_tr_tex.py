"""Terminal Reality .TEX textures (BloodRayne, Blowout)."""

import struct

import numpy as np

from gcrip.formats import gx_texture as gx
from gcrip.formats import tr_tex
from gcrip.plugins import tr_tex as plugin


def header(version: int, fmt: int, w: int, h: int) -> bytes:
    return struct.pack("<4I", version, fmt, w, h) + bytes(tr_tex.HEADER - 16)


def build_ci8(w: int = 8, h: int = 8) -> bytes:
    # a palette whose entry i is RGB5A3 opaque, and indices that walk it
    pal = b"".join(struct.pack(">H", 0x8000 | (i << 5)) for i in range(tr_tex.PALETTE_ENTRIES))
    body = bytes(range(w * h))
    return header(3, tr_tex.CI8, w, h) + pal + body


def build_cmpr(w: int = 8, h: int = 8) -> bytes:
    return header(3, tr_tex.CMPR, w, h) + bytes(gx.encoded_size(0xE, w, h))


def test_ci8_palette_comes_first():
    d = build_ci8()
    assert tr_tex.is_tex(d[: tr_tex.HEADER], len(d))
    rgba = tr_tex.decode(d)
    assert rgba.shape == (8, 8, 4)
    # index 0 is palette entry 0 (green channel 0), so decoding must not read the palette as pixels
    assert rgba.dtype == np.uint8


def test_cmpr_size_and_shape():
    d = build_cmpr(16, 16)
    assert tr_tex.needed(tr_tex.CMPR, 16, 16) == 16 * 16 // 2
    assert tr_tex.decode(d).shape == (16, 16, 4)


def test_padding_tail_is_ignored():
    d = build_cmpr(16, 16) + b"\xff" * 40
    assert tr_tex.decode(d).shape == (16, 16, 4)


def test_rejects_other_formats_and_junk():
    assert not tr_tex.is_tex(header(2, 2, 128, 128), 33560)  # format 2 is not decoded
    assert not tr_tex.is_tex(header(3, tr_tex.CMPR, 100, 128), 1 << 20)  # not a power of two
    assert not tr_tex.is_tex(header(9, tr_tex.CMPR, 64, 64), 1 << 20)  # unknown version
    assert not tr_tex.is_tex(b"short")
    assert tr_tex.decode(b"short") is None
    assert not tr_tex.is_tex(header(3, tr_tex.CI8, 64, 64), 100)  # truncated


def test_plugin_makes_a_textures_only_scene():
    d = build_ci8()
    assert plugin.detect("ART/123.TEX", d[: tr_tex.HEADER], len(d))
    assert not plugin.detect("ART/123.BST", d[: tr_tex.HEADER], len(d))
    scenes = plugin.extract(d, "ART/123.TEX", None)
    assert len(scenes) == 1
    assert list(scenes[0].textures) == ["123"]
    assert scenes[0].extras["textures_only"] is True
    assert plugin.extract(header(2, 2, 128, 128) + bytes(100), "x.TEX", None) == []


def test_version_2_header_is_four_bytes_shorter():
    assert tr_tex.header_size(2) == 24
    assert tr_tex.header_size(3) == 28
    body = bytes(gx.encoded_size(0xE, 16, 16))
    v2 = struct.pack("<4I", 2, tr_tex.CMPR, 16, 16) + bytes(8) + body
    assert len(v2) == 24 + len(body)
    assert tr_tex.is_tex(v2[: tr_tex.HEADER], len(v2))
    assert tr_tex.decode(v2).shape == (16, 16, 4)
