"""PNG images - gcrip recognised the magic for years but never decoded one."""

import io
import struct

import numpy as np
from PIL import Image

from gcrip.formats import png
from gcrip.plugins import png as plugin


def build(width=4, height=3, mode="RGBA"):
    image = Image.new(mode, (width, height))
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), (x * 60, y * 80, 30, 255)[: len(mode)])
    with io.BytesIO() as fh:
        image.save(fh, format="PNG")
        return fh.getvalue()


def test_detects_on_the_signature_and_the_size_in_the_header():
    data = build()
    assert png.is_png(data[:64])
    assert png.size(data[:64]) == (4, 3)
    assert not png.is_png(b"\x89PNG" + bytes(60))


def test_a_dimension_past_the_guard_is_refused():
    data = bytearray(build())
    struct.pack_into(">2I", data, png.IHDR_AT, png.MAX_DIM + 1, 4)
    assert not png.is_png(bytes(data)[:64])
    assert png.decode(bytes(data)) is None


def test_decodes_to_rgba_whatever_the_colour_type():
    for mode in ("RGBA", "RGB", "L"):
        got = png.decode(build(mode=mode))
        assert got is not None and got.shape == (3, 4, 4)
        assert got.dtype == np.uint8


def test_a_truncated_file_comes_back_none_rather_than_raising():
    data = build()
    assert png.decode(data[: len(data) // 2]) is None


def test_the_end_marker_is_what_makes_carving_safe():
    data = build()
    assert data.endswith(png.END)


def test_plugin_returns_one_textures_only_scene():
    data = build()
    assert plugin.detect("image_00001.png", data[:64], len(data))
    (scene,) = plugin.extract(data, "data.hff/image_00001.png", None)
    assert scene.extras["textures_only"] and set(scene.textures) == {"image_00001"}
