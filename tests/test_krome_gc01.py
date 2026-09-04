"""Krome GC01 models (Jimmy Neutron: Jet Fusion .mdl + .mdg), gcrip.formats.krome_gc01."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import krome_gc01
from gcrip.plugins import krome_gc01 as plugin


def vertex(x, y, z, u=0.0, v=0.0) -> bytes:
    return (
        struct.pack(">3f", x, y, z)
        + struct.pack(">3b", 0, 0, 64)
        + struct.pack(">H", 0xF0FF)  # RGBA4: r=15, g=0, b=15, a=15
        + struct.pack(">2h", round(u * 4096), round(v * 4096))
        + bytes(3)
    )


def make_pair():
    quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    strip = b"\x98" + struct.pack(">H", 4) + b"".join(vertex(*q, u=q[0], v=q[1]) for q in quad)
    mdg = strip + bytes(-len(strip) % 16)
    names = b"\0m_body\0CM_ROCK\0"
    mdl = bytearray(b"GC01" + struct.pack(">HhhH", 1, 1, 1, 0) + struct.pack(">3I", 0x50, 0xA0, 0))
    mdl += bytes(0x50 - len(mdl))
    # 0x50: the subobject; 0xa0: the refpoint; 0xc0: the material; 0xd0: the names
    sub = bytearray(0x50)
    struct.pack_into(">7f", sub, 0, -1, -1, -1, 1.7, 1, 1, 1)
    struct.pack_into(">I", sub, 0x30, 0xD0 + 1)
    struct.pack_into(">h", sub, 0x42, 1)
    struct.pack_into(">I", sub, 0x44, 0xC0)
    mdl += sub
    ref = bytearray(0x20)
    struct.pack_into(">I", ref, 16, 0xD0 + 8)  # "CM_ROCK" doubles as the refpoint name here
    mdl += ref
    mdl += struct.pack(">IIHHI", 0xD0 + 8, 0, len(mdg) >> 4, 0, 1)
    mdl += names
    return bytes(mdl), mdg


def test_a_strip_of_twenty_four_byte_vertices_decodes():
    mdl, mdg = make_pair()
    assert krome_gc01.is_gc01(mdl[:16])
    m = krome_gc01.parse(mdl, mdg)
    assert m.warnings == [] and m.refpoints == ["CM_ROCK"]
    (part,) = m.parts
    assert part.subobject == "m_body" and part.material == "CM_ROCK"
    assert part.positions.tolist() == [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
    assert np.allclose(part.normals[0], [0, 0, 1])
    assert part.colors[0].tolist() == [255, 0, 255, 255]
    assert np.allclose(part.uvs[2], [1, 1], atol=1e-3)
    assert len(part.indices) == 6  # a strip of four is two triangles


def test_the_plugin_needs_the_mdg_and_binds_tex_by_name():
    mdl, mdg = make_pair()
    files = {
        "files/Data_GC.rkv/_PP_Files/rock.mdl": mdl,
        "files/Data_GC.rkv/_PP_Files/rock.mdg": mdg,
    }

    class Src:
        by_path = dict.fromkeys(files)

        def get(self, p):
            return files[p]

    path = "files/Data_GC.rkv/_PP_Files/rock.mdl"
    assert plugin.detect(path, mdl[:64], len(mdl))
    (scene,) = plugin.extract(mdl, path, Src())
    assert scene.materials[0].name == "CM_ROCK" and scene.materials[0].texture is None
    assert scene.extras["subobjects"] == ["m_body"]
    del files["files/Data_GC.rkv/_PP_Files/rock.mdg"]
    Src.by_path = dict.fromkeys(files)
    assert plugin.extract(mdl, path, Src()) == []
