"""Free Radical gct textures - TimeSplitters 2, Future Perfect, Second Sight."""

import struct

from gcrip.formats import frd_gct
from gcrip.formats import gx_texture as gx
from gcrip.plugins import frd_gct as plugin


def build(width=32, height=32, code=2, levels=0, doubled=True, short=False):
    fmt = frd_gct.FORMATS.get(code, frd_gct.RGBA8)  # unknown codes get the biggest body
    head = bytearray(frd_gct.HEADER)
    struct.pack_into(">4I", head, 0, width, height, width if doubled else width + 1, height)
    struct.pack_into(">2H", head, 16, levels, code)
    body = bytes(gx.encoded_size(fmt, width, height))
    return bytes(head) + (body[:-1] if short else body)


def test_the_doubled_size_is_the_header_check():
    assert frd_gct.header(build()) is not None
    assert frd_gct.header(build(doubled=False)) is None


def test_several_codes_share_one_format():
    """Free Radical's numbering is its own: five codes are CMPR, two are I8, two RGB5A3."""
    assert {frd_gct.FORMATS[c] for c in (2, 3, 4, 10, 13)} == {frd_gct.CMPR}
    assert {frd_gct.FORMATS[c] for c in (5, 7)} == {frd_gct.I8}
    assert {frd_gct.FORMATS[c] for c in (6, 8)} == {frd_gct.RGB5A3}
    assert frd_gct.FORMATS[0] == frd_gct.RGBA8


def test_the_mip_count_is_the_high_half_of_the_word():
    """Read as one u32 a three-level format 5 comes out as the format 196,613."""
    got = frd_gct.header(build(code=6, levels=3))
    assert got is not None and got.levels == 3
    packed = struct.unpack_from(">I", build(code=6, levels=3), 16)[0]
    assert packed == 0x00030006


def test_unidentified_codes_are_refused_rather_than_guessed():
    for code in (9, 11, 12):
        assert frd_gct.header(build(code=code)) is None


def test_a_short_file_is_refused():
    assert frd_gct.header(build(short=True)) is None


def test_plugin_returns_one_textures_only_scene():
    data = build(code=6)
    assert plugin.detect("textures__misc__pda__invmouse.gct", data[:64], len(data))
    assert not plugin.detect("model.gcr", data[:64], len(data))
    (scene,) = plugin.extract(data, "pak/textures__misc__invmouse.gct", None)
    assert scene.extras["textures_only"]
    assert set(scene.textures) == {"textures__misc__invmouse"}
