"""THQ g4rc textures - Avatar: The Last Airbender, Jimmy Neutron: Attack of the Twonkies."""

import struct
import zlib

from gcrip.formats import gx_texture as gx
from gcrip.formats import thq_g4rc
from gcrip.plugins import thq_g4rc as plugin


def packed(width, height):
    return ((width - 1) & 0xFF) | (((height - 1) & 0xFF) << thq_g4rc.HEIGHT_SHIFT)


def build(width=16, height=16, levels=2, pixels=None, dims=None):
    chain = 0
    w, h = width, height
    for _ in range(levels):
        chain += gx.encoded_size(thq_g4rc.FORMAT, max(w, 1), max(h, 1))
        w, h = max(w // 2, 1), max(h // 2, 1)
    head = bytearray(thq_g4rc.HEADER)
    head[0:4] = thq_g4rc.MAGIC
    struct.pack_into(">I", head, 4, 7)
    struct.pack_into(">I", head, 12, chain + thq_g4rc.HEADER - 16)
    struct.pack_into(
        ">I", head, thq_g4rc.PACKED_AT, packed(width, height) if dims is None else dims
    )
    struct.pack_into(">I", head, thq_g4rc.LEVELS_AT, levels)
    struct.pack_into(">I", head, thq_g4rc.PIXELS_AT, chain if pixels is None else pixels)
    return bytes(head) + bytes(chain)


def test_detection_is_the_magic():
    data = build()
    assert thq_g4rc.is_g4rc(data[:64])
    assert plugin.detect("tex.bin", data[:64], len(data))
    assert not plugin.detect("tex.bin", b"bats" + bytes(60), 64)


def test_the_dimensions_are_packed_with_a_gap_between_the_fields():
    """width - 1 in bits 0-7 and height - 1 in bits 10-17.  Read as two plain bytes a 16x16
    image comes out 16x60, which is why the packing is easy to miss."""
    tex = thq_g4rc.texture(build(16, 16))
    assert (tex.width, tex.height) == (16, 16)
    raw = struct.unpack_from(">I", build(16, 16), thq_g4rc.PACKED_AT)[0]
    assert (raw >> 8) & 0xFF == 60  # the naive second byte, and it is wrong
    assert ((raw >> thq_g4rc.HEIGHT_SHIFT) & 0xFF) + 1 == 16


def test_a_texture_round_trips():
    tex = thq_g4rc.texture(build(256, 128, levels=1))
    assert (tex.width, tex.height, tex.levels) == (256, 128, 1)
    assert tex.rgba.shape == (128, 256, 4)


def test_the_mip_chain_has_to_equal_the_declared_pixel_bytes():
    """That identity is what turns the packed-dimension reading from a fit into a check."""
    assert thq_g4rc.texture(build(16, 16, pixels=999)) is None
    assert thq_g4rc.texture(build(16, 16)) is not None


def test_objects_that_are_not_textures_are_declined():
    """Four fonts and a string table in boot.rad carry zero mip levels, and two more declare
    zero pixel bytes.  None of them is an image."""
    assert thq_g4rc.texture(build(levels=0)) is None
    assert thq_g4rc.texture(build(pixels=0)) is None


def test_an_rcb_is_inflated_as_a_container():
    inner = build()
    blob = zlib.compress(inner)
    assert thq_g4rc.is_rcb(blob[:2])
    assert plugin.is_container("tex_ui_load_aang_ll.rcb", blob[:64])
    assert not plugin.is_container("tex_ui_load_aang_ll.dat", blob[:64])
    ((name, out),) = plugin.expand(blob)
    assert out == inner and name == "g4rc.bin"


def test_a_corrupt_rcb_declines_rather_than_raising():
    assert thq_g4rc.inflate(b"\x78\x9c" + b"\xff" * 64) is None
    assert plugin.expand(b"\x78\x9c" + b"\xff" * 64) == []


def test_the_plugin_returns_a_textures_only_scene():
    (scene,) = plugin.extract(build(32, 32, levels=1), "boot.rad/tex_thing.bin", None)
    assert scene.extras["textures_only"] and scene.extras["size"] == "32x32"
    assert set(scene.textures) == {"tex_thing"}
