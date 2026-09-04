"""Acclaim supertree0.tre - Vexx, Turok: Evolution."""

import struct

from gcrip.formats import acclaim_tre, gx_texture
from gcrip.plugins import acclaim_tre as plugin


def build_texture(width=8, height=8, kind=0x30):
    fmt = acclaim_tre.TEXTURE_FORMATS[kind]
    size = gx_texture.encoded_size(fmt, width, height)
    head = (
        bytes(10) + struct.pack(">HI", size, 0) + struct.pack(">4H", width, height, width, height)
    )
    head += b"\xff\xff" + bytes([0x00, 0x59, 0xFF, kind, 0x01, 0x00])
    assert len(head) == acclaim_tre.TEXTURE_HEADER
    return head + bytes(k & 0xFF for k in range(size))


def build(members):
    """members: list of (key, blob); keys must ascend."""
    table = b""
    body = b""
    base = acclaim_tre.RECORD * len(members)
    for k, (key, blob) in enumerate(members):
        table += struct.pack(">4I", 1000 + k, base + len(body), len(blob), key)
        body += blob
    return table + body


def test_table_stops_where_keys_stop_ascending():
    data = build([(1, b"a" * 10), (5, build_texture()), (9, b"SWAP" + bytes(60))])
    ents = acclaim_tre.table(data[:256], len(data))
    assert [e.key for e in ents] == [1, 5, 9] and ents[1].size == len(build_texture())
    assert acclaim_tre.is_tre(data[:48], len(data)) is True
    big = build([(k * 7, b"x" * 4) for k in range(10)])
    assert acclaim_tre.is_tre(big[:256], len(big))
    assert acclaim_tre.table(bytes(64), 64) == []


def test_container_names_textures_and_skips_swap():
    members = [(k * 7, b"x" * 4) for k in range(8)] + [
        (100, build_texture()),
        (200, b"SWAP" + bytes(60)),
    ]
    data = build(members)
    assert plugin.is_container("files/supertree0.tre", data[:256])
    out = plugin.expand(data)
    names = [n for n, _ in out]
    assert names == ["tex_00000064.atx"]


def test_texture_decodes():
    data = build_texture(16, 8, 0x2C)
    assert plugin.detect("x/tex_00000064.atx", data[:32], len(data))
    scenes = plugin.extract(data, "x/tex_00000064.atx", None)
    assert scenes and scenes[0].textures["tex_00000064"].shape == (8, 16, 4)
    assert not plugin.detect("x/tex_00000064.atx", bytes(32), 32)


def test_nested_tables_are_walked():
    inner = build([(k * 3, b"y" * 4) for k in range(8)] + [(50, build_texture())])
    data = build([(k * 7, b"x" * 4) for k in range(8)] + [(100, inner)])
    names = [n for n, _ in plugin.expand(data)]
    assert "00000064/tex_00000032.atx" in names
    assert not any(n == "00000064.bin" for n in names)
