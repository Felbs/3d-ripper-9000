"""Krome MDL3 (.mdl + .mdg) models."""

import struct

import numpy as np

from gcrip.formats import mdl3
from gcrip.plugins import mdl3 as plug


def build_pair(rigged: bool, pad: bytes = b"\0") -> tuple[bytes, bytes]:
    """One subobject, one texture, one block: a quad as a 4-vertex strip.

    *pad* fills the 32-byte alignment tail of the position section - the shipped
    archives leave junk there (NaN / 1e38 float patterns), not zeros.
    """
    # .mdg: magic + pad, block header at 0x20, sections
    dl = bytes([0x98, 0, 4])
    for i in range(4):
        dl += struct.pack(">HbbbHH", i, 0, 0, 127, 0, i)
    dl += bytes((-len(dl)) % 32)
    cols = bytes([255, 128, 0, 255]) + bytes(28)
    rec = 16 if rigged else 12
    pos = b""
    for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
        pos += struct.pack(">3f", x, y, 0)
        if rigged:
            pos += bytes([0, 1, 255, 0])
    pos += (pad * 32)[: (-len(pos)) % 32]
    uvs = b"".join(
        struct.pack(">2h", x * 4096, y * 4096) for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))
    )
    uvs += bytes((-len(uvs)) % 32)
    hdr = struct.pack(">8H", 4, 4, 0, 1, 0, 16 if rigged else 0, 0, 0)
    hdr += struct.pack(">4I", len(dl), len(cols), len(pos), len(uvs))
    mdg = b"MDG3" + bytes(28) + hdr + dl + cols + pos + uvs
    assert len(pos) // rec >= 4
    # .mdl
    nbone = 2 if rigged else 0
    names = b"quad\0Tex_A\0"
    sub_off, tex_off = 0x70, 0xB0
    blk_off = 0xC0
    bone_off = 0xD0 if rigged else 0
    name_off = (bone_off + nbone * 16) if rigged else 0xD0
    mdl = bytearray(name_off) + names
    mdl[:4] = b"MDL3"
    struct.pack_into(">6H", mdl, 4, 1, 1, nbone, 0, 0, 1)
    struct.pack_into(">8I", mdl, 0x50, sub_off, tex_off, 0xC0, bone_off, 0, 0, blk_off, 0)
    struct.pack_into(">I", mdl, sub_off + 48, name_off)
    struct.pack_into(">I", mdl, tex_off, name_off + 5)
    struct.pack_into(">I", mdl, blk_off, 0x20)
    if rigged:
        struct.pack_into(">8f", mdl, bone_off, 0, 0, 0, 0, 0, 1, 0, 0)
    return bytes(mdl), mdg


def test_mdl3_parse_rigged():
    mdl, mdg = build_pair(True)
    m = mdl3.parse(mdl, mdg, "quad")
    assert [(p.name, p.material) for p in m.parts] == [("quad", "Tex_A")]
    p = m.parts[0]
    assert len(p.indices) == 6 and p.positions.shape == (4, 3)
    assert np.allclose(p.uvs, [[0, 0], [1, 0], [0, 1], [1, 1]])
    assert np.allclose(p.normals[:, 2], 1.0)
    assert np.allclose(p.colors[0], [1.0, 128 / 255, 0.0, 1.0])
    assert m.bones.shape == (2, 3) and np.allclose(m.bones[1], [0, 1, 0])
    assert p.joints[0].tolist() == [0, 1, 0, 0] and np.allclose(p.weights[0], [1, 0, 0, 0])


def test_mdl3_parse_static():
    mdl, mdg = build_pair(False)
    m = mdl3.parse(mdl, mdg, "quad")
    assert len(m.parts) == 1 and len(m.bones) == 0 and m.parts[0].joints is None
    assert np.allclose(m.parts[0].positions[3], [1, 1, 0])


def test_mdl3_alignment_pad_is_not_vertices():
    """The Krome world-chunk bug: the position section is padded to 32 bytes and the
    shipped pad bytes are junk (NaN / huge-float patterns).  ``pos_size // rec`` used
    to read that pad as 1-2 extra vertices, blowing the bbox of ~2,000 world models
    (Ty2/Ty3/Spyro06/King Arthur).  Only max(index)+1 records are real."""
    mdl, mdg = build_pair(False, pad=b"\x7f\xc0\xff\xee")  # NaN-patterned junk
    m = mdl3.parse(mdl, mdg, "quad")
    p = m.parts[0]
    assert p.positions.shape == (4, 3)  # exactly the referenced records, no pad tail
    assert np.isfinite(p.positions).all()
    # rigged records (16 B) still parse whole, with the same pad rule
    mdl, mdg = build_pair(True, pad=b"\x7f\xc0\xff\xee")
    p = mdl3.parse(mdl, mdg, "quad").parts[0]
    assert p.positions.shape == (4, 3) and np.isfinite(p.positions).all()
    assert p.joints is not None


class Src:
    def __init__(self, mdg: bytes):
        self.mdg = mdg
        self.by_path = {"files/Data_GC.rkv/quad.mdl": None, "files/Data_GC.rkv/quad.mdg": None}

    def get(self, path):
        assert path.endswith("quad.mdg")
        return self.mdg


def test_mdl3_plugin():
    mdl, mdg = build_pair(True)
    assert plug.detect("files/Data_GC.rkv/quad.mdl", mdl[:64], len(mdl))
    scenes = plug.extract(mdl, "files/Data_GC.rkv/quad.mdl", Src(mdg))
    assert len(scenes) == 1 and scenes[0].triangles == 2 and len(scenes[0].joints) == 2
    assert scenes[0].materials[0].texture is None and scenes[0].extras["format"] == "mdl3"
