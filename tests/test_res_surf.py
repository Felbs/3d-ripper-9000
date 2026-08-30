"""surf textures inside res\n resource files (Samurai Jack, Digimon Rumble Arena 2)."""

import struct

import numpy as np

from gcrip.formats import gx_texture as gx
from gcrip.formats import res_surf


def build(w=64, h=32, fmt=3, levels=1, entries=16, short=0) -> bytes:
    head = bytearray(res_surf.HEADER)
    head[8] = fmt
    head[11] = levels
    struct.pack_into(">2H", head, 12, w, h)
    palette = b"".join(struct.pack(">H", 0x0841 * (i + 1) & 0xFFFF) for i in range(entries))
    gxf = res_surf.GX_FORMAT[fmt]
    body = b""
    ww, hh = w, h
    for _ in range(levels):
        body += bytes(gx.encoded_size(gxf, max(1, ww), max(1, hh)))
        ww, hh = max(1, ww // 2), max(1, hh // 2)
    return bytes(head) + palette + body[: len(body) - short]


def test_header_derives_the_palette_from_what_is_left_over():
    info = res_surf.header(build(entries=16))
    assert (info.width, info.height) == (64, 32)
    assert info.format == 9  # C8
    assert info.levels == 1
    assert info.palette_bytes == 32


def test_mip_levels_are_tile_padded():
    """A 1x1 level still costs a whole tile; without that the palette comes out a stupid size."""
    a = res_surf.header(build(levels=1, entries=16))
    b = res_surf.header(build(levels=4, entries=16))
    assert a.palette_bytes == b.palette_bytes == 32
    # four levels of a 64x32 C8 texture, each padded up to whole 8x4 tiles
    assert len(build(levels=4)) > len(build(levels=1))


def test_format_byte_picks_c4_or_c8():
    assert res_surf.header(build(fmt=2)).format == 8  # C4, 4 bpp
    assert res_surf.header(build(fmt=3)).format == 9  # C8, 8 bpp
    bad = bytearray(build(fmt=3))
    bad[8] = 7  # no such format
    assert res_surf.header(bytes(bad)) is None


def test_rejects_sections_that_do_not_add_up():
    # trimming more than the palette makes the leftover negative, which cannot be a palette
    assert res_surf.header(build(entries=16, short=64)) is None
    assert res_surf.header(b"") is None
    assert not res_surf.is_surf(bytes(64))  # format byte 0
    d = bytearray(build())
    d[11] = 0  # zero mip levels
    assert res_surf.header(bytes(d)) is None


def test_decode_uses_an_rgb565_palette():
    d = build(w=8, h=8, entries=4)
    rgba = res_surf.decode(d)
    assert rgba.shape == (8, 8, 4)
    assert rgba.dtype == np.uint8
    # index 0 maps to palette entry 0, which is RGB565 0x0841
    expected = gx.decode_palette(res_surf.RGB565, struct.pack(">H", 0x0841), 1)[0]
    assert tuple(rgba[0, 0]) == tuple(expected)
    assert res_surf.decode(bytes(8)) is None
