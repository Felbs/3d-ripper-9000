"""Konami TMNT texture packs (RenderWare chunk 0x23 + rwID_IMAGE) and AFS archives."""

import struct

from gcrip.formats import konami_pac
from gcrip.plugins import afs


def make_pack() -> bytes:
    lib = 0x1005FFFF
    pixels = bytes([0, 1, 1, 0] * 4)  # 4x4, depth 4, stride 4
    palette = bytes([255, 0, 0, 255] + [0, 0, 255, 255] + [0] * 56)
    image = struct.pack("<3I", 1, 16, lib) + struct.pack("<4I", 4, 4, 4, 4) + pixels + palette
    chunk = struct.pack("<3I", 0x18, len(image), lib) + image
    entry = b"brick\0".ljust(16, b"\0") + bytes(56) + chunk
    payload = struct.pack("<I", 1) + entry
    return struct.pack("<3I", 0x23, len(payload), lib) + payload


def test_konami_pack():
    data = make_pack()
    assert konami_pac.is_pack(data[:16])
    texs = konami_pac.parse(data)
    assert [t.name for t in texs] == ["brick"]
    t = texs[0]
    assert t.rgba is not None and t.rgba.shape == (4, 4, 4)
    assert t.rgba[0, 0].tolist() == [255, 0, 0, 255] and t.rgba[0, 1].tolist() == [0, 0, 255, 255]


def test_afs_container():
    names = [b"a.dff".ljust(32, b"\0") + bytes(16), b"b.txd".ljust(32, b"\0") + bytes(16)]
    table = b"".join(names)
    head = b"AFS\0" + struct.pack("<I", 2)
    data_off = 0x40
    entries = struct.pack("<2I", data_off, 4) + struct.pack("<2I", data_off + 4, 3)
    nt_off = data_off + 8
    data = head + entries + struct.pack("<2I", nt_off, len(table))
    data = data.ljust(data_off, b"\0") + b"DFF!" + b"TXD" + b"\0" + table
    assert afs.is_container("TMNT.DAT", data[:16])
    assert afs.expand(data) == [("a.dff", b"DFF!"), ("b.txd", b"TXD")]
