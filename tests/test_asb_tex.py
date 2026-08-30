"""Acclaim TBLOCKTEX / ASB_TEXTURE texture blocks - the All-Star Baseball discs."""

import struct

import numpy as np

from gcrip.formats import asb_tex
from gcrip.formats import gx_texture as gx
from gcrip.plugins import asb_tex as plugin


def image(w=8, h=8, fmt=9):
    """One image: 32-byte header, pixels, then the palette."""
    pixels = bytes(range(256))[: gx.encoded_size(fmt, w, h)]
    pixels = (pixels * 64)[: gx.encoded_size(fmt, w, h)]
    palette = (
        b"".join(struct.pack(">H", 0x8000 | (i * 7)) for i in range(256)) if fmt in (8, 9) else b""
    )
    if fmt == 8:
        palette = palette[:32]
    head = bytearray(asb_tex.IMAGE_HEADER)
    struct.pack_into("<2I", head, 8, len(pixels), len(palette))
    struct.pack_into("<4H", head, 16, w, h, w, h)
    return bytes(head) + pixels + palette


def block(images=(("jersey", 8, 8, 9), ("sky", 8, 8, 0xE))):
    body = b""
    offsets = []
    base = asb_tex.HEADER + len(images) * asb_tex.ENTRY
    for _name, w, h, fmt in images:
        offsets.append(base + len(body))
        body += image(w, h, fmt)
    head = bytearray(asb_tex.HEADER)
    head[:16] = b"TBLOCKTEX_30_BE\0"
    struct.pack_into(">I", head, 16, len(images))
    table = b""
    for (name, _w, _h, _f), off in zip(images, offsets, strict=True):
        table += name.encode().ljust(asb_tex.NAME, b"\0") + struct.pack(">I", off)
    return bytes(head) + table + body


def old_block(names=("ABREU_BOBBY", "ABBOTT_PAUL"), sizes=((8, 8), (16, 16))):
    body = b"".join(image(w, h, 9) for w, h in sizes)
    head = bytearray(asb_tex.OLD_NAMES_AT)
    head[:12] = b"ASB_TEXTURE\0"
    struct.pack_into(">I", head, 16, len(names))
    struct.pack_into(">2I", head, 24, len(body), asb_tex.IMAGE_HEADER + 64 + 512)
    table = b"".join(n.encode().ljust(asb_tex.NAME, b"\0") for n in names)
    return bytes(head) + table + body


def test_the_format_falls_out_of_the_palette_size_and_the_bits_per_pixel():
    assert asb_tex.FORMATS[(512, 8)] == 9  # C8
    assert asb_tex.FORMATS[(32, 4)] == 8  # C4
    assert asb_tex.FORMATS[(0, 4)] == 0xE  # CMPR
    assert asb_tex.FORMATS[(0, 32)] == 6  # RGBA8


def test_images_are_named_and_sized_from_the_table():
    got = asb_tex.images(block())
    assert [i.name for i in got] == ["jersey", "sky"]
    assert [i.format for i in got] == [9, 0xE]
    assert all(i.width == 8 and i.height == 8 for i in got)


def test_the_palette_is_after_the_pixels():
    """Reading it first still decodes - the shapes come through and only the colours are
    wrong - so the layout has to be pinned rather than eyeballed."""
    data = block(images=(("jersey", 8, 8, 9),))
    (img,) = asb_tex.images(data)
    at = img.offset + asb_tex.IMAGE_HEADER + img.pixels
    assert data[at : at + 2] == b"\x80\x00"  # the first palette entry, not a pixel
    assert asb_tex.decode(data, img) is not None


def test_a_size_that_does_not_match_the_format_is_refused():
    data = bytearray(block(images=(("jersey", 8, 8, 9),)))
    (img,) = asb_tex.images(bytes(data))
    struct.pack_into("<2H", data, img.offset + 16, 64, 64)  # claim 64x64 for 64 bytes of pixels
    assert asb_tex.images(bytes(data)) == []


def test_the_old_container_walks_image_by_image():
    """The size at +28 is the first image's, not a stride: mixed sizes need the walk."""
    got = asb_tex.images(old_block())
    assert [i.name for i in got] == ["ABREU_BOBBY", "ABBOTT_PAUL"]
    assert [(i.width, i.height) for i in got] == [(8, 8), (16, 16)]
    assert all(i.palette_format == asb_tex.RGB565 for i in got)


def test_the_two_containers_use_different_palette_formats():
    (new,) = asb_tex.images(block(images=(("jersey", 8, 8, 9),)))
    old = asb_tex.images(old_block())[0]
    assert new.palette_format == asb_tex.RGB5A3 and old.palette_format == asb_tex.RGB565


def test_plugin_returns_one_textures_only_scene():
    data = block()
    assert plugin.detect("Home.tex", data[:64], len(data))
    (scene,) = plugin.extract(data, "DATAGC/Teams/NL/Padres/Home.tex", None)
    assert scene.extras["textures_only"] and scene.extras["images"] == 2
    assert set(scene.textures) == {"jersey", "sky"}
    assert all(isinstance(v, np.ndarray) and v.shape[2] == 4 for v in scene.textures.values())
