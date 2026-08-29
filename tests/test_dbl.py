"""Avalanche DBL / DBU sub-database splitting (formats.dbl; the plugin parses records)."""

import struct

from gcrip.formats import dbl
from gcrip.plugins import dbl as plug


def block(kind: int, payload: bytes, little: bool = False) -> bytes:
    fmt = "<" if little else ">"
    hdr = struct.pack(fmt + "HHIH", 1, kind, len(payload), 4) + b"1000\0\0" + bytes(0x30)
    return hdr + payload


def test_dbl_blocks():
    text = b"320    \n" + b"build notes\n".ljust(312, b" ")
    data = (
        text + block(0xE, bytes(0x200)) + block(0xB, bytes(0x40)) + block(0xE, bytes(0x300), True)
    )
    assert dbl.is_dbl("files/x.dbu", data[:64])
    bl = dbl.blocks(data)
    assert [(b.kind, b.size, b.little) for b in bl] == [
        (0xE, 0x200, False),
        (0xB, 0x40, False),
        (0xE, 0x300, True),
    ]
    members = dbl.expand(data)
    assert [n for n, _ in members] == [
        "000_kinde.dbl",
        "002_kinde.dbl",
    ]  # the 0x40 block is too small
    assert len(members[1][1]) == 0x40 + 0x300
    assert plug.detect("files/Burial.dbu", data[:64], len(data))
    assert plug.extract(data, "files/Burial.dbu", None) == []
