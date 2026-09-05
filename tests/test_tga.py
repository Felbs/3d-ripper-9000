"""Truevision TGA: the lenient decoder (RenderWare loose textures, Kashmir pictures)
and the strict ``claimable`` sniff behind the ``tga`` plugin.

The GCJE41 regression the plugin guards: 462 loose ``screens/<lang>/*_loading*.tga``
pictures on Splinter Cell Chaos Theory were claimed by nothing, so the ``gx`` fallback
scanned their palette-indexed pixel data and shipped 51 noise meshes (66-74% degenerate
edges) - the whole game scored garbage in the quality audit.  A ``.tga`` with a coherent
header must be claimed as a picture, keeping the scanner off it.  The decode side must
stay lenient: clipped palettes and zero-filled truncation are what shipped SlugFest /
Outlaw Golf / RedCard / City Racer textures.
"""

import struct

import numpy as np
import pytest

from gcrip.formats import tga
from gcrip.plugins import tga as plugin


def build(width=4, height=2, image_type=1, bits=8, top_down=False, palette=None):
    head = bytearray(tga.HEADER)
    table = b""
    if image_type in (1, 9):
        entries = palette or [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 255)]
        head[1] = 1
        struct.pack_into("<H", head, 5, len(entries))
        head[7] = 24
        table = b"".join(bytes((b, g, r)) for r, g, b in entries)
    head[2] = image_type
    struct.pack_into("<2H", head, 12, width, height)
    head[16] = bits
    head[17] = 0x20 if top_down else 0
    step = (bits + 7) // 8
    if image_type in (1, 9, 3, 11):
        pixels = bytes((x + y) % 4 for y in range(height) for x in range(width))
    else:
        pixels = b"".join(
            bytes((30, 20 * y, 10 * x, 0xFF)[:step])  # BGR(A) on disk
            for y in range(height)
            for x in range(width)
        )
    if image_type in (9, 10, 11):  # one raw packet holding every pixel (count <= 128)
        assert width * height <= 128
        pixels = bytes([width * height - 1]) + pixels
    return bytes(head) + table + pixels


def chaos_theory_screen():
    """The exact header shape of the 462 GCJE41 screens: type 1, 256 x 24-bit palette,
    8 bpp, 640x448, descriptor 0x08 - plus a low-entropy body the gx scanner used to
    chew on, and the TRUEVISION-XFILE footer the discs carry."""
    head = bytearray(tga.HEADER)
    head[1], head[2] = 1, 1
    struct.pack_into("<H", head, 5, 256)
    head[7] = 24
    struct.pack_into("<2H", head, 12, 640, 448)
    head[16], head[17] = 8, 0x08
    table = bytes(3 * 256)
    body = bytes((x * y) & 0x7F for y in range(448) for x in range(640))
    return bytes(head) + table + body + b"\0" * 8 + b"TRUEVISION-XFILE.\0"


# --- the strict claim sniff -----------------------------------------------------------


def test_claims_the_chaos_theory_header():
    data = chaos_theory_screen()
    assert tga.claimable(data[:64], len(data))
    assert tga.decode(data).shape == (448, 640, 4)


def test_gcje41_screens_route_to_tga_not_the_gx_fallback():
    """The bug itself: before the plugin existed, plugins_for handed these files to the
    gx display-list scanner, which exported noise geometry."""
    from gcrip.plugins import plugins_for

    data = chaos_theory_screen()
    names = [m.NAME for m in plugins_for("files/screens/esp/x_loading0.tga", data[:64], len(data))]
    assert names == ["tga"]


def test_claimable_refuses_headers_without_a_tga_shape():
    assert not tga.claimable(bytes(18))  # image_type 0
    assert not tga.claimable(b"\0" + b"RPMOC3S" + bytes(10))  # kashmir's GC repack
    bad = bytearray(build())
    bad[2] = 2  # true-colour claiming a colormap
    assert not tga.claimable(bytes(bad))
    bad = bytearray(build())
    bad[17] = 0xC0  # interleave bits are never set
    assert not tga.claimable(bytes(bad))
    big = bytearray(build())
    struct.pack_into("<2H", big, 12, 8500, 8500)
    assert not tga.claimable(bytes(big))


