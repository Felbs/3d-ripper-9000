"""EA TXG texture groups - the txf members of the Tiger Woods SHOC archives."""

import struct

from gcrip.formats import ea_txg
from gcrip.formats import gx_texture as gx
from gcrip.plugins import ea_txg as plugin


def chunk(tag, payload):
    """TXG's size excludes the eight-byte header - the opposite of the SHOC holding it."""
    return tag + struct.pack(">I", len(payload)) + payload


def header(name, width, height, fmt, offset):
    rec = bytearray(ea_txg.ENTRY)
    rec[: len(name)] = name
    struct.pack_into(">I", rec, ea_txg.MIP0_AT, offset)
    struct.pack_into(">2H", rec, ea_txg.SIZE_AT, width, height)
    rec[ea_txg.FORMAT_AT] = fmt
    return bytes(rec)


def build(entries=((b"tbmulch", 64, 64, 0xE), (b"tbcp1", 32, 32, 0x5))):
    heads, pixels = b"", b""
    for name, w, h, fmt in entries:
        heads += header(name, w, h, fmt, len(pixels))
        pixels += bytes(gx.encoded_size(fmt, w, h))
    return (
        ea_txg.MAGIC
        + bytes([2, 2, 1, 0])
        + chunk(b"HEAD", bytes(8))
        + chunk(b"TXHE", heads)
        + chunk(b"CLHE", b"")
        + chunk(b"TXDA", pixels)
        + chunk(b"CLDA", b"")
    )


def test_the_chunk_size_excludes_the_header():
    """Read the SHOC way - size including the header - and the walk stops on the first chunk."""
    got = ea_txg.textures(build())
    assert [t.name for t in got] == ["tbmulch", "tbcp1"]


def test_a_header_is_eighty_eight_bytes():
    data = build()
    assert ea_txg.ENTRY == 88
    assert len(ea_txg.textures(data)) == 2


def test_dimensions_and_format_come_from_the_record():
    a, b = ea_txg.textures(build())
    assert (a.width, a.height, a.format) == (64, 64, 0xE)
    assert (b.width, b.height, b.format) == (32, 32, 0x5)


def test_a_texture_running_past_the_pixel_chunk_is_dropped():
    data = build()
    bad = bytearray(data)
    at = data.index(b"TXHE") + 8
    struct.pack_into(">I", bad, at + ea_txg.MIP0_AT, 1 << 20)
    assert [t.name for t in ea_txg.textures(bytes(bad))] == ["tbcp1"]


def test_an_unknown_gx_format_is_refused():
    data = bytearray(build())
    at = data.index(b"TXHE") + 8
    data[at + ea_txg.FORMAT_AT] = 0x7F
    assert [t.name for t in ea_txg.textures(bytes(data))] == ["tbcp1"]


def test_the_plugin_names_every_texture_with_a_material():
    """A texture no material names is dropped at export - see textures-only-scenes.md."""
    blob = build()
    assert plugin.detect("x", blob[:64], len(blob))
    (scene,) = plugin.extract(blob, "hole.hog/txfh", None)
    assert set(scene.textures) == {"tbmulch", "tbcp1"}
    assert {m.texture for m in scene.materials} == set(scene.textures)
