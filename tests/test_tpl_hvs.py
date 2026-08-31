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
        at = tpl_hvs.TABLE_AT + 4 + i * tpl_hvs.STRIDE
        struct.pack_into(">HHII", head, at, h, w, fmt, offset)
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


def build_stock(w=8, h=8, fmt=0x0E, base=0) -> bytes:
    """A stock Nintendo TPL, optionally embedded at `base` inside a wrapper."""
    from gcrip.formats import gx_texture as gx

    header_len = 12
    table = header_len
    img = table + 8
    data_off = img + 0x20
    body = bytearray(data_off + gx.encoded_size(fmt, w, h))
    body[0:4] = tpl.MAGIC
    struct.pack_into(">2I", body, 4, 1, table)
    struct.pack_into(">2I", body, table, img, 0)
    struct.pack_into(">HHII", body, img, h, w, fmt, data_off)
    return bytes(base) + bytes(body) if isinstance(base, int) and base else bytes(body)


def test_an_embedded_tpl_is_found_and_offsets_resolve_against_it():
    """Mega Man X: Command Mission wraps a TPL in a 32-byte header, so it sits at 0x20."""
    inner = build_stock(w=16, h=16)
    wrapped = bytes(0x20) + inner
    assert plugin.detect("OG085.arc", wrapped[:64], len(wrapped))
    scenes = plugin.extract(wrapped, "OG085.arc", None)
    assert len(scenes) == 1
    rgba = next(iter(scenes[0].textures.values()))
    assert rgba.shape == (16, 16, 4)
    # the same bytes at offset 0 must decode identically
    flat = plugin.extract(inner, "OG085.arc", None)
    assert np.array_equal(next(iter(flat[0].textures.values())), rgba)


def test_a_tpl_past_the_sniff_window_is_not_claimed():
    wrapped = bytes(4096) + build_stock()
    assert not plugin.detect("x.arc", wrapped[:64], len(wrapped))
