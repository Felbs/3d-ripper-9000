"""Traveller's Tales NU2 vertex streams."""

import struct

import numpy as np

from gcrip.formats import nu2
from gcrip.plugins import nu2 as plug


def build_gsc() -> bytes:
    """NU20 header + one 4-vertex strip block with UV/normal and colour blocks."""
    d = bytearray(b"NU20" + struct.pack("<I", 0) + bytes(8))
    d += b"\x03\x01\x00\x01" + bytes([0x03, 0x80, 4, 0x6C])
    for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
        d += struct.pack("<4f", x, y, 0, 1.0)  # nz = 1
    d += b"\x01\x00\x00\x05" + bytes([0x04, 0x80, 4, 0x6D])
    for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
        d += struct.pack("<4h", x * 4096, y * 4096, 0, 0)
    d += b"\x00\x00\x00\x05" + bytes([0x05, 0xC0, 4, 0x6E]) + bytes([255, 128, 0, 255]) * 4
    d += b"\x01\x01\x00\x01\x00\x03\x00\x14"
    return bytes(d)


def test_nu2_meshes():
    d = build_gsc()
    ms = nu2.meshes(d)
    assert len(ms) == 1
    m = ms[0]
    assert m.positions.shape == (4, 3) and len(m.indices) == 6
    assert np.allclose(m.uvs, [[0, 0], [1, 0], [0, 1], [1, 1]])
    assert np.allclose(m.normals[:, 2], 1.0)
    assert np.allclose(m.colors[0], [1.0, 128 / 255, 0.0, 1.0])
    assert plug.detect("files/x.gsc", d[:64], len(d))
    scenes = plug.extract(d, "files/x.gsc", None)
    assert len(scenes) == 1 and scenes[0].triangles == 2
