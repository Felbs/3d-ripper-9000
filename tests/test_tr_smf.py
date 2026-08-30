"""Terminal Reality _smf static meshes (Blowout version 7, BloodRayne version 4)."""

import struct

import numpy as np

from gcrip.formats import tr_smf
from gcrip.plugins import tr_smf as plugin


def vertex(pos, normal, uv) -> bytes:
    return (
        struct.pack(">3h", *pos)
        + bytes(np.array(normal, np.int8).tobytes())
        + struct.pack(">2h", *uv)
    )


def build(verts, materials=("wall.tif",), version: int = 7) -> bytes:
    head = bytearray(tr_smf.LAYOUTS[7].materials_at + len(materials) * tr_smf.MATERIAL_RECORD)
    struct.pack_into("<2I", head, 0, version, len(materials))
    for i, name in enumerate(materials):
        at = tr_smf.LAYOUTS[7].materials_at + i * tr_smf.MATERIAL_RECORD
        head[at : at + len(name)] = name.encode()
    body = tr_smf.SIGNATURE + b"\x00\x00" + bytes([0x84]) + struct.pack(">H", len(verts))
    return bytes(head) + body + b"".join(vertex(*v) for v in verts)


# a unit quad in the XY plane, normals pointing at +Z, wound counter-clockwise
QUAD = [
    ((0, 0, 0), (0, 0, 127), (0, 0)),
    ((256, 0, 0), (0, 0, 127), (256, 0)),
    ((256, 256, 0), (0, 0, 127), (256, 256)),
    ((0, 256, 0), (0, 0, 127), (0, 256)),
]


def test_quad_list_becomes_two_triangles():
    parsed = tr_smf.parse(build(QUAD))
    assert parsed.version == 7
    assert parsed.materials == ["wall.tif"]
    assert len(parsed.meshes) == 1
    mesh = parsed.meshes[0]
    assert len(mesh.indices) == 6
    # positions are s16 * 2^-8, so 256 is exactly 1.0
    assert mesh.positions.max() == 1.0
    assert mesh.uvs.max() == 1.0
    assert np.allclose(mesh.normals[0], [0, 0, 127 / 128])


def test_winding_follows_the_stored_normals():
    # the same quad wound the other way must still come out facing +Z
    parsed = tr_smf.parse(build(QUAD[::-1]))
    mesh = parsed.meshes[0]
    p = mesh.positions[mesh.indices].reshape(-1, 3, 3)
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    assert (face[:, 2] > 0).all()


def test_degenerate_triangles_are_dropped():
    # a quad that repeats a vertex is how the engine writes a single triangle
    tri = [QUAD[0], QUAD[1], QUAD[2], QUAD[2]]
    mesh = tr_smf.parse(build(tri)).meshes[0]
    assert len(mesh.indices) == 3


def build_v4(verts, name: str = "BULLET.tif") -> bytes:
    lay = tr_smf.LAYOUTS[4]
    head = bytearray(lay.materials_at + tr_smf.NAME_MAX)
    struct.pack_into("<2I", head, 0, 4, 3)
    head[lay.materials_at : lay.materials_at + len(name)] = name.encode()
    body = tr_smf.SIGNATURE + bytes([0x84]) + struct.pack(">H", len(verts))
    rows = b"".join(
        struct.pack(">3h", *p) + struct.pack(">3h", *n) + struct.pack(">2H", *uv)
        for p, n, uv in verts
    )
    return bytes(head) + body + rows


def test_version_4_uses_a_wider_vertex():
    # 32768 is 1.0 at 2^-15, and 16384 is 1.0 for a Q1.14 normal
    quad = [
        ((0, 0, 0), (0, 0, 16384), (0, 0)),
        ((32768 - 1, 0, 0), (0, 0, 16384), (256, 0)),
        ((32768 - 1, 32768 - 1, 0), (0, 0, 16384), (256, 256)),
        ((0, 32768 - 1, 0), (0, 0, 16384), (0, 256)),
    ]
    parsed = tr_smf.parse(build_v4(quad))
    assert parsed.version == 4
    assert parsed.materials == ["BULLET.tif"]
    mesh = parsed.meshes[0]
    assert len(mesh.indices) == 6
    assert abs(mesh.positions.max() - 1.0) < 1e-3
    assert abs(mesh.normals[0][2] - 1.0) < 1e-3  # Q1.14, not /128
    assert abs(mesh.uvs.max() - 1.0) < 1e-3


def test_layouts_differ_by_version():
    assert tr_smf.LAYOUTS[7].stride == 13
    assert tr_smf.LAYOUTS[4].stride == 16
    assert tr_smf.LAYOUTS[4].normal_16 and not tr_smf.LAYOUTS[7].normal_16


def test_rejects_other_versions_and_junk():
    assert not tr_smf.is_smf(struct.pack("<2I", 5, 3) + bytes(64))  # no version 5 seen
    assert not tr_smf.is_smf(struct.pack("<2I", 7, 0) + bytes(64))  # zero materials
    assert not tr_smf.is_smf(b"short")
    assert tr_smf.parse(b"short") is None
    assert tr_smf.materials(b"short") == []


def test_a_preamble_in_padding_is_not_a_mesh():
    # version 4 pads with F00DBAAD, which contains the preamble; only a real opcode counts
    junk = build(QUAD)[: tr_smf.LAYOUTS[7].materials_at + tr_smf.MATERIAL_RECORD]
    junk += tr_smf.SIGNATURE + bytes([0x00, 0x00, 0x04, 0x00])
    assert tr_smf.parse(junk).meshes == []


def test_plugin_binds_the_texture_and_reports_ambiguity():
    scenes = plugin.extract(build(QUAD), "WEAP.SMF", None)
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene.name == "WEAP"
    assert scene.materials[0].texture == "wall"
    assert scene.triangles == 2
    assert not scene.warnings
    # repeated records naming one texture still bind; genuinely different ones do not
    assert plugin.extract(build(QUAD, ("a.tif", "a.tif")), "X.SMF", None)[0].materials[0].texture
    mixed = plugin.extract(build(QUAD, ("a.tif", "b.tif")), "X.SMF", None)[0]
    assert mixed.materials[0].texture is None
    assert mixed.warnings
    assert plugin.detect("X.SMF", build(QUAD)[:64], 4096) is True
    assert plugin.detect("X.TEX", build(QUAD)[:64], 4096) is False
    assert plugin.extract(b"short", "X.SMF", None) == []
