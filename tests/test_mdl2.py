"""Krome MDL2 (.gmd) models and .gtx textures."""

import struct

import numpy as np

from gcrip.formats import mdl2
from gcrip.plugins import mdl2 as plug


def build_gmd() -> bytes:
    """One subobject, one mesh: a quad as a 4-vertex strip, two bones."""
    hdr = bytearray(0x40)
    hdr[:4] = b"MDL2"
    names = b"quad" + bytes(1) + b"Tex_A" + bytes(1)
    name_off = 0x40
    sub_off = name_off + len(names)
    sub_off += (-sub_off) % 16
    mesh_off = sub_off + 80
    dl_off = mesh_off + 16
    dl = bytes([0x98, 0, 4])
    for i in range(4):
        dl += struct.pack(">4H", i, i, i, i)
    dl += bytes((-len(dl)) % 16)
    bone_off = dl_off + len(dl)
    vert_off = bone_off + 32
    struct.pack_into(">4H", hdr, 4, 1, 1, 0, 2)
    struct.pack_into(">4I", hdr, 12, sub_off, 0, bone_off, vert_off)
    struct.pack_into(">I", hdr, 0x1C, 4)
    sub = bytearray(80)
    struct.pack_into(">I", sub, 48, name_off)
    struct.pack_into(">H", sub, 66, 1)
    struct.pack_into(">I", sub, 68, mesh_off)
    mesh = struct.pack(">4I", name_off + 5, dl_off, (len(dl) // 16) << 16, 1)
    bones = struct.pack(">8f", 0, 0, 0, 0, 0, 1, 0, 0)
    verts = b""
    for i, (x, y) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
        w = 4096 if i < 2 else 0
        verts += struct.pack(">3f3bB2h", x, y, 0, 0, 0, 127, 0, x * 4096, y * 4096)
        verts += struct.pack(">h2b4B", w, 0, 1, 255, 128, 0, 255)
    d = bytes(hdr) + names
    d += bytes(sub_off - len(d)) + bytes(sub) + mesh + dl + bones + verts
    return d


def test_mdl2_parse():
    m = mdl2.parse(build_gmd(), "quad")
    assert [p.name for p in m.parts] == ["quad"] and m.parts[0].material == "Tex_A"
    p = m.parts[0]
    assert len(p.indices) == 6 and p.positions.shape == (4, 3)
    assert np.allclose(p.uvs, [[0, 0], [1, 0], [0, 1], [1, 1]])
    assert np.allclose(p.normals[:, 2], 1.0)
    assert m.bones.shape == (2, 3) and np.allclose(m.bones[1], [0, 1, 0])
    assert np.allclose(p.weights[:, 0], [1, 1, 0, 0]) and p.joints[0].tolist() == [0, 1, 0, 0]


def build_gtx() -> bytes:
    hdr = struct.pack(">3I", 0, 8, 8) + bytes(0x14)
    return hdr + struct.pack(">64H", *([0xFFFF] * 64))  # RGB5A3: opaque white


class Src:
    def __init__(self):
        self.by_path = {"files/Data_GC.rkv/Tex_A.gtx": None, "files/Data_GC.rkv/quad.gmd": None}

    def get(self, path):
        assert path.endswith("Tex_A.gtx")
        return build_gtx()


def test_mdl2_plugin():
    data = build_gmd()
    assert plug.detect("files/Data_GC.rkv/quad.gmd", data[:64], len(data))
    scenes = plug.extract(data, "files/Data_GC.rkv/quad.gmd", Src())
    assert len(scenes) == 1 and scenes[0].triangles == 2
    sc = scenes[0]
    assert sc.materials[0].texture == "tex_a" and sc.textures["tex_a"].shape == (8, 8, 4)
    assert int(sc.textures["tex_a"][0, 0, 0]) == 255 and len(sc.joints) == 2
    assert not sc.materials[0].alpha_blend
