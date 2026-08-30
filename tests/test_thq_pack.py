"""THQ 'pack' archives (Avatar, Jimmy Neutron, Alien Hominid ...)."""

import struct

from gcrip.formats import thq_pack
from gcrip.plugins import thq_pack as plugin


def build() -> bytes:
    names = b"data/boot.rad\x00data/level.pak\x00"
    entries = 2
    names_off = thq_pack.TABLE + entries * thq_pack.ENTRY
    data_off = names_off + len(names)
    payloads = [b"first-member", b"second-member!!"]
    head = bytearray(data_off)
    body = bytearray()
    placed = []
    for p in payloads:
        placed.append((data_off + len(body), len(p)))
        body += p
    total = data_off + len(body)
    struct.pack_into(">4sIIIII", head, 0, thq_pack.MAGIC, 1, names_off, total, names_off, entries)
    for k, (off, size) in enumerate(placed):
        name_off = 0 if k == 0 else names.index(b"data/level.pak")
        struct.pack_into(">4I", head, thq_pack.TABLE + k * thq_pack.ENTRY, off, size, 0, name_off)
    head[names_off : names_off + len(names)] = names
    return bytes(head) + bytes(body)


def test_members():
    data = build()
    assert thq_pack.is_pack(data[: thq_pack.TABLE])
    mem = thq_pack.members(data)
    assert [(m.name, m.size) for m in mem] == [("data/boot.rad", 12), ("data/level.pak", 15)]
    out = dict(thq_pack.expand(data))
    assert out["data/boot.rad"] == b"first-member"
    assert out["data/level.pak"] == b"second-member!!"


def test_plugin_container_only():
    data = build()
    assert plugin.is_container("c2_DATA.PAK", data[:64])
    assert [n for n, _ in plugin.expand(data)] == ["data/boot.rad", "data/level.pak"]
    assert plugin.detect("x.pak", data[:64], len(data)) is False
    assert plugin.extract(data, "x.pak", None) == []
    assert not thq_pack.is_pack(b"PACK" + bytes(0x20))
