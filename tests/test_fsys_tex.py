"""Pokemon Colosseum / XD textures - the image members of an FSYS archive."""

import struct

from gcrip.formats import fsys_tex
from gcrip.formats import gx_texture as gx
from gcrip.plugins import fsys_tex as plugin


def build(width=42, height=84, depth=32, extra=0, fmt=None):
    fmt = fsys_tex.BY_DEPTH.get(depth, 6) if fmt is None else fmt
    head = bytearray(fsys_tex.HEADER)
    struct.pack_into(">2H", head, 0, width, height)
    head[fsys_tex.BPP_AT] = depth
    head[fsys_tex.BPP_AT + 1] = 1
    return bytes(head) + bytes(gx.encoded_size(fmt, width, height) + extra)


def test_the_depth_is_a_single_byte_not_a_u16():
    """`20 01` at +4 is two fields.  Read as a u16 it is 8193, matches no depth, and every
    image is silently skipped - which is exactly what happened first time."""
    data = build()
    assert data[fsys_tex.BPP_AT] == 32
    assert struct.unpack_from(">H", data, fsys_tex.BPP_AT)[0] == 8193
    assert fsys_tex.looks_like(data[:64])


def test_a_thirty_two_bit_image_round_trips():
    tex = fsys_tex.texture(build(42, 84, 32))
    assert (tex.width, tex.height, tex.depth) == (42, 84, 32)
    assert tex.rgba.shape == (84, 42, 4)


def test_a_sixteen_bit_image_round_trips():
    tex = fsys_tex.texture(build(64, 64, 16))
    assert tex.depth == 16 and tex.rgba.shape == (64, 64, 4)


def test_the_size_identity_is_the_check():
    """128 + encoded_size(format, w, h) has to equal the member exactly; a member that is a
    little longer or shorter is something else with plausible numbers at the front."""
    assert fsys_tex.texture(build(extra=16)) is None
    assert fsys_tex.texture(build()) is not None


def test_an_unattested_depth_is_declined():
    """4 and 8 bits would need a palette and none has been located, so they are not guessed."""
    assert not fsys_tex.looks_like(build(depth=8)[:64])
    assert fsys_tex.texture(build(depth=8)) is None


def test_implausible_dimensions_are_declined():
    """Most members of an archive are not images at all - 1,456 of them in one sample."""
    data = bytearray(build())
    struct.pack_into(">2H", data, 0, 0, 0)
    assert not fsys_tex.looks_like(bytes(data)[:64])
    struct.pack_into(">2H", data, 0, 4096, 4096)
    assert not fsys_tex.looks_like(bytes(data)[:64])


def test_the_plugin_returns_a_textures_only_scene():
    (scene,) = plugin.extract(build(42, 84), "poke_face.fsys/face344.bin", None)
    assert scene.extras["textures_only"] and scene.extras["size"] == "42x84"
    assert set(scene.textures) == {"face344"}
