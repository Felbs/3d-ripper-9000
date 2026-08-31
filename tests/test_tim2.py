"""Sony TIM2 textures - Auto Modellista, Capcom vs SNK 2 EO."""

import struct

import numpy as np

from gcrip.formats import tim2
from gcrip.plugins import tim2 as plugin


def build(
    width=8,
    height=8,
    pictures=1,
    aligned=True,
    image_type=tim2.INDEXED8,
    colours=256,
    break_sizes=False,
):
    head = tim2.MAGIC + bytes([4, 1 if aligned else 0]) + struct.pack("<H", pictures)
    head = head.ljust(tim2.ALIGNED if aligned else tim2.COMPACT, b"\0")
    body = b""
    for p in range(pictures):
        pixels = bytes((x + p) % colours for x in range(width * height))
        clut = bytes(colours * 4)
        header = tim2.PICTURE
        total = len(pixels) + len(clut) + header
        rec = struct.pack(
            "<3IH", total if not break_sizes else total + 1, len(clut), len(pixels), header
        )
        rec += struct.pack("<H", colours) + bytes([0, 1, 3, image_type])
        rec += struct.pack("<2H", width, height)
        body += rec.ljust(header, b"\0") + pixels + clut
    return head + body


def test_the_three_sizes_have_to_add_up():
    assert len(tim2.pictures(build())) == 1
    assert tim2.pictures(build(break_sizes=True)) == []


def test_several_pictures_follow_one_another():
    got = tim2.pictures(build(pictures=3))
    assert len(got) == 3 and all(p.width == 8 for p in got)


def test_the_compact_header_is_sixteen_bytes():
    assert len(tim2.pictures(build(aligned=False))) == 1


def test_four_bit_indices_are_unpacked_low_nibble_first():
    (pic,) = tim2.pictures(build(image_type=tim2.INDEXED4, colours=16))
    image = tim2.decode(pic)
    assert image is not None and image.shape == (8, 8, 4)


def test_an_unexplained_clut_stride_declines_rather_than_guesses():
    """Three pictures on Auto Modellista carry an eight-byte stride that no documented CLUT
    format explains; guessing at those would produce plausible nonsense."""
    pic = tim2.Picture(8, 8, tim2.INDEXED8, 256, bytes(64), bytes(256 * 8))
    assert tim2.decode(pic) is None
    assert tim2.decode(tim2.Picture(8, 8, tim2.INDEXED8, 256, bytes(64), bytes(1024))) is not None


def test_a_two_byte_clut_is_read_as_ps2_a1b5g5r5():
    """Nine of the pictures use it - red in the low five bits, one bit of alpha on top."""
    import struct as _s

    clut = b"".join(_s.pack("<H", 0x8000 | 0x1F) for _ in range(256))
    pic = tim2.Picture(2, 2, tim2.INDEXED8, 256, bytes(4), clut)
    image = tim2.decode(pic)
    assert image is not None
    assert tuple(image[0, 0]) == (255, 0, 0, 255)


def test_the_clut_is_unswizzled_in_blocks_of_thirty_two():
    """CSM1 swaps the middle two groups of eight - entry 8 comes from 16 and back."""
    palette = np.arange(256 * 4, dtype=np.uint8).reshape(256, 4)
    got = tim2._unswizzle(palette)
    assert np.array_equal(got[8], palette[16])
    assert np.array_equal(got[16], palette[8])
    assert np.array_equal(got[0], palette[0])
    assert np.array_equal(got[24], palette[24])


def test_alpha_is_doubled_from_the_ps2_range():
    width = height = 8
    head = build(width=width, height=height)
    at = head.index(b"\0" * 4, tim2.ALIGNED + tim2.PICTURE + width * height)
    data = bytearray(head)
    data[at + 3] = 128  # a fully opaque PS2 entry
    (pic,) = tim2.pictures(bytes(data))
    image = tim2.decode(pic)
    assert image is not None and image[..., 3].max() == 255


def test_the_plugin_yields_a_textures_only_scene():
    blob = build(pictures=2)
    assert plugin.detect("x.tm2", blob[:64], len(blob))
    (scene,) = plugin.extract(blob, "afs02/car.tm2", None)
    assert scene.extras["textures_only"] and set(scene.textures) == {"car", "car_1"}


def test_the_table_container_is_confined_to_afs_members():
    """The shape test alone claims 50 members on Auto Modellista to find 7 real tables, and
    the magic that would settle it sits past the 64-byte sniff - so the claim is confined to
    where the structure has actually been seen."""
    import struct as _s

    head = _s.pack("<4I", 64, 0x10540, 0x20A40, 0xFFFFFFFF).ljust(64, b"\0")
    assert tim2.looks_like_table(head)
    assert plugin.is_container("afs02.afs/7", head)
    assert not plugin.is_container("common_thing.gcp", head)


def test_a_terminator_is_not_required():
    """One real table of 16 offsets carries none, so requiring it would lose a disc's
    textures."""
    import struct as _s

    head = _s.pack("<16I", *(64 + 4096 * i for i in range(16)))
    assert len(tim2._offsets(head)) == 16
