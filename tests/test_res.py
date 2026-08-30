"""'res\\n' resource files (Digimon Rumble Arena 2, Lemony Snicket, Samurai Jack)."""

import struct

from gcrip.formats import res
from gcrip.plugins import res as plugin


def build() -> bytes:
    data_off = 0x1000
    payloads = [(b"wave", 4, b"AUDIODATA"), (b"surf", 44, b"TEXTUREBYTES!"), (b"strg", 28, b"hi")]
    body = bytearray()
    entries = []
    for tag, ident, blob in payloads:
        entries.append((ident, tag, len(body), len(blob)))
        body += blob
    dir_off = data_off + 0x1000
    out = bytearray(dir_off)
    out[:4] = res.MAGIC
    struct.pack_into("<H", out, 4, 7)  # version, little-endian
    struct.pack_into(">2I", out, 8, data_off, len(body))
    struct.pack_into(">2I", out, 0x1C, dir_off, 4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", out, 0x24, len(entries))
    out[data_off : data_off + len(body)] = body
    dirbuf = bytearray(4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", dirbuf, 0, len(entries))
    for i, (ident, tag, off, size) in enumerate(entries):
        struct.pack_into(">I4sIII", dirbuf, 4 + i * res.ENTRY, ident, tag, off, size, 0)
    return bytes(out) + bytes(dirbuf)


def test_sections():
    d = build()
    assert res.is_res(d[:0x28])
    secs = res.sections(d)
    assert [(s.tag, s.ident, s.size) for s in secs] == [
        ("wave", 4, 9),
        ("surf", 44, 13),
        ("strg", 28, 2),
    ]
    assert d[secs[1].offset : secs[1].offset + secs[1].size] == b"TEXTUREBYTES!"


def test_plugin_expands_named_sections():
    d = build()
    assert plugin.is_container("final_cavern.res", d[:0x28])
    out = plugin.expand(d)
    assert [n for n, _ in out] == ["000_wave_4.bin", "001_surf_44.bin", "002_strg_28.bin"]
    assert out[1][1] == b"TEXTUREBYTES!"
    assert plugin.detect("x.res", d[:0x28], len(d)) is False
    assert plugin.extract(d, "x.res", None) == []
    assert not res.is_res(b"nope" + bytes(0x28))
