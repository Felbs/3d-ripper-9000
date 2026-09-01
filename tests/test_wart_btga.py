"""Warthog `.btga` textures - the image members of a WART3.00 .hog archive."""

import struct

import pytest

from gcrip.formats import gx_texture as gx
from gcrip.formats import wart_btga
from gcrip.plugins import wart_btga as plugin


def build(width=64, height=64, code=0x01, levels=1, extra=0, kind=3):
    fmt = wart_btga.BY_CODE.get(code, 14)
    payload = sum(
        gx.encoded_size(fmt, max(1, width >> i), max(1, height >> i)) for i in range(levels)
    )
    head = bytearray(wart_btga.HEADER)
    struct.pack_into(">I", head, wart_btga.KIND_AT, kind << 24)
    head[wart_btga.CODE_AT] = code
    struct.pack_into(">I", head, wart_btga.WIDTH_AT, width)
    struct.pack_into(">I", head, wart_btga.HEIGHT_AT, height)
    struct.pack_into(">I", head, wart_btga.LEVELS_AT, levels)
    struct.pack_into(">I", head, wart_btga.PAYLOAD_AT, payload + extra)
    return bytes(head) + bytes(payload + extra)


def test_a_cmpr_texture_round_trips():
    tex = wart_btga.texture(build(64, 64, 0x01))
    assert (tex.width, tex.height, tex.fmt) == (64, 64, 14)
    assert tex.rgba.shape == (64, 64, 4)


def test_an_ia4_texture_round_trips():
    tex = wart_btga.texture(build(32, 32, 0x81))
    assert tex.fmt == 2 and tex.rgba.shape == (32, 32, 4)


def test_the_mip_chain_is_part_of_the_size_identity():
    """A texture declaring five levels has to carry all five; the payload of a single level
    with the same dimensions is a different number and must be rejected."""
    assert wart_btga.texture(build(64, 64, 0x01, levels=5)) is not None
    short = bytearray(build(64, 64, 0x01, levels=5))
    struct.pack_into(">I", short, wart_btga.LEVELS_AT, 1)
    assert wart_btga.texture(bytes(short)) is None


def test_a_member_that_is_a_little_long_or_short_is_declined():
    assert wart_btga.texture(build(extra=16)) is None
    assert wart_btga.texture(build()) is not None


def test_an_unattested_format_code_is_declined_rather_than_guessed():
    """A wrong GX format still decodes to a plausible-looking image, so an unknown code has to
    decline instead of picking the nearest bit depth."""
    assert not wart_btga.looks_like(build(code=0x02)[:64])
    assert wart_btga.texture(build(code=0x02)) is None


@pytest.mark.parametrize("kind", [1, 2, 10])
def test_the_other_resource_kinds_are_left_alone(kind):
    """.bskl, .banr and .bmsh share the header and are not textures."""
    assert not wart_btga.looks_like(build(kind=kind)[:64])


def test_the_plugin_returns_a_textures_only_scene():
    (scene,) = plugin.extract(build(128, 64, 0x01), "frontend.hog/art/cog.btga", None)
    assert scene.extras["textures_only"] and scene.extras["size"] == "128x64"
    assert scene.extras["gx_format"] == "CMPR"
    assert set(scene.textures) == {"cog"}


def test_the_plugin_declines_a_btga_that_is_not_one():
    assert plugin.extract(b"\0" * 256, "x.btga", None) == []
    assert not plugin.detect("x.bmsh", build()[:64], 4096)
