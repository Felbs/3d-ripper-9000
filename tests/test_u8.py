"""Nintendo U8 archives (.arc directory format)."""

import struct

from gcrip.formats import u8
from gcrip.plugins import u8 as plugin

NAMES = b"\x00dir\x00a.tpl\x00b.gma\x00c.bin\x00"


def build() -> bytes:
    """Root, one directory with two files, and one file at the root."""
    at = {n: NAMES.index(n.encode() + b"\x00") for n in ("dir", "a.tpl", "b.gma", "c.bin")}
    nodes = [
        (1, 0, 0, 5),  # root: five nodes in total
        (1, at["dir"], 0, 4),  # dir/ holds nodes 2 and 3
        (0, at["a.tpl"], 0, 0),
        (0, at["b.gma"], 0, 0),
        (0, at["c.bin"], 0, 0),
    ]
    header = 0x20
    node_bytes = len(nodes) * u8.NODE
    strings_off = header + node_bytes
    data_off = strings_off + len(NAMES)
    payloads = [b"tpl-data", b"gma-data!", b"bin"]
    out = bytearray(data_off)
    struct.pack_into(">4sIII", out, 0, u8.MAGIC, header, node_bytes + len(NAMES), data_off)
    body = bytearray()
    placed = []
    for p in payloads:
        placed.append((data_off + len(body), len(p)))
        body += p
    it = iter(placed)
    for i, (kind, name_off, a, b) in enumerate(nodes):
        if kind == 0:
            a, b = next(it)
        struct.pack_into(
            ">B3sII", out, header + i * u8.NODE, kind, name_off.to_bytes(3, "big"), a, b
        )
    out[strings_off : strings_off + len(NAMES)] = NAMES
    return bytes(out) + bytes(body)


def test_entries_and_paths():
    data = build()
    assert u8.is_u8(data[:0x20])
    ents = u8.entries(data)
    assert [(e.path, e.size) for e in ents] == [
        ("dir/a.tpl", 8),
        ("dir/b.gma", 9),
        ("c.bin", 3),
    ]
    members = dict(u8.expand(data))
    assert members["dir/a.tpl"] == b"tpl-data"
    assert members["c.bin"] == b"bin"


def test_plugin_is_a_container_only():
    data = build()
    assert plugin.is_container("parts_all.arc", data[:0x20])
    assert [n for n, _ in plugin.expand(data)] == ["dir/a.tpl", "dir/b.gma", "c.bin"]
    assert plugin.detect("x.arc", data[:0x20], len(data)) is False
    assert plugin.extract(data, "x.arc", None) == []
    assert not u8.is_u8(b"RARC" + bytes(0x20))
