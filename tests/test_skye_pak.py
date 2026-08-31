"""Darkened Skye PAK archives."""

import struct

from gcrip.formats import skye_pak
from gcrip.plugins import skye_pak as plugin


def build(names=("COIN.SKX", "DRAAK.SKX"), pad: int = 20) -> bytes:
    table = b"".join(n.encode() + b"\0" for n in names)
    head = bytearray(skye_pak.NAMES_AT)
    head[:4] = skye_pak.MAGIC
    struct.pack_into("<2I", head, 4, 1, len(table))
    entries = bytearray()
    body = bytearray()
    data_at = skye_pak.NAMES_AT + len(table) + pad + len(names) * skye_pak.ENTRY
    off = 0
    for n in names:
        payload = b"\x00XKS" + n.encode()
        rec = bytearray(skye_pak.ENTRY)
        struct.pack_into("<5I", rec, 0, table.index(n.encode()), 0, 0, data_at + off, len(payload))
        entries += rec
        body += payload
        off += len(payload)
    return bytes(head) + table + bytes(pad) + bytes(entries) + bytes(body)


def test_members_tile_and_are_named():
    d = build()
    ms = skye_pak.members(d)
    assert [m.name for m in ms] == ["COIN.SKX", "DRAAK.SKX"]
    assert ms[0].offset + ms[0].size == ms[1].offset
    assert plugin.is_container("Level14.pak", d[:64])
    got = plugin.expand(d)
    assert got[0][1].startswith(b"\x00XKS")


def test_the_table_is_found_whatever_the_padding():
    """The entry table does not start right after the names, so it is located by tiling."""
    for pad in (0, 4, 20, 64):
        assert [m.name for m in skye_pak.members(build(pad=pad))] == ["COIN.SKX", "DRAAK.SKX"]


def test_rejects_junk():
    assert not skye_pak.is_pak(b"nope")
    assert skye_pak.members(b"PAK\0" + bytes(64)) == []  # zero name table
    assert plugin.detect("x.pak", b"", 0) is False
    assert plugin.extract(b"", "x.pak", None) == []


def test_repeated_names_are_kept_apart():
    d = build(names=("COIN.SKX", "COIN.SKX"))
    assert [n for n, _ in plugin.expand(d)] == ["COIN.SKX", "COIN_001.SKX"]
