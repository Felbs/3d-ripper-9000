"""High Voltage's TPL variant (Billy & Mandy, Kids Next Door .jam archives)."""

import struct

import numpy as np

from gcrip.formats import gx_texture as gx
from gcrip.formats import tpl, tpl_hvs
from gcrip.plugins import tpl as plugin


def build(images=((64, 64, 0x0E), (64, 64, 0x0E)), spare: int = 0) -> bytes:
    head = bytearray(tpl_hvs.TABLE_AT + 4 + len(images) * tpl_hvs.STRIDE)
    head[:4] = tpl.MAGIC
    struct.pack_into(">3I", head, 4, len(images), spare, tpl_hvs.TABLE_AT + 4)
    body = b""
    for i, (h, w, fmt) in enumerate(images):
        offset = len(head) + len(body)
        struct.pack_into(">HHII", head, tpl_hvs.TABLE_AT + 4 + i * tpl_hvs.STRIDE, h, w, fmt, offset)
        body += bytes(gx.encoded_size(fmt, w, h))
    return bytes(head) + body


def test_image_headers_are_inline_not_pointers():
    d = build()
    imgs = tpl_hvs.images(d)
    assert [(i.width, i.height, i.format) for i in imgs] == [(64, 64, 0x0E), (64, 64, 0x0E)]
    # the second image's data begins exactly where the first's ends - what confirmed the stride
    assert imgs[0].offset + gx.encoded_size(0x0E, 64, 64) == imgs[1].offset
    assert tpl_hvs.is_hvs(d)


def test_the_spare_word_at_plus_eight_must_be_zero():
    """Stock TPL puts the table offset there; a non-zero value means this is not the variant."""
    assert not tpl_hvs.is_hvs(build(spare=0x20))


def test_rejects_bad_dimensions_formats_and_truncation():
    assert tpl_hvs.images(b"") == []
    assert tpl_hvs.images(bytes(64)) == []  # no magic
    assert tpl_hvs.images(build(images=((0, 64, 0x0E),))) == []  # zero height
    bad = bytearray(build(images=((64, 64, 0x0E),)))
    struct.pack_into(">I", bad, tpl_hvs.TABLE_AT + 4 + 4, 0x99)  # not a GX format
    assert tpl_hvs.images(bytes(bad)) == []
    assert tpl_hvs.images(build()[:-64]) == []  # pixels run past the end


def test_decode_returns_rgba():
    d = build(images=((8, 8, 0x0E),))
    rgba = tpl_hvs.decode(d, tpl_hvs.images(d)[0])
    assert rgba.shape == (8, 8, 4)
    assert rgba.dtype == np.uint8


def test_plugin_prefers_the_variant_then_falls_back():
    d = build()
    scenes = plugin.extract(d, "x/ZOMBIEG1.TPL", None)
    assert len(scenes) == 1
    assert scenes[0].extras["format"] == "tpl_hvs"
    assert sorted(scenes[0].textures) == ["ZOMBIEG1_000", "ZOMBIEG1_001"]
    assert plugin.detect("x/ZOMBIEG1.TPL", d[:64], len(d))
    # something carrying the magic but neither layout yields nothing rather than noise
    assert plugin.extract(tpl.MAGIC + b"\xff" * 64, "x/junk.tpl", None) == []
