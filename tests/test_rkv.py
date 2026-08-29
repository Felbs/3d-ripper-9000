"""Krome RKV v1 archives: directory at the end of the file."""

import struct

from gcrip.formats import rkv
from gcrip.plugins import rkv as plug


def build_rkv() -> tuple[bytes, bytes, bytes]:
    a, b = b"MDL2" + bytes(60), b"GTX!" + bytes(28)
    data = bytearray(a + b)
    dirs = [b"Models\\", b"Textures\\"]
    ents = []
    for name, didx, off, size in (
        (b"ty.gmd", 0, 0, len(a)),
        (b"ty.gtx", 1, len(a), len(b)),
        (b"src.tga", 1, 0xFFFFFFFF, 123),
    ):
        e = name.ljust(32, b"\0") + struct.pack("<8I", didx, size, 0, off, 0, 0, 0, 0)
        ents.append(e)
    data += b"".join(ents) + b"".join(x.ljust(256, b"\0") for x in dirs)
    data += struct.pack("<II", len(ents), len(dirs))
    return bytes(data), a, b


def build_rkv2() -> tuple[bytes, bytes, bytes]:
    a, b = b"MDL3" + bytes(60), b"MDG3" + bytes(28)
    names = b"ty.mdl\0ty.mdg\0"
    ents = struct.pack("<5I", 0, 0, len(a), 0x80, 0x11111111)
    ents += struct.pack("<5I", 7, 0, len(b), 0x80 + len(a), 0x22222222)
    body = a + b
    dir_off = 0x80 + len(body)
    directory = ents + names
    head = b"RKV2" + struct.pack("<6I", 2, len(names), 0, 16, dir_off, len(directory))
    head = head.ljust(0x80, b"\0")
    return head + body + directory, a, b


def test_rkv2_members():
    data, a, b = build_rkv2()
    assert rkv.is_rkv(data[:64])
    got = [(m.name, m.offset, m.size) for m in rkv.members(data)]
    assert got == [("ty.mdl", 0x80, 64), ("ty.mdg", 0x80 + 64, 32)]
    assert plug.expand(data) == [("ty.mdl", a), ("ty.mdg", b)]


def test_rkv_members():
    data, a, b = build_rkv()
    ms = rkv.members(data)
    got = [(m.name, m.offset, m.size) for m in ms]
    assert got == [("Models/ty.gmd", 0, 64), ("Textures/ty.gtx", 64, 32)]
    assert plug.is_container("files/Data_GC.rkv", data[:64])
    assert plug.expand(data) == [("Models/ty.gmd", a), ("Textures/ty.gtx", b)]
