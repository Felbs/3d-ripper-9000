"""Textures in Blitz Games .gcp packs (Bratz, Bad Boys, Pac-Man World 3, ...)."""

import struct

from gcrip.formats import blitz_tex
from gcrip.formats import gx_texture as gx
from gcrip.plugins import blitz_tex as plugin


def pack_header() -> bytes:
    """The 0x20-byte-data-start pack header the .gcp reader recognises."""
    head = bytearray(blitz_tex.FIRST)
    struct.pack_into(">3I", head, 0, 0x1234, 0x20, 0)
    return bytes(head)


def descriptor(w: int, h: int, fmt: int) -> bytes:
    d = bytearray(blitz_tex.DESCRIPTOR)
    struct.pack_into(">7I", d, 0, w, h, fmt, 0x101, 0, 0xFF000000, w * h)
    return bytes(d)


def build(*specs) -> bytes:
    out = bytearray(pack_header())
    for w, h, fmt in specs:
        out += descriptor(w, h, fmt)
        out += bytes(gx.encoded_size(blitz_tex.GX_FOR[fmt], w, h))
    return bytes(out)


def test_walks_a_chain_of_descriptors():
    d = build((128, 128, 21), (128, 128, 21))
    found = blitz_tex.textures(d)
    assert [(t.width, t.height, t.format) for t in found] == [(128, 128, 21), (128, 128, 21)]
    # CMPR is 4 bits per pixel, and the second descriptor sits right after the first's pixels
    assert found[0].size == 128 * 128 // 2
    assert found[1].offset == found[0].offset + found[0].size + blitz_tex.DESCRIPTOR
    # the gap between descriptors is the arithmetic that proved the 160-byte size
    first_desc = found[0].offset - blitz_tex.DESCRIPTOR
    second_desc = found[1].offset - blitz_tex.DESCRIPTOR
    assert second_desc - first_desc == 8192 + 160


def test_rgba8_and_cmpr_sizes():
    d = build((32, 32, 15), (32, 32, 21))
    a, b = blitz_tex.textures(d)
    assert a.size == 32 * 32 * 4
    assert b.size == 32 * 32 // 2
    assert blitz_tex.decode(d, a).shape == (32, 32, 4)
    assert blitz_tex.decode(d, b).shape == (32, 32, 4)


def test_the_width_times_height_field_gates_the_walk():
    d = bytearray(build((64, 64, 21)))
    struct.pack_into(">I", d, blitz_tex.FIRST + 24, 999)  # count no longer width*height
    assert blitz_tex.textures(bytes(d)) == []


def test_unknown_formats_stop_the_chain_rather_than_guess():
    # format 17 is real but undecoded; the walk must stop, not invent a size
    d = build((64, 64, 21)) + descriptor(64, 64, 17) + bytes(4096)
    assert [t.format for t in blitz_tex.textures(d)] == [21]
    assert not blitz_tex.textures(pack_header())  # no descriptor at all
    assert not blitz_tex.textures(b"short")


def test_truncated_pixel_data_is_rejected():
    d = build((128, 128, 21))[: blitz_tex.FIRST + blitz_tex.DESCRIPTOR + 100]
    assert blitz_tex.textures(d) == []


def test_plugin_makes_a_textures_only_scene():
    d = build((32, 32, 21), (32, 32, 15))
    assert plugin.detect("packages/common_BP Earrings 01 Sector.gcp", d[:64], len(d))
    assert not plugin.detect("packages/thing.bin", d[:64], len(d))
    scenes = plugin.extract(d, "packages/common_BP Earrings 01 Sector.gcp", None)
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene.extras["textures_only"] is True
    assert scene.extras["count"] == 2
    assert sorted(scene.textures) == [
        "common_BP Earrings 01 Sector_00",
        "common_BP Earrings 01 Sector_01",
    ]
    # a single texture keeps the pack's own name
    one = plugin.extract(build((32, 32, 21)), "x/common_Thing.gcp", None)[0]
    assert list(one.textures) == ["common_Thing"]
    assert plugin.extract(pack_header(), "x/common_Thing.gcp", None) == []


def test_an_undecodable_format_is_stepped_over_not_stopped_at():
    """Format 17's encoding is unknown but its size is not - 16 bits per pixel - so it must
    not hide the textures behind it in the chain."""
    import struct

    from gcrip.formats import blitz_tex
    from gcrip.formats import gx_texture as gx

    def descriptor(w, h, fmt):
        return struct.pack(">7I", w, h, fmt, 0x101, 0, 0xFF000000, w * h).ljust(
            blitz_tex.DESCRIPTOR, b"\0"
        )

    body = bytes(blitz_tex.FIRST)
    body += descriptor(16, 16, 17) + bytes(16 * 16 * blitz_tex.BYTES_PER_PIXEL[17])
    body += descriptor(8, 8, 21) + bytes(gx.encoded_size(0xE, 8, 8))
    got = blitz_tex.textures(body)
    assert [(t.width, t.format) for t in got] == [(8, 21)]


def test_the_unknown_format_size_is_sixteen_bits_a_pixel():
    from gcrip.formats import blitz_tex

    assert blitz_tex.BYTES_PER_PIXEL == {17: 2}


def test_descriptors_counts_what_textures_hides():
    """`textures` returns only what it can decode, so a census built on it reports format 17 as
    absent no matter how much of it a disc holds.  That cost two wrong measurements of how
    common the format is; `descriptors` is the one to count with."""
    body = pack_header() + descriptor(64, 64, 21) + bytes(64 * 64 // 2)
    body += descriptor(16, 16, 17) + bytes(16 * 16 * blitz_tex.BYTES_PER_PIXEL[17])
    body += descriptor(32, 32, 15) + bytes(32 * 32 * 4)
    every = blitz_tex.descriptors(body)
    assert [d.format for d in every] == [21, 17, 15]
    assert [t.format for t in blitz_tex.textures(body)] == [21, 15]
    assert 17 not in {t.format for t in blitz_tex.textures(body)}
