"""Radical Pure3D: LZR / P3DZ streams, RCF directories and a GameCube prim group."""

import struct

import numpy as np

from gcrip.formats import lzr, p3d, rcf
from gcrip.plugins import p3d as plug
from gcrip.plugins import rcf as rcf_plug


def test_lzr_stream():
    # literal run of 3 ("abc"), match of 6 at offset 3 -> "abcabcabc", literal "!"
    stream = bytes([0x03]) + b"abc" + bytes([0x36, 0x00]) + bytes([0x01]) + b"!"
    assert lzr.lzr(stream, 10) == b"abcabcabc!"
    # extended literal run: 0 then 3 -> 15 + 3 = 18 bytes
    stream = bytes([0x00, 0x03]) + b"P3D\xff" + bytes(14)
    assert lzr.lzr(stream, 18) == b"P3D\xff" + bytes(14)


def test_lzrf_stream():
    stream = bytes([0x03]) + b"abc" + bytes([0x86, 0x03]) + bytes([0x01]) + b"!"
    assert lzr.lzrf(stream, 10) == b"abcabcabc!"


def _chunk(cid: int, body: bytes, children: bytes = b"") -> bytes:
    head = struct.pack("<III", cid, 12 + len(body), 12 + len(body) + len(children))
    return head + body + children


def _pstr(s: str) -> bytes:
    return bytes([len(s)]) + s.encode()


def build_p3d() -> bytes:
    """One Mesh with a GameCube prim group: 4 positions (s16, 14 frac bits), 4 UVs
    (s16, 15 frac bits) and a 4-vertex strip with u8 indices."""
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], np.float64)
    vb = (pos * (1 << 14)).astype(">i2").tobytes()
    vb += (pos[:, :2] * 0.5 * (1 << 15)).astype(">i2").tobytes()
    desc = struct.pack("<HHIII", 3, 3, 36, 36, 0)
    desc += bytes([9, 2, 1, 3, 14, 6]) + struct.pack(">HI", 4, 24)
    desc += bytes([13, 2, 1, 2, 15, 4]) + struct.pack(">H", 4)
    dl = b"\x98\x00\x04" + bytes([0, 0, 1, 1, 2, 2, 3, 3])
    dl += bytes(-len(dl) % 32)

    def mem(cid, payload):
        return _chunk(cid, struct.pack("<HHII", 3, 3, len(payload), len(payload)) + payload)

    pg_body = struct.pack("<I", 0) + _pstr("quad_shader")
    pg_body += struct.pack("<IIIII", 1, 0x2001, 4, 0, 0)
    kids = _chunk(p3d.GX_DESC, desc) + mem(p3d.GX_VERTEX, vb) + mem(p3d.GX_INDEX, dl)
    pg = _chunk(p3d.PRIMGROUP, pg_body, kids)
    mesh = _chunk(p3d.MESH, _pstr("quad") + struct.pack("<II", 0, 1), pg)
    shader_body = _pstr("quad_shader") + _pstr("simple") + struct.pack("<IIII", 0, 0, 0, 1)
    tex_param = _chunk(p3d.SHADER_TEX_PARAM, b"TEX\0" + _pstr("quad.png"))
    shader = _chunk(p3d.SHADER, shader_body, tex_param)
    body = mesh + shader
    return b"P3D\xff" + struct.pack("<II", 12, 12 + len(body)) + body


def test_p3d_mesh_and_plugin():
    data = build_p3d()
    chunks = p3d.parse(data)
    meshes = p3d.meshes(chunks)
    assert len(meshes) == 1 and len(meshes[0].groups) == 1
    g = meshes[0].groups[0]
    assert g.positions.shape == (4, 3) and len(g.indices) == 6
    assert np.allclose(g.positions[3], [1, 1, 0]) and np.allclose(g.uvs[3], [0.5, 0.5])
    assert p3d.shader_textures(chunks) == {"quad_shader": "quad.png"}
    assert plug.detect("art/x.p3d", data[:64], len(data))
    scenes = plug.extract(data, "art/x.p3d", None)
    assert len(scenes) == 1 and len(scenes[0].primitives) == 1


def build_rcf(member: bytes) -> bytes:
    data = bytearray(0x2000)
    data[:22] = rcf.MAGIC_RADCORE
    struct.pack_into(">I", data, 0x24, 0x800)
    struct.pack_into(">IIII", data, 0x800, 1, 0x1000, 0x1000, 0)
    struct.pack_into(">III", data, 0x810, 0x12345678, 0x2000, len(member))
    name = b"art/quad.p3d\0"
    struct.pack_into("<II", data, 0x1000, 1, 0)
    struct.pack_into("<I", data, 0x1008, len(name))
    data[0x100C : 0x100C + len(name)] = name
    return bytes(data) + member


def test_rcf_container():
    member = build_p3d()
    data = build_rcf(member)
    assert rcf_plug.is_container("x.rcf", data[:64])
    out = rcf_plug.expand(data)
    assert out == [("art/quad.p3d", member)]
