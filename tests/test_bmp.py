"""Windows BMP images shipped loose on a dozen discs."""

import struct

import numpy as np

from gcrip.formats import bmp
from gcrip.plugins import bmp as plugin


def build(width=2, height=2, bits=24, top_down=False, palette=None):
    stride = ((width * bits + 31) // 32) * 4
    table = b""
    if bits == 8:
        entries = palette or [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 255)]
        table = b"".join(bytes((b, g, r, 0)) for r, g, b in entries)
    pixels_at = bmp.HEADER + bmp.INFO + len(table)
    rows = []
    for y in range(height):
        if bits == 8:
            row = bytes((x + y) % 4 for x in range(width))
        else:
            row = b"".join(bytes((10 * x, 20 * y, 30)[:3][::-1]) for x in range(width))
        rows.append(row.ljust(stride, b"\0"))
    body = b"".join(rows)
    head = bytearray(bmp.HEADER + bmp.INFO)
    head[:2] = b"BM"
    struct.pack_into("<I", head, 2, pixels_at + len(body))
    struct.pack_into("<I", head, 10, pixels_at)
    struct.pack_into("<I", head, bmp.HEADER, bmp.INFO)
    struct.pack_into("<2i", head, 18, width, -height if top_down else height)
    struct.pack_into("<H", head, 26, 1)
    struct.pack_into("<H", head, 28, bits)
    struct.pack_into("<I", head, 30, 0)
    if bits == 8:
        struct.pack_into("<I", head, 46, len(table) // 4)
    return bytes(head) + table + body


def test_detects_only_uncompressed_supported_depths():
    assert bmp.is_bmp(build()[:64])
    assert bmp.is_bmp(build(bits=8)[:64])
    bad = bytearray(build())
    struct.pack_into("<I", bad, 30, 1)  # RLE8
    assert not bmp.is_bmp(bytes(bad)[:64])
    assert not bmp.is_bmp(b"BM" + bytes(62))


def test_rows_run_bottom_up_unless_the_height_is_negative():
    up = bmp.decode(build(width=1, height=2))
    down = bmp.decode(build(width=1, height=2, top_down=True))
    assert up.shape == (2, 1, 4)
    assert np.array_equal(up, down[::-1])


def test_four_bit_rows_are_two_pixels_a_byte_high_nibble_first():
    """Crash Nitro Kart's legal screens are 4bpp; without this they are the only BMPs on the
    disc and it stays at zero."""
    # built by hand as 4bpp: indices 0,1,2,3 pack into two bytes
    head = bytearray(bmp.HEADER + bmp.INFO)
    head[:2] = b"BM"
    table = b"".join(
        bytes((b, g, r, 0)) for r, g, b in [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 255)]
    )
    pixels_at = bmp.HEADER + bmp.INFO + len(table)
    struct.pack_into("<I", head, 10, pixels_at)
    struct.pack_into("<I", head, bmp.HEADER, bmp.INFO)
    struct.pack_into("<2i", head, 18, 4, 1)
    struct.pack_into("<H", head, 28, 4)
    struct.pack_into("<I", head, 46, 4)
    body = bytes([0x01, 0x23]).ljust(4, b"\0")
    got = bmp.decode(bytes(head) + table + body)
    assert tuple(got[0, 0]) == (0, 0, 255, 255)
    assert tuple(got[0, 3]) == (255, 255, 255, 255)


def test_a_palette_entry_is_bgra():
    got = bmp.decode(build(width=4, height=1, bits=8))
    assert tuple(got[0, 0]) == (0, 0, 255, 255)  # index 0 -> the blue entry
    assert tuple(got[0, 2]) == (255, 0, 0, 255)


def test_an_index_past_the_palette_is_refused():
    data = bytearray(build(width=4, height=1, bits=8))
    struct.pack_into("<I", data, 46, 2)  # claim two entries for indices up to three
    assert bmp.decode(bytes(data)) is None


def test_disc_padding_is_refused_by_size():
    """Two discs pad themselves with 8500x8500 bitmaps that are not art."""
    data = bytearray(build())
    struct.pack_into("<2i", data, 18, 8500, 8500)
    assert bmp.decode(bytes(data)) is None
    assert bmp.MAX_DIM == 4096


def test_a_truncated_file_is_refused():
    data = build(width=8, height=8)
    assert bmp.decode(data[: len(data) // 2]) is None


def test_plugin_returns_one_textures_only_scene():
    data = build()
    assert plugin.detect("assets/gc_icon.bmp", data[:64], len(data))
    (scene,) = plugin.extract(data, "files/assets/gc_icon.bmp", None)
    assert scene.extras["textures_only"]
    assert set(scene.textures) == {"gc_icon"}
