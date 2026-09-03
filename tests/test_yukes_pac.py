"""Yuke's .pac / .tex packs (WWE Day of Reckoning, WrestleMania XIX): a flat little-endian
name / type / size / offset table."""

from __future__ import annotations

import struct

from gcrip.formats import yukes_pac
from gcrip.plugins import yukes_pac as plugin


def pack(items: list[tuple[str, str, bytes]]) -> bytes:
    table = 16 + 32 * len(items)
    body = bytearray()
    head = bytearray(struct.pack("<4I", len(items), 0x100, 0, 16))
    for name, kind, blob in items:
        head += name.encode().ljust(16, b"\0") + kind.encode().ljust(4, b"\0")
        head += struct.pack("<III", len(blob), table + len(body), 0)
        body += blob + bytes(-len(blob) % 32)
    return bytes(head) + bytes(body)


def test_pack_entries_and_expansion():
    data = pack(
        [
            ("g_skin", "tpl", b"\x00\x20\xaf\x30" + bytes(28)),
            ("floor", "ymg", b"YOBJ" + bytes(60)),
            ("floor", "ymg", b"YOBJ"),
        ]
    )
    assert yukes_pac.is_pac(data[:64], len(data))
    assert plugin.is_container("edit_data/TEX/Gears/tz0_120.tex", data[:64])
    assert plugin.is_container("bg/Aar.pac", data[:64])
    assert not plugin.is_container("bg/Aar.ymg", data[:64])
    ents = yukes_pac.entries(data)
    assert [(e.name, e.kind, e.size) for e in ents] == [
        ("g_skin", "tpl", 32),
        ("floor", "ymg", 64),
        ("floor", "ymg", 4),
    ]
    members = plugin.expand(data)
    assert [n for n, _ in members] == ["g_skin.tpl", "floor.ymg", "floor_1.ymg"]
    assert members[0][1][:4] == b"\x00\x20\xaf\x30" and members[2][1] == b"YOBJ"
    assert not yukes_pac.is_pac(bytes(64), 64)
