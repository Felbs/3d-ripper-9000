"""Eighting FPK archives and their PRS compression."""

import struct

from gcrip.formats import fpk
from gcrip.plugins import fpk as plug


def prs_compress_simple(data: bytes) -> bytes:
    """Literals only (flag bytes of all ones) - enough to exercise the reader."""
    out = bytearray()
    for i in range(0, len(data), 8):
        chunk = data[i : i + 8]
        out.append(0xFF)
        out += chunk
    return bytes(out)


def test_prs_copies():
    # flag 0b1111_0011: 4 literals, (0,0) short copy, length bits 11 -> 5, offset byte 0xfc
    # (-4): "abcd" + "abcda"
    src = bytes([0xF3]) + b"abcd" + bytes([0xFC])
    assert fpk.prs_decompress(src, 9) == b"abcdabcda"
    # long copy: flag 0b1111_0100 -> 4 literals, then (0,1) long, u16 BE = offset -4 << 3 | len 2
    code = ((-4 << 3) & 0xFFFF) | 2  # length 2 + 2
    src = bytes([0xF4]) + b"wxyz" + struct.pack(">H", code)
    assert fpk.prs_decompress(src, 8) == b"wxyzwxyz"


def build_fpk() -> tuple[bytes, bytes, bytes]:
    dat = b"\0\0\0\x40" + bytes(60)
    txg = b"TXG" + bytes(29)
    packed = prs_compress_simple(dat)
    body = packed + txg
    count = 2
    hs = 16
    entries = b"hr/ank/0000.dat".ljust(20, b"\0") + struct.pack(
        ">3I", hs + 64, len(packed), len(dat)
    )
    entries += b"hr/ank/0000.txg".ljust(20, b"\0") + struct.pack(
        ">3I", hs + 64 + len(packed), len(txg), len(txg)
    )
    total = hs + len(entries) + len(body)
    head = struct.pack(">4I", 0, count, hs, total)
    return head + entries + body, dat, txg


def test_fpk_wide_names():
    dff = b"\x10\x00\x00\x00" + bytes(28)
    name = b"chr/ar2/0000_gc.dff".ljust(32, b"\0")
    entries = name + struct.pack(">3I", 16 + 48, len(dff), len(dff))
    data = struct.pack(">4I", 0, 1, 16, 16 + 48 + len(dff)) + entries + dff
    assert [(m.name, m.size) for m in fpk.members(data)] == [("chr/ar2/0000_gc.dff", 32)]
    assert plug.expand(data) == [("chr/ar2/0000_gc.dff", dff)]


def test_fpk_members():
    data, dat, txg = build_fpk()
    assert fpk.is_fpk(data[:64], len(data))
    assert plug.is_container("files/fpack/chr/ank0000.fpk", data[:64])
    assert not plug.is_container("files/x.bin", data[:64])
    assert plug.expand(data) == [("hr/ank/0000.dat", dat), ("hr/ank/0000.txg", txg)]
