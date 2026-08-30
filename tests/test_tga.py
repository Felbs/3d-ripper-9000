"""Truevision TGA images (loose textures beside RenderWare models)."""

import struct

import numpy as np

from gcrip.formats import tga


def header(kind: int, w: int, h: int, bits: int, cmap=(0, 0, 0), idlen: int = 0, desc: int = 0x20):
    return struct.pack(
        "<BBBHHBHHHHBB",
        idlen,
        1 if cmap[1] else 0,
        kind,
        cmap[0],
        cmap[1],
        cmap[2],
        0,
        0,
        w,
        h,
        bits,
        desc,
    )


def test_true_colour_32():
    px = bytes([10, 20, 30, 255, 40, 50, 60, 128])  # BGRA
    data = header(2, 2, 1, 32) + px
    img = tga.decode(data)
    assert img.shape == (1, 2, 4)
    assert tuple(img[0, 0]) == (30, 20, 10, 255)
    assert tuple(img[0, 1]) == (60, 50, 40, 128)


def test_bottom_up_rows_are_flipped():
    px = bytes([0, 0, 255, 255]) + bytes([255, 0, 0, 255])  # row 0 red, row 1 blue (BGRA)
    data = header(2, 1, 2, 32, desc=0) + px
    img = tga.decode(data)
    assert tuple(img[0, 0]) == (0, 0, 255, 255)  # last stored row comes first


def test_palettised_rle():
    palette = bytes([0, 0, 255, 255]) + bytes([255, 255, 255, 255])  # entry 0 red, 1 white
    body = bytes([0x82, 0]) + bytes([0x01, 1, 0])  # 3x index 0, then literal 1, 0
    data = header(9, 5, 1, 8, cmap=(0, 2, 32)) + palette + body
    img = tga.decode(data)
    assert img.shape == (1, 5, 4)
    assert tuple(img[0, 0]) == (255, 0, 0, 255)
    assert tuple(img[0, 3]) == (255, 255, 255, 255)


def test_is_tga_and_truncation():
    data = header(2, 4, 4, 24) + bytes(10)
    assert tga.is_tga(data)
    img = tga.decode(data)  # short body is zero filled rather than raising
    assert img.shape == (4, 4, 4)
    assert not tga.is_tga(b"not a tga")
    assert np.asarray(img).dtype == np.uint8
