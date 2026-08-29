"""Hudson HSF models and Mario Party .bin archives."""

import struct

import numpy as np

from gcrip.formats import hsf, mpbin
from gcrip.plugins import hsf as plug
from gcrip.plugins import mpbin as bin_plug


def build_hsf() -> bytes:
    """Root + one mesh object: a quad (type 3) with 4 positions, one material/texture."""
    d = bytearray(0x1000)
    d[:8] = b"HSFV037\0"
    names = b"root\0quad\0mat\0att\0tex\0"
    strings = 0xE00
    d[strings : strings + len(names)] = names

    def section(name: str, off: int, count: int) -> None:
        i = hsf._SECTIONS.index(name)
        struct.pack_into(">2I", d, 8 + i * 8, off, count)

    struct.pack_into(">2I", d, 0xA8, strings, len(names))
    # material (0x3c): texture count 1, first symbol 0 -> symbols[0] = attribute 0
    section("material", 0x100, 1)
    struct.pack_into(">I", d, 0x100, 10)
    struct.pack_into(">2i", d, 0x100 + 0x34, 1, 0)
    section("symbol", 0x140, 1)
    struct.pack_into(">i", d, 0x140, 0)
    section("attribute", 0x150, 1)
    struct.pack_into(">I", d, 0x150, 14)
    struct.pack_into(">i", d, 0x150 + 0x80, 0)
    # positions: one component of 4
    section("position", 0x200, 1)
    struct.pack_into(">3I", d, 0x200, 5, 4, 0)
    for i, (x, y) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        struct.pack_into(">3f", d, 0x20C + i * 12, x, y, 0)
    section("texcoord", 0x260, 1)
    struct.pack_into(">3I", d, 0x260, 5, 4, 0)
    for i, (x, y) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        struct.pack_into(">2f", d, 0x26C + i * 8, x, y)
    # faces: one component, one quad primitive
    section("face", 0x300, 1)
    struct.pack_into(">3I", d, 0x300, 5, 1, 0)
    p = 0x30C
    struct.pack_into(">2H", d, p, 3, 0x8000)
    for i in range(4):
        struct.pack_into(">4h", d, p + 4 + i * 8, i, -1, -1, i)
    # objects: root (type 3) and mesh (type 2, parent 0)
    section("object", 0x400, 2)
    for i, (name_off, typ, parent) in enumerate(((0, 3, -1), (5, 2, 0))):
        o = 0x400 + i * hsf.OBJECT_SIZE
        struct.pack_into(">I6i", d, o, name_off, typ, 0, 0, parent, 0, 0)
        struct.pack_into(">9f", d, o + 0x1C, 0, 0, 0, 0, 0, 0, 1, 1, 1)
        struct.pack_into(">8i", d, o + 0x100, -1, 0, 0, -1, -1, 0, 0, 0)
        struct.pack_into(">2i", d, o + 0x134, 0, -1)
    # texture: 8x8 CMPR (format 7), data right after the table
    section("texture", 0x700, 1)
    struct.pack_into(">IIBBHHHIiII", d, 0x700, 19, 1, 7, 4, 8, 8, 0, 0, -1, 0, 0)
    d[0x720 : 0x720 + 32] = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0, 0]) * 4
    return bytes(d)


def test_hsf_mesh_and_texture():
    data = build_hsf()
    m = hsf.parse(data)
    assert [o.name for o in m.objects] == ["root", "quad"]
    out = hsf.meshes(m)
    assert len(out) == 1 and len(out[0].indices) == 6 and out[0].positions.shape == (4, 3)
    assert np.allclose(out[0].uvs[:, 0], [0, 1, 1, 0])
    assert hsf.material_texture(m, 0) == 0 and m.textures[0].rgba.shape == (8, 8, 4)
    scenes = plug.extract(data, "x/000.hsf", None)
    assert len(scenes) == 1 and scenes[0].triangles == 2 and scenes[0].materials[0].texture


def test_mpbin_lzss():
    payload = build_hsf()
    # LZSS stream of literals only: flag byte 0xff then 8 literal bytes
    packed = bytearray()
    for i in range(0, len(payload), 8):
        packed.append(0xFF)
        packed += payload[i : i + 8]
    stored = b"\0\0\0\x10" + bytes(12)
    members = [(1, bytes(packed), len(payload)), (0, stored, len(stored))]
    offs = []
    body = bytearray()
    base = 4 + 4 * len(members)
    for comp, blob, size in members:
        offs.append(base + len(body))
        body += struct.pack(">2I", size, comp) + blob
    data = struct.pack(">I", len(members)) + struct.pack(f">{len(members)}I", *offs) + bytes(body)
    assert mpbin.is_mpbin(data[:16], len(data))
    ms = mpbin.members(data)
    assert [(m.compression, m.size) for m in ms] == [(1, len(payload)), (0, len(stored))]
    assert mpbin.read(data, ms[0]) == payload and mpbin.read(data, ms[1]) == stored
    assert bin_plug.is_container("files/data/mario.bin", data[:64])
    assert [n for n, _ in bin_plug.expand(data)] == ["000.hsf", "001.dat"]
