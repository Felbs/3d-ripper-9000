import struct

import numpy as np

from gcrip.export import png
from gcrip.formats import bti, gx_texture


def test_rgb565_tile_layout():
    # 8x4 image = 2 tiles of 4x4. Pixel (x=5,y=1) lives in tile 1, row 1, col 1.
    w, h = 8, 4
    data = bytearray(gx_texture.encoded_size(4, w, h))
    red = 0xF800
    tile, row, col = 1, 1, 1
    off = (tile * 16 + row * 4 + col) * 2
    data[off : off + 2] = struct.pack(">H", red)
    img = gx_texture.decode(4, w, h, bytes(data))
    assert img.shape == (4, 8, 4)
    assert tuple(img[1, 5]) == (255, 0, 0, 255)
    assert tuple(img[0, 0]) == (0, 0, 0, 255)


def test_i4_and_ia8_and_rgb5a3():
    # I4: 8x8 tile, first byte holds pixels (0,0) and (1,0)
    img = gx_texture.decode(0, 8, 8, b"\xf0" + b"\x00" * 31)
    assert tuple(img[0, 0]) == (255, 255, 255, 255) and tuple(img[0, 1]) == (0, 0, 0, 255)
    # IA8: alpha high byte, intensity low
    img = gx_texture.decode(3, 4, 4, struct.pack(">H", 0x80FF) + b"\x00" * 30)
    assert tuple(img[0, 0]) == (255, 255, 255, 128)
    # RGB5A3: top bit set -> RGB555 opaque; clear -> ARGB3444
    img = gx_texture.decode(5, 4, 4, struct.pack(">HH", 0x801F, 0x0F00) + b"\x00" * 28)
    assert tuple(img[0, 0]) == (0, 0, 255, 255)
    assert img[0, 1, 3] == 0 and img[0, 1, 0] == 255


def test_rgba8_split_planes():
    # one 4x4 tile: 32 bytes of A,R pairs then 32 bytes of G,B pairs
    ar = bytes([0x80, 0x10] * 16)
    gb = bytes([0x20, 0x30] * 16)
    img = gx_texture.decode(6, 4, 4, ar + gb)
    assert tuple(img[2, 3]) == (0x10, 0x20, 0x30, 0x80)


def test_cmpr_gc_bit_order():
    # One 8x8 tile = 4 DXT1 sub-blocks. Sub-block 0: c0=red > c1=blue, all indices 01 (=c1)
    # except the very first pixel (top-left) = 00 (=c0). GC packs pixel 0 in the TOP 2 bits.
    c0, c1 = 0xF800, 0x001F
    sub0 = struct.pack(">HH", c0, c1) + bytes([0b00010101, 0x55, 0x55, 0x55])
    other = struct.pack(">HH", 0, 0) + b"\x00" * 4
    tile = sub0 + other * 3
    img = gx_texture.decode(14, 8, 8, tile)
    assert tuple(img[0, 0]) == (255, 0, 0, 255)  # index 0 -> c0 red
    assert tuple(img[0, 1]) == (0, 0, 255, 255)  # index 1 -> c1 blue
    assert tuple(img[3, 3]) == (0, 0, 255, 255)
    # sub-block 1 covers x=4..7 of rows 0..3 -> black
    assert tuple(img[0, 4]) == (0, 0, 0, 255)


def test_c8_palette():
    pal = struct.pack(">HH", 0xF800, 0x07E0)  # RGB565 red, green
    data = bytes([1]) + b"\x00" * 31  # 8x4 tile, first pixel index 1
    palette = gx_texture.decode_palette(1, pal, 2)
    img = gx_texture.decode(9, 8, 4, data, palette)
    assert tuple(img[0, 0]) == (0, 255, 0, 255)
    assert tuple(img[0, 1]) == (255, 0, 0, 255)


def test_bti_parse_and_decode():
    hdr = struct.pack(">BBHHBBBBHI", 4, 0, 4, 4, 1, 1, 0, 0, 0, 0)  # RGB565 4x4
    hdr += struct.pack(">IBBBBBBHI", 0, 0, 0, 0, 0, 1, 0, 0, 0x20)  # data offset 0x20
    body = struct.pack(">H", 0x07E0) + b"\x00" * 30
    t = bti.parse(hdr + body, 0, "t")
    assert (t.fmt_name, t.width, t.height, t.wrap_s) == ("RGB565", 4, 4, 1)
    img = t.decode()
    assert tuple(img[0, 0]) == (0, 255, 0, 255)


def test_png_roundtrip_signature(tmp_path):
    img = np.zeros((2, 3, 4), np.uint8)
    img[..., 3] = 255
    data = png.encode_rgba(img)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in data and b"IEND" in data
