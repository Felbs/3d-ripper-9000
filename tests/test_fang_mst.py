"""Midway Fang .mst archives - Freaky Flyers."""

import struct

from gcrip.formats import fang_mst, gx_texture
from gcrip.plugins import fang_mst as plugin


def lzo_literals(raw: bytes) -> bytes:
    """An LZO1X stream of one literal run (17 < n <= 238) and the end mark."""
    assert 1 <= len(raw) <= 238 - 17
    return bytes([len(raw) + 17]) + raw + b"\x11\x00\x00"


def build(members):
    table = b""
    body = b""
    base = fang_mst.ENTRIES_AT + fang_mst.ENTRY * len(members)
    for name, raw in members:
        packed = lzo_literals(raw)
        entry = name.encode().ljust(fang_mst.NAME, b"\0")
        entry += struct.pack(
            "<4I", base + len(body), len(packed), 0x3ED3F408, len(raw) + fang_mst.SLACK
        )
        table += entry
        body += packed
    total = base + len(body)
    head = fang_mst.MAGIC + bytes([0, 7, 1, 24]) + struct.pack("<I", total)
    head += struct.pack("<I", len(members)) + struct.pack("<7I", 0, 0, 0, 0, 6, 6, 6)
    head = head.ljust(fang_mst.ENTRIES_AT, b"\0")
    return head + table + body


def build_gtx(width=8, height=8, fmt=1):
    head = bytearray(0x59)
    struct.pack_into(">I", head, plugin.GTX_HEADER_AT, 0x59)
    struct.pack_into(">2H", head, plugin.GTX_SIZE_AT, width, height)
    struct.pack_into(">2H", head, plugin.GTX_SIZE_AT + 8, width, height)
    struct.pack_into(">I", head, plugin.GTX_FORMAT_AT, fmt)
    size = gx_texture.encoded_size(fmt, width, height)
    return bytes(head) + bytes(range(size))[:size].ljust(size, b"\0")


def test_entries_and_members_round_trip():
    data = build(
        [
            ("andre.gob", b"\x0c\0\0\0CGfPlayerDef\0" + bytes(20)),
            ("lever.gmo", b"lever\0mo" + bytes(40)),
        ]
    )
    assert fang_mst.is_mst(data[:16], len(data))
    ents = fang_mst.entries(data)
    assert [e.name for e in ents] == ["andre.gob", "lever.gmo"]
    assert ents[0].unpacked == 37
    assert fang_mst.member(data, ents[1]) == b"lever\0mo" + bytes(40)


def test_container_plugin_expands_by_name():
    data = build([("a.gob", b"abc" * 10), ("t.gtx", build_gtx())])
    assert plugin.is_container("OHTD_gc.mst", data[:64])
    out = dict(plugin.expand(data))
    assert set(out) == {"a.gob", "t.gtx"}
    assert out["a.gob"] == b"abc" * 10


def test_gtx_textures_decode():
    data = build_gtx()
    assert plugin.detect("m/t.gtx", data[:64], len(data))
    scenes = plugin.extract(data, "m/t.gtx", None)
    assert len(scenes) == 1 and scenes[0].extras["textures_only"]
    assert scenes[0].textures["t"].shape == (8, 8, 4)
    assert not plugin.detect("m/t.gtx", bytes(64), 64)
