"""Next Level Games GL (Super Mario Strikers): .glg chunk units with packets, streams and
placement matrices; .glt PTLG bundles; the plugin binding textures by hash."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import nlg_gl
from gcrip.plugins import nlg_glg


def chunk(cid: int, body: bytes) -> bytes:
    return struct.pack(">II", cid, len(body)) + body


def glg(psize: int = 74, s16: bool = False, level: bool = False) -> bytes:
    """One model, one packet: a quad strip over four vertices, placed by a translation."""
    if s16:
        pos = np.array([[0, 0, 0], [256, 0, 0], [0, 256, 0], [256, 256, 0]], ">i2").tobytes()
    else:
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], ">f4").tobytes()
    nrm = bytes([0, 0, 64] * 4)
    clr = bytes([255, 0, 0, 255] * 4)
    uv = np.array([[0, 0], [1024, 0], [0, 1024], [1024, 1024]], ">i2").tobytes()
    vdata = pos + nrm + clr + uv
    streams = struct.pack(">IBB", 0, 0, 6 if s16 else 12)
    streams += struct.pack(">IBB", len(pos), 1, 3)
    streams += struct.pack(">IBB", len(pos) + len(nrm), 2, 4)
    streams += struct.pack(">IBB", len(pos) + len(nrm) + len(clr), 3, 4)
    indices = struct.pack(">4H", 0, 1, 2, 3)
    matrix = np.eye(4, dtype=">f4")
    matrix[3, :3] = (10, 20, 30)
    state = bytearray(psize - 20)
    struct.pack_into(">I", state, 0x14, 0)  # matrix offset
    struct.pack_into(">I", state, 0x18, 0xCAFEF00D)  # texture hash
    packet = struct.pack(">IIHBBI", 0, 0, 4, 1, 4, 0) + bytes(state) + struct.pack(">I", 0)
    assert len(packet) == psize
    model = struct.pack(">4I", 1, 0xAB12CD34, 0, 0)
    body = chunk(0x1B001, struct.pack(">HH", 2, 2)) + chunk(0x1B002, matrix.tobytes())
    body += chunk(0x1B003, model) + chunk(0x1B004, packet) + chunk(0x1B005, streams)
    body += chunk(0x1B006, vdata) + chunk(0x1B007, indices)
    unit = chunk(0x8001B000, body)
    return chunk(0x8001B100, unit) if level else unit


def glt(hashes: list[int], table: int = 0x20) -> bytes:
    """A PTLG bundle of 4x4 RGB565 textures, pixel (0,0) green and the rest red."""
    pixels = struct.pack(">16H", 0x07E0, *([0xF800] * 15))
    hdr = struct.pack(">III", 1, 0, 0) + bytes([0, 0]) + struct.pack(">HH", 4, 4)
    hdr += b"\0\0" + struct.pack(">I", 0) + b"\0" * 8
    tex = hdr + pixels
    entries = b"".join(
        struct.pack(">4I", h, i * len(tex), len(tex), 0) for i, h in enumerate(hashes)
    )
    head = b"PTLG" + struct.pack(">I", len(hashes))
    return head.ljust(table, b"\0") + entries + tex * len(hashes)


class FakeSrc:
    def __init__(self, files):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, path):
        return self.files[path]


def test_glg_packets_streams_and_matrix():
    for psize, s16, level in ((74, False, False), (70, True, True)):
        data = glg(psize, s16, level)
        assert nlg_gl.is_glg(data[:64], len(data))
        warn: list[str] = []
        models = nlg_gl.parse_glg(data, warn)
        assert warn == [] and [m.id for m in models] == [0xAB12CD34]
        (pk,) = models[0].packets
        np.testing.assert_allclose(
            pk.positions[:4], [[10, 20, 30], [11, 20, 30], [10, 21, 30], [11, 21, 30]]
        )
        assert len(pk.triangles) == 2
        np.testing.assert_allclose(pk.normals[0], [0, 0, 1])
        assert pk.colors[0].tolist() == [255, 0, 0, 255]
        np.testing.assert_allclose(pk.uvs[3], [1, 1])
        assert pk.texture == 0xCAFEF00D


def test_glt_bundle_both_table_offsets():
    for table in (0x20, 0x10):
        data = glt([0xCAFEF00D, 0x11], table)
        assert nlg_gl.is_glt(data[:16])
        entries = nlg_gl.glt_entries(data)
        assert set(entries) == {0xCAFEF00D, 0x11}
        img = nlg_gl.decode_glt_texture(data, *entries[0x11])
        assert img.shape == (4, 4, 4) and tuple(img[0, 0]) == (0, 255, 0, 255)
        assert tuple(img[3, 3]) == (255, 0, 0, 255)


def test_plugin_binds_the_sibling_bundle():
    files = {
        "files/art/characters/Mario/Mario.glg": glg(),
        "files/art/characters/Mario/Mario.glt": glt([0xCAFEF00D]),
        "files/art/global.glt": glt([0x22]),
    }
    src = FakeSrc(files)
    path = "files/art/characters/Mario/Mario.glg"
    assert nlg_glg.detect(path, files[path][:64], len(files[path]))
    assert not nlg_glg.detect("files/art/global.glt", files["files/art/global.glt"][:64], 100)
    (sc,) = nlg_glg.extract(files[path], path, src)
    assert sc.name == "Mario" and sc.warnings == []
    assert sc.materials[0].texture == "cafef00d" and "cafef00d" in sc.textures
    assert sc.extras["models"] == ["ab12cd34"]