def test_claimable_refuses_an_uncompressed_file_shorter_than_its_pixels():
    data = build(width=8, height=8)
    assert tga.claimable(data[:18], len(data))
    assert not tga.claimable(data[:18], len(data) // 2)


# --- the lenient decoder (behaviour shipped for RenderWare / Kashmir - keep it) -------


def test_a_colormap_entry_is_bgr():
    got = tga.decode(build(width=4, height=1))
    assert tuple(got[0, 0]) == (0, 0, 255, 255)  # index 0 -> the blue entry
    assert tuple(got[0, 2]) == (255, 0, 0, 255)


def test_an_index_past_the_colormap_is_clipped_not_refused():
    data = bytearray(build(width=4, height=1, palette=[(0, 0, 255), (0, 255, 0)]))
    got = tga.decode(bytes(data))  # indices 2 and 3 exceed the two entries
    assert tuple(got[0, 3]) == tuple(got[0, 1])  # clipped to the last entry


def test_a_truncated_file_decodes_zero_filled():
    data = build(width=8, height=8, image_type=2, bits=24)
    got = tga.decode(data[: len(data) // 2])
    assert got.shape == (8, 8, 4)
    assert (got[0, :, :3] == 0).all()  # bottom-up: the lost rows are the top ones


def test_rows_run_bottom_up_unless_descriptor_bit5():
    up = tga.decode(build(width=1, height=2, image_type=2, bits=24))
    down = tga.decode(build(width=1, height=2, image_type=2, bits=24, top_down=True))
    assert up.shape == (2, 1, 4)
    assert np.array_equal(up, down[::-1])


def test_truecolor_pixels_are_bgr_ordered():
    got = tga.decode(build(width=2, height=1, image_type=2, bits=24, top_down=True))
    assert tuple(got[0, 1]) == (10, 0, 30, 255)  # r=10*x, g=20*y, b=30


def test_sixteen_bit_is_argb1555():
    head = bytearray(tga.HEADER)
    head[2], head[16], head[17] = 2, 16, 0x20
    struct.pack_into("<2H", head, 12, 2, 1)
    # pixel 0: a=1 r=31 g=0 b=0; pixel 1: a=0 g=31
    px = struct.pack("<2H", 0x8000 | (31 << 10), 31 << 5)
    got = tga.decode(bytes(head) + px)
    assert tuple(got[0, 0]) == (255, 0, 0, 255)
    assert tuple(got[0, 1])[:3] == (0, 255, 0)


def test_rle_matches_the_uncompressed_decode():
    for image_type in (1, 2, 3):
        bits = 24 if image_type == 2 else 8
        plain = tga.decode(build(width=4, height=2, image_type=image_type, bits=bits))
        rle = tga.decode(build(width=4, height=2, image_type=image_type + 8, bits=bits))
        assert np.array_equal(plain, rle)


def test_an_rle_run_packet_repeats_one_pixel():
    head = bytearray(tga.HEADER)
    head[2], head[16], head[17] = 11, 8, 0x20  # greyscale RLE
    struct.pack_into("<2H", head, 12, 4, 1)
    got = tga.decode(bytes(head) + bytes([0x83, 0x55]))  # run of four 0x55
    assert np.array_equal(got[0, :, 0], [0x55] * 4)


def test_not_a_tga_raises():
    with pytest.raises(tga.TgaError):
        tga.decode(bytes(18))


# --- the plugin ------------------------------------------------------------------------


def test_plugin_wants_both_the_extension_and_the_header():
    data = build()
    assert plugin.detect("files/screens/esp/a_loading0.tga", data[:64], len(data))
    assert not plugin.detect("files/screens/esp/a_loading0.bin", data[:64], len(data))
    assert not plugin.detect("files/pic.tga", b"\0" + b"RPMOC3S" + bytes(56), 4096)


def test_plugin_returns_one_textures_only_scene():
    data = build()
    (scene,) = plugin.extract(data, "files/screens/esp/01_LightHouse_B_loading0.tga", None)
    assert scene.extras == {"textures_only": True, "format": "tga"}
    assert set(scene.textures) == {"01_LightHouse_B_loading0"}
    assert scene.textures["01_LightHouse_B_loading0"].shape == (2, 4, 4)
