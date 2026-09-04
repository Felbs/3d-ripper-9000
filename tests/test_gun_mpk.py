"""Neversoft Gun .mpk.ngc map packs: array location by scene header + unit-normal
run, mesh signature scan, and display-list decode against the global arrays."""

import struct

import numpy as np

from gcrip.formats import gun_mpk
from gcrip.plugins import gun_mpk as plugin

QUAD = np.array(
    [[100.0, 0.0, 100.0], [200.0, 0.0, 100.0], [100.0, 0.0, 200.0], [200.0, 0.0, 200.0]],
    np.float32,
)
NPOS, NNRM, NCOL, NUV = 4, 600, 4, 4


def build_pack() -> bytes:
    out = bytearray()
    # asset header: one 8x8 CMPR image, end of chain
    out += b"\x04\x20\x00\x00" + bytes(6) + bytes([3, 3]) + bytes([0, 14, 0, 0])
    out += struct.pack(">III", 32, 32, 0xFFFFFFFF) + bytes(4)
    out += bytes(32)  # the image payload (8x8 CMPR)

    # scene header: 44 bytes ending where the aa ff ee ff marker starts
    out += struct.pack(">IIHH", NPOS, NNRM, NCOL, NUV) + bytes(32) + gun_mpk.MARKER
    out += bytes(-len(out) % 4)

    # global arrays: positions, 16 zero pad, colours, uvs, 2 pad, normals
    pos0 = len(out)
    out += QUAD.astype(">f4").tobytes()
    out += bytes(16)
    out += bytes([0x80, 0x80, 0x80, 0xFF]) * NCOL
    uv = np.array([[256, 256], [512, 256], [256, 512], [512, 512]], ">i2")
    out += uv.tobytes()
    out += bytes(2)
    nrm0 = len(out)
    out += np.array([[16384, 0, 0]] * NNRM, ">i2").tobytes()

    # one mesh: strip of 4 corners -> 2 triangles
    dl = bytearray()
    dl += bytes([0x08, 0x50]) + struct.pack(">I", 0x7E00)
    dl += bytes([0x08, 0x60]) + struct.pack(">I", 3)
    dl += bytes([0x10, 0x00, 0x00, 0x10, 0x08]) + struct.pack(">I", 0x15)
    dl += bytes([0x9F]) + struct.pack(">H", 4)
    for i in range(4):
        dl += struct.pack(">4H", i, i % NNRM, i % NCOL, i % NUV)  # pos nrm col tex
    dl += bytes(-len(dl) % 4)

    sphere = (150.0, 0.0, 150.0, 100.0)
    out += struct.pack(">I", len(dl))  # dl size          (sig-36)
    out += struct.pack(">I", 0xDEADBEEF)  # material      (sig-32)
    out += struct.pack(">I", 0x90000007)  # flags         (sig-28)
    out += struct.pack(">I", 0x12345678)  # mesh checksum (sig-24)
    out += struct.pack(">4f", *sphere)  # bounding sphere (sig-20)
    out += bytes(4)
    out += gun_mpk.MESH_SIG
    out += struct.pack(">HH", 4, 0x200)  # corner count, 0x200
    out += bytes(4)
    out += struct.pack(">I", len(dl))  # dl size again    (sig+12)
    out += struct.pack(">f", 0.0) + bytes(4) + struct.pack(">I", 0x4400)
    out += dl
    blob = bytes(out)
    assert blob.find(gun_mpk.MARKER) == blob.rfind(gun_mpk.MARKER)
    return blob, pos0, nrm0


def test_parse():
    data, pos0, nrm0 = build_pack()
    assert gun_mpk.is_mpk(data[:32])
    assert gun_mpk.scene_counts(data) == (NPOS, NNRM, NCOL, NUV)
    found = gun_mpk.find_normals(data)
    assert found is not None and found[0] == nrm0 and found[1] >= NNRM

    level = gun_mpk.parse(data)
    assert len(level.meshes) == 1
    assert level.rejected == 0
    np.testing.assert_array_equal(level.positions, QUAD)
    assert level.triangle_count == 2
    mesh = level.meshes[0]
    assert mesh.material == 0xDEADBEEF
    np.testing.assert_array_equal(mesh.corners["pos"], [0, 1, 2, 3])
    np.testing.assert_array_equal(mesh.triangles, [[0, 1, 2], [1, 3, 2]])
    np.testing.assert_allclose(level.uvs[1], [0.5, 0.25])
    np.testing.assert_allclose(level.normals[0], [1.0, 0.0, 0.0])


def test_prop_mesh_rejected():
    """A mesh whose indices land far outside its own bounding sphere (a prop
    with inline arrays) is skipped, not exported wrong."""
    data, _pos0, _nrm0 = build_pack()
    bad = bytearray(data)
    sig = data.rfind(gun_mpk.MESH_SIG)
    # move the sphere far away so the containment test fails
    bad[sig - 20 : sig - 4] = struct.pack(">4f", 90000.0, 0.0, 0.0, 5.0)
    try:
        gun_mpk.parse(bytes(bad))
        raise AssertionError("expected GunMpkError")
    except gun_mpk.GunMpkError:
        pass  # the only mesh was rejected


def test_plugin():
    data, _pos0, _nrm0 = build_pack()
    assert plugin.detect("gun/z_test.mpk.ngc", data[:64], len(data))
    assert not plugin.detect("gun/z_test.img.ngc", data[:64], len(data))
    assert not plugin.detect("gun/z_test.mpk.ngc", data[:64], 32)  # placeholder
    scenes = plugin.extract(data, "gun/z_test.mpk.ngc", None)
    assert len(scenes) == 1
    sc = scenes[0]
    assert sc.name == "z_test"
    assert sc.triangles == 2
    assert len(sc.materials) == 1
    assert sc.materials[0].name == "mat_deadbeef"
    prim = sc.primitives[0]
    np.testing.assert_array_equal(prim.positions, QUAD)
    assert prim.uvs is not None and prim.colors is not None and prim.normals is not None
    np.testing.assert_allclose(prim.colors[0], [0.5019608, 0.5019608, 0.5019608, 1.0], rtol=1e-5)
