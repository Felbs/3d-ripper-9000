"""GCT textures (Darkened Skye)."""

import struct

import numpy as np

from gcrip.formats import gct
from gcrip.formats import gx_texture as gx
from gcrip.plugins import gct as plugin


def build(w=64, h=64, fmt=0x0E, levels=1) -> bytes:
    head = bytearray(gct.HEADER)
    struct.pack_into(">3H", head, 0, gct.MAGIC, w, h)
    head[6] = levels - 1
    struct.pack_into(">I", head, 8, 0x00CCCCCC)
    struct.pack_into(">I", head, 12, fmt)
    body = b""
    ww, hh = w, h
    for _ in range(levels):
        body += bytes(gx.encoded_size(fmt, max(1, ww), max(1, hh)))
        ww, hh = max(1, ww // 2), max(1, hh // 2)
    return bytes(head) + body


def test_header_fields():
    t = gct.header(build(w=128, h=64, fmt=0x0E, levels=4))
    assert (t.width, t.height, t.format, t.levels) == (128, 64, 0x0E, 4)
    assert gct.is_gct(build())


def test_byte_six_is_the_level_count_not_the_format():
    """Reading +6 as a format explains nothing; the format is the u32 at +12."""
    one = build(levels=1)
    four = build(levels=4)
    assert one[6] == 0 and four[6] == 3
    assert gct.header(one).format == gct.header(four).format == 0x0E
    # the chain plus the header must account for the file exactly - that is the check
    assert gct.HEADER + gct.chain(gct.header(one)) == len(one)
    assert gct.HEADER + gct.chain(gct.header(four)) == len(four)


def test_formats_the_size_cannot_separate():
    # I8 and C8 are both 8 bits per pixel, so only the header tells them apart
    assert gct.header(build(fmt=1)).format == 1
    assert gct.header(build(fmt=9)).format == 9
    assert len(build(fmt=1)) == len(build(fmt=9))


def test_decode_returns_the_top_level():
    d = build(w=32, h=16, fmt=0x0E, levels=3)
    rgba = gct.decode(d)
    assert rgba.shape == (16, 32, 4)
    assert rgba.dtype == np.uint8


def test_rejects_junk_and_truncation():
    assert gct.header(b"") is None
    assert gct.header(bytes(64)) is None  # no magic
    d = bytearray(build())
    struct.pack_into(">I", d, 12, 0x99)  # not a GX format
    assert gct.header(bytes(d)) is None
    assert gct.decode(build()[:40]) is None  # pixels truncated


def test_plugin_makes_a_textures_only_scene():
    d = build()
    assert plugin.detect("GotCathTop1.gct", d[:64], len(d))
    scenes = plugin.extract(d, "DATA/GotCathTop1.gct", None)
    assert list(scenes[0].textures) == ["GotCathTop1"]
    assert scenes[0].extras["textures_only"] is True
    assert plugin.extract(bytes(64), "x.gct", None) == []
