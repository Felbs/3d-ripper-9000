"""Avalanche DBL model records: mesh (GX display list + arrays), CI4 texture, material list."""

import struct

import numpy as np

from gcrip.formats import dbl, dbl_mesh
from gcrip.plugins import dbl as plugin


def _block(rtype: int, kind: int, payload: bytes) -> bytes:
    hdr = struct.pack(">HHIH", rtype, kind, len(payload), 1) + b"1000\0\0" + bytes(0x30)
    return hdr + payload


def make_mesh(prefixed: bool = True) -> bytes:
    fifo = struct.pack(">BBI", 0x08, 0x50, 0x1400) + struct.pack(">BBI", 0x08, 0x60, 2)
    fifo += bytes([0x9B, 0, 3]) + bytes([0, 0, 0, 1, 1, 1, 2, 2, 2])
    fifo += bytes(-len(fifo) % 32)
    dl = struct.pack(">5IIHHHH", 0, 1, 0, 0x0102, 0, len(fifo), 3, 1, 0x6401, 0) + fifo
    head = struct.pack(">I", 0x13000160) + struct.pack(">11f", *([0.0] * 11))
    head += b"triShape".ljust(32, b"\0")
    table_len = 42 * 4
    dl_off = len(head) + table_len
    pos_off = dl_off + len(dl)
    nrm_off = pos_off + 3 * 12
    uv_off = nrm_off + 12
    positions = struct.pack(">9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    normals = struct.pack(">12b", 0, 64, 0, 0, 64, 0, 0, 64, 0, 0, 0, 0)
    uvs = struct.pack(">6f", 0, 0, 1, 0, 0, 1)
    words = [0] * 42
    words[0], words[1] = 3, pos_off
    words[8], words[9], words[10] = 3, 1, dl_off
    words[13], words[14] = 3, nrm_off
    words[15], words[16] = 3, uv_off
    words[19] = uv_off
    body = head + struct.pack(">42I", *words) + dl + positions + normals + uvs
    return (dbl_mesh.PREFIX if prefixed else b"") + body


def make_texture() -> bytes:
    pay = bytearray(0xA0)
    struct.pack_into(">I", pay, 0, 1)
    pay[0x18 : 0x18 + 16] = b"c:\\dev\\maps\\ball".ljust(16, b"\0")
    struct.pack_into(">I", pay, 0x38, 8)
    struct.pack_into(">I", pay, 0x44, 0xA0)
    struct.pack_into(">I", pay, 0x48, (8 << 16) | 8)
    pay[0x60 : 0x60 + 13] = b"maps\\ball.tga"
    palette = struct.pack(">16H", *([0x8000 | (31 << 10)] * 16))  # opaque red
    pay[0x80:0xA0] = palette
    return bytes(pay) + bytes(32)


def make_material() -> bytes:
    return (
        b"\0\2\0\1"
        + b"\0\0\0\x0c"
        + b"\0\0\0\x14"
        + b"\xff" * 4
        + bytes(10)
        + b"ball.tga".ljust(40, b"\0")
    )


def make_dbl() -> bytes:
    head = b"0\0\0\0" + bytes(4) + b"GCN\0" + bytes(0x40 - 12)
    return (
        head
        + _block(0x82, 0xE, make_texture())
        + _block(0x67, 0xE, make_material())
        + _block(0x23, 0xE, make_mesh())
    )


def test_parse_mesh_record():
    rec = dbl_mesh.parse(make_mesh())
    assert rec is not None and rec.name == "triShape" and len(rec.meshes) == 1
    m = rec.meshes[0]
    assert m.material == 1 and m.bones == (1, 2) and m.tris == 1
    assert m.indices.tolist() == [0, 1, 2]
    np.testing.assert_allclose(m.positions, [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    np.testing.assert_allclose(m.normals, [[0, 1, 0]] * 3)
    np.testing.assert_allclose(m.uvs, [[0, 0], [1, 0], [0, 1]])


def test_unprefixed_record_is_normalised():
    rec = dbl_mesh.parse(make_mesh(prefixed=False))
    assert rec is not None and len(rec.meshes) == 1


def test_texture_and_material_records():
    t = dbl_mesh.texture(make_texture())
    assert t is not None and t.name == "ball" and t.rgba.shape == (8, 8, 4)
    assert tuple(t.rgba[0, 0]) == (255, 0, 0, 255)
    assert dbl_mesh.material_names(make_material()) == ["ball.tga"]


def test_plugin_binds_texture_by_material_name():
    data = make_dbl()
    assert dbl.is_dbl("hero.dbl", data[:64])
    assert plugin.detect("files/hero.dbl", data[:64], len(data))
    scenes = plugin.extract(data, "files/hero.dbl", None)
    assert len(scenes) == 1
    s = scenes[0]
    assert s.name == "triShape" and len(s.primitives) == 1
    assert s.materials[0].texture == "ball" and "ball" in s.textures
    assert s.extras["display_lists"] == 1 and s.extras["bones"] == 2
