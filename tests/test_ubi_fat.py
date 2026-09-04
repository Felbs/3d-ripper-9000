"""Ubisoft .fat/.000 archives and Sin Tzu geoobj.bin - Batman: Vengeance, Rise of Sin Tzu."""

import struct

import numpy as np

from gcrip.formats import ubi_fat, ubi_geoobj
from gcrip.plugins import ubi_fat as fat_plugin
from gcrip.plugins import ubi_geoobj as geo_plugin

T1, T2 = 0x3BD08770, 0x3BD09580


def lzo_literals(raw: bytes) -> bytes:
    assert 1 <= len(raw) <= 238 - 17
    return bytes([len(raw) + 17]) + raw + b"\x11\x00\x00"


def build_store(files):
    """files: list of (name, raw). Each becomes one first block (flag 3); a raw longer than
    100 bytes is split into an LZO block and a stored continuation block."""
    store = b""
    entries = []
    for name, raw in files:
        offset = len(store)
        first, rest = raw[:100], raw[100:]
        packed = lzo_literals(first)
        store += (
            struct.pack("<3IB", len(first), len(packed), ubi_fat.MAGIC, ubi_fat.FLAG_FIRST) + packed
        )
        if rest:
            store += (
                struct.pack("<3IB", len(rest), len(rest), ubi_fat.MAGIC, ubi_fat.FLAG_STORED) + rest
            )
        entries.append((name, offset, len(raw), len(store) - offset))
    return store, entries


def build_fat(entries):
    out = b"\x01"
    out += struct.pack("<4I", 1, 1, 0, 0) + struct.pack("<3I", T1, T2, 11) + b"/gamedata/\0"
    out += (
        struct.pack("<4I", 0, 0x2C, 1, 0) + struct.pack("<3I", T1, T2, 18) + b"/gamedata/binary/\0"
    )
    for k, (name, offset, unpacked, packed) in enumerate(entries):
        full = f"/gamedata/binary/{name}\0".encode()
        out += struct.pack("<HHIIII", 0x100, 0, 100 + k, offset, unpacked, packed)
        out += struct.pack("<3I", T1, T2, len(full)) + full
    return out


def test_fat_entries_and_unpack():
    store, ents = build_store([("a.bin", b"alpha" * 4), ("b/long.bin", bytes(range(200)))])
    fat = build_fat(ents)
    assert ubi_fat.is_fat(fat[:64])
    found = ubi_fat.entries(fat)
    assert [e.name for e in found] == ["/gamedata/binary/a.bin", "/gamedata/binary/b/long.bin"]
    assert ubi_fat.unpack(store, found[0]) == b"alpha" * 4
    assert ubi_fat.unpack(store, found[1]) == bytes(range(200))


def test_container_reads_the_sibling_store():
    store, ents = build_store([("x.bin", b"x" * 50)])
    fat = build_fat(ents)
    assert fat_plugin.is_container("levels.fat", fat[:64])
    got = fat_plugin.expand_with(
        fat, "gamedata/Binary/levels.fat", lambda n: store if n == "levels.000" else None
    )
    assert got == [("binary/x.bin", b"x" * 50)]
    assert fat_plugin.expand_with(fat, "levels.fat", lambda n: None) == []


def build_geoobj():
    quad = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]
    verts = b"".join(
        struct.pack("<8f4B", x, y, z, 0, 1, 0, x, z, 255, 255, 255, 255) for x, y, z in quad
    )
    name = b"box/box.gmt^GameMaterial:lid\0"
    element = verts + struct.pack("<IBH", 4, 1, len(name)) + name + struct.pack("<4H", 0, 1, 3, 2)
    payload = ubi_geoobj.TAG + bytes(0x4F) + element
    record = struct.pack("<I", len(payload)) + payload
    return struct.pack("<I", 1) + record + record


def test_geoobj_elements_read_strips():
    data = build_geoobj()
    assert ubi_geoobj.is_geoobj(data[:16], len(data))
    ms = ubi_geoobj.models(data)
    assert len(ms) == 2 and len(ms[0].elements) == 1
    e = ms[0].elements[0]
    assert e.name == "box/box.gmt^GameMaterial:lid" and e.indices.reshape(-1, 3).shape == (2, 3)
    assert np.allclose(e.normals[0], (0, 1, 0)) and np.allclose(e.uvs[2], (1, 1))
    assert geo_plugin.detect("3d/gli/geoobj.bin", data[:16], len(data))
    scenes = geo_plugin.extract(data, "3d/gli/geoobj.bin", None)
    assert [s.name for s in scenes] == ["box", "box_2"]
    assert scenes[0].materials[0].name == "lid"


def build_tsd(kind, width=8, height=8):
    head = struct.pack(">3I", 0, 1, 1) + b"D:\\src\\pic.tga\0".ljust(256, b"\0")
    head += struct.pack(">3I", width, height, kind) + bytes(20)
    assert len(head) == ubi_geoobj.TSD_HEADER
    if kind == ubi_geoobj.TSD_RGBA8:
        px = bytes([10, 20, 30, 255]) * (width * height)
    elif kind == ubi_geoobj.TSD_DXT1:
        px = (struct.pack("<2H", 0xF800, 0xF800) + bytes(4)) * (width * height // 16)
    else:
        px = (
            bytes([0x10] * (width * height // 2))
            + bytes(4)
            + struct.pack("<16H", *([0xF800, 0x07E0] + [0] * 14))
        )
    data = head + px
    return struct.pack(">I", len(data)) + data[4:]


def test_tsd_pictures_decode_in_pc_layouts():
    rgba = ubi_geoobj.tsd(build_tsd(ubi_geoobj.TSD_RGBA8))
    assert rgba.shape == (8, 8, 4) and rgba[0, 0].tolist() == [10, 20, 30, 255]
    red = ubi_geoobj.tsd(build_tsd(ubi_geoobj.TSD_DXT1))
    assert red[3, 3, 0] > 200 and red[3, 3, 1] < 20
    c4 = ubi_geoobj.tsd(build_tsd(0x07))
    assert c4[0, 0].tolist() == [255, 0, 0, 255] and c4[0, 1].tolist() == [0, 255, 0, 255]
    assert ubi_geoobj.tsd(bytes(400)) is None
