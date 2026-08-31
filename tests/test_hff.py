"""HFF data files - Aquaman, Casper, TONKA Rescue Patrol.  No directory, so members are carved."""

import io

from PIL import Image

from gcrip.formats import hff, png
from gcrip.plugins import hff as plugin


def image(width=8, height=8):
    with io.BytesIO() as fh:
        Image.new("RGBA", (width, height), (10, 20, 30, 255)).save(fh, format="PNG")
        return fh.getvalue()


def build(gap=b"// this file contains the path to the *.obd file\r\n", count=3):
    body = gap
    for i in range(count):
        body += image(8 + i, 8)
        body += bytes(16)  # padding between members
    return body


def test_members_are_carved_between_the_signature_and_iend():
    got = hff.members(build())
    assert len(got) == 3
    assert [m.name for m in got] == ["image_00000.png", "image_00001.png", "image_00002.png"]


def test_each_carved_member_decodes():
    data = build()
    for name, blob in plugin.expand(data):
        assert blob.startswith(png.MAGIC) and blob.endswith(png.END), name
        assert png.decode(blob) is not None


def test_a_signature_with_no_terminator_is_skipped():
    data = build() + png.MAGIC + b"truncated, no IEND here"
    assert len(hff.members(data)) == 3


def test_leading_text_does_not_stop_the_walk():
    """Casper and TONKA open with a comment, Aquaman with the first PNG."""
    assert len(hff.members(build(gap=b""))) == 3
    assert len(hff.members(build(gap=b"// a comment\r\n" * 8))) == 3


def test_only_the_hff_extension_is_claimed():
    data = build()
    assert plugin.is_container("data.hff", data[:64])
    assert not plugin.is_container("data.dat", data[:64])


def test_a_stray_signature_shorter_than_the_minimum_is_not_a_member():
    data = png.MAGIC + png.END + build()
    assert len(hff.members(data)) == 3
