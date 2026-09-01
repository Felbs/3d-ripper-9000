"""Visual Concepts RTXT texture records - the uncompressed .IFF members of game.dat."""

import struct

import numpy as np

from gcrip.formats import vc_iff
from gcrip.plugins import vc_iff as plugin


def palette(entries=None):
    """256 RGB565 entries, big-endian."""
    vals = entries if entries is not None else [i << 11 for i in range(256)]
    return b"".join(struct.pack(">H", v & 0xFFFF) for v in vals)


def record(name="TEST", width=8, height=4, pixels=None, pal=None, declared=None):
    body = bytearray(vc_iff.PIXELS_AT)
    body[vc_iff.TAG_AT : vc_iff.TAG_AT + 4] = vc_iff.MAGIC
    raw = name.encode()
    body[vc_iff.NAME_AT : vc_iff.NAME_AT + len(raw)] = raw
    at = vc_iff.NAME_AT + (len(name) + 4) // 4 * 4 + vc_iff.DIMS_GAP
    struct.pack_into(">2I", body, at, width, height)
    px = pixels if pixels is not None else bytes(range(width * height))
    rec = bytes(body) + px + (pal if pal is not None else palette())
    size = declared if declared is not None else len(rec) - vc_iff.HEADER
    out = bytearray(rec)
    struct.pack_into(">2I", out, vc_iff.SIZE_AT, size, size)
    return bytes(out)


def test_a_record_comes_out_named_and_sized():
    (tex,) = vc_iff.textures(record())
    assert (tex.name, tex.width, tex.height) == ("TEST", 8, 4)
    assert len(tex.pixels) == 32


def test_detection_is_the_tag_at_sixteen_not_the_extension():
    """The tag sits at +16, which is inside the 64 bytes classify sniffs."""
    data = record()
    assert plugin.detect("AOSTREET.IFF", data[:64], len(data))
    assert not plugin.detect("AOSTREET.IFF", bytes(64), len(data))


def test_a_record_whose_dimensions_do_not_match_its_length_is_declined():
    """176 + width * height + 512 == record size is the whole safety property: a header
    read at the wrong place is skipped rather than turned into a garbage picture."""
    data = bytearray(record())
    at = vc_iff.NAME_AT + (4 + 4) // 4 * 4 + vc_iff.DIMS_GAP
    struct.pack_into(">2I", data, at, 16, 16)
    assert vc_iff.textures(bytes(data)) == []


def test_several_records_walk_by_their_own_declared_size():
    data = record(name="AAA") + record(name="BBB", width=4, height=4) + record(name="CCC")
    assert [t.name for t in vc_iff.textures(data)] == ["AAA", "BBB", "CCC"]


def test_an_unprintable_name_is_refused():
    data = bytearray(record())
    data[vc_iff.NAME_AT] = 1
    assert vc_iff.textures(bytes(data)) == []


def test_the_palette_is_rgb565_big_endian():
    pal = [0] * 256
    pal[1] = 0xF800  # five bits of red, none of green or blue
    px = bytes([1]) * 32
    (tex,) = vc_iff.textures(record(pixels=px, pal=palette(pal)))
    rgba = vc_iff.decode(tex)
    assert tuple(rgba[0, 0]) == (255, 0, 0, 255)


def test_the_indices_are_row_major_not_gx_tiled():
    """Every other GameCube texture in this project is tiled; these are not, and reading
    them as C8 tiles scrambles the picture."""
    (tex,) = vc_iff.textures(record(width=8, height=4))
    rgba = vc_iff.decode(tex)
    red = rgba[:, :, 0].astype(int)
    assert list(red[0]) == sorted(red[0]) and red[0][0] < red[0][-1]
    assert red[1][0] > red[0][-1]


def test_the_plugin_returns_a_textures_only_scene():
    data = record(name="HEAD0000") + record(name="HEAD0001")
    (scene,) = plugin.extract(data, "game.dat/AOSTREET.IFF", None)
    assert scene.extras["textures_only"]
    assert set(scene.textures) == {"HEAD0000", "HEAD0001"}
    assert scene.textures["HEAD0000"].shape == (4, 8, 4)


def test_two_records_sharing_a_name_do_not_collide():
    data = record(name="SAME") + record(name="SAME")
    (scene,) = plugin.extract(data, "game.dat/X.IFF", None)
    assert len(scene.textures) == 2


def test_a_truncated_record_ends_the_walk_instead_of_raising():
    data = record() + record()[:100]
    assert len(vc_iff.textures(data)) == 1


def test_decode_returns_rgba_of_the_declared_shape():
    (tex,) = vc_iff.textures(record(width=16, height=8))
    assert vc_iff.decode(tex).shape == (8, 16, 4)
    assert vc_iff.decode(tex).dtype == np.uint8
