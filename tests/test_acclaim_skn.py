"""Acclaim ``.SKN`` skinned characters (gcrip.formats.acclaim_skn).

The crack that settled the format: every geom is up to two MODEL-SPACE copies of the same
piece (nothing is bone-local - the runtime XF matrices are ``boneWorld x inverseBind``),
and the header tiles the file to the byte: ``0x4c + mats*32 + bones*32 + objects*76 +
geoms*52 + pad == size - sizeA - sizeB`` held on 17 of 17 disc samples.  The tests pin the
tiling, both display-list vertex layouts, the blended copy's ``uv == pos + verts`` rule,
the z-first blended normal, and the ``ff 00`` single-weight sentinel.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import acclaim_skn


def pad_to(raw: bytes, size: int) -> bytes:
    assert len(raw) <= size
    return raw + bytes(size - len(raw))


def build(placeholder: bool = False) -> bytes:
    """Two geoms: one with a rigid and a blended copy, one position-only (shadow).

    With ``placeholder=True`` the rigid copy's XF loads name bone 0xffff and its indices
    are garbage, the way the real files pad unused accessory slots.
    """
    # section A: uv pairs (3 rigid + 4 blended), rigid array, blended array, shadow array
    uv = b"".join(struct.pack(">2h", 512 * i, 1024) for i in range(7))  # 28 bytes @0
    rigid = b"".join(
        struct.pack(">6h", 256 * i, 0, -256, 16384, 0, 0) for i in range(3)
    )  # 36 bytes @28
    blended = b""
    for i in range(4):
        w = b"\xff\x00" if i < 2 else b"\x80\x7f"
        # position (i, 2, -1) * 256; normal +x stored z-first: (nz, nx, ny)
        blended += struct.pack(">6h", 256 * i, 512, -256, 0, 16384, 0) + w + b"\x7f\xe2"
    # 64 bytes @64
    shadow = b"".join(struct.pack(">3h", 256 * i, -512, 0) for i in range(3))  # 18 bytes @128
    section_a = uv + rigid + blended + shadow
    # section B: rigid dl @0, blended dl, shadow dl
    bone = 0xFFFF if placeholder else 1
    rigid_dl = struct.pack(">BHH", 0x20, bone, 0xB000) + struct.pack(">BHH", 0x28, bone, 0x8400)
    rigid_dl += bytes([0x98]) + struct.pack(">H", 3)
    for i in range(3):
        j = 0x4000 + i if placeholder else i
        rigid_dl += bytes([0]) + struct.pack(">3H", j, j, j)
    blend_dl = bytes([0x98]) + struct.pack(">H", 4)
    for i in range(4):
        blend_dl += struct.pack(">3H", i, i, i + 3)
    shadow_dl = struct.pack(">BHH", 0x20, 0, 0xB000) + bytes([0x98]) + struct.pack(">H", 3)
    for i in range(3):
        shadow_dl += bytes([0]) + struct.pack(">H", i) + bytes([0])
    section_b = rigid_dl + blend_dl + shadow_dl

    geoms = struct.pack(
        ">3I4H8i",
        0x10, len(rigid_dl), len(blend_dl), 3, 2, 2, 0,
        0, len(rigid_dl), 28, 64, -1, 0, -1, 0,
    )
    geoms += struct.pack(
        ">3I4H8i",
        0x10, len(shadow_dl), 0, 3, 0, 0, 0,
        len(rigid_dl) + len(blend_dl), -1, -1, -1, 128, -1, -1, 0,
    )
    objects = pad_to(b"body", 64) + struct.pack(">I2HI", 1, 0, 1, 0)
    objects += pad_to(b"head", 64) + struct.pack(">I2HI", 1, 1, 1, 0)
    head = pad_to(b"toy", 36)
    head += struct.pack(">4I", 1, 2, 2, 2)  # materials, bones, objects, geoms
    head += struct.pack(">5I", 0, 4, 0, 0, len(section_a))  # zero, tail pad, zeros, sizeA
    head += struct.pack(">I", len(section_b))
    head += pad_to(b"mat", 32)
    head += pad_to(b"ROOT", 32) + pad_to(b"HEAD", 32)
    return head + objects + geoms + bytes(4) + section_a + section_b


def test_header_and_names():
    data = build()
    assert acclaim_skn.is_skn(data[:0x4C], len(data))
    m = acclaim_skn.model(data)
    assert m.name == "toy"
    assert m.materials == ["mat"]
    assert m.bones == ["ROOT", "HEAD"]
    assert [(o.name, o.first_geom, o.geoms) for o in m.objects] == [("body", 0, 1), ("head", 1, 1)]
    assert len(m.geoms) == 2
    assert m.geom_object(0) == "body" and m.geom_object(1) == "head"
    assert m.geoms[0].material == 0
    assert m.geoms[0].blend_verts == 4


def test_tiling_gates_the_sniff():
    data = build()
    assert not acclaim_skn.is_skn(data[:0x4C], len(data) + 4)
    assert not acclaim_skn.is_skn(b"\x00" * 0x4C, 100)
    assert not acclaim_skn.is_skn(data[:0x20], len(data))
    with pytest.raises(acclaim_skn.SknError):
        acclaim_skn.model(data + bytes(4))


def test_sixty_four_byte_sniff():
    """The rip hands detect() only head[:64] - the structural check must carry it, and a
    real `.GDF` head must fail it (its material-name text sits where the zero words are)."""
    from tests.test_acclaim_gdf import build as build_gdf  # noqa: F401
    from tests.test_acclaim_gdf import strip_list

    data = build()
    assert acclaim_skn.is_skn(data[:64], len(data))
    gdf = build_gdf([("mesh0", 1, [(1.0, 2.0, 2.0)], strip_list([0, 0, 0], 1), 1)])
    assert not acclaim_skn.is_skn(gdf[:64], len(gdf))
    from gcrip.plugins import acclaim_skn as plug

    assert plug.detect("toy.SKN", data[:64], len(data))


def test_meshes_decode_model_space():
    data = build()
    m = acclaim_skn.model(data)
    got = acclaim_skn.meshes(data, m)
    assert [g.kind for g in got] == ["blended", "shadow"]
    blended, shadow = got
    # the blended copy wins over the rigid one; positions are s16 / 256 in model space
    assert blended.material == 0 and blended.object_name == "body"
    np.testing.assert_allclose(np.asarray(blended.positions)[:, 0], [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_allclose(np.asarray(blended.positions)[0], [0.0, 2.0, -1.0])
    # the z-first stored normal comes out as +x
    np.testing.assert_allclose(np.asarray(blended.normals)[0], [1.0, 0.0, 0.0])
    # blended uv index = pos + verts: rows 3..6 of the uv array
    want_u = [512 * (i + 3) / 4096.0 for i in range(4)]
    np.testing.assert_allclose(np.asarray(blended.uvs)[:, 0], want_u)
    assert len(blended.indices) == 2  # one 4-vertex strip
    assert shadow.normals is None and shadow.uvs is None
    np.testing.assert_allclose(np.asarray(shadow.positions)[1], [1.0, -2.0, 0.0])
    assert shadow.bones == [0, 0, 0]


def test_rigid_copy_reads_when_alone():
    data = build()
    m = acclaim_skn.model(data)
    g = m.geoms[0]
    verts, tris, ok, real = acclaim_skn.rigid_dl(data, m.b, m.b + g.dl_size)
    assert ok and real
    assert verts == [(1, 0), (1, 1), (1, 2)]  # bone 1 through the 0x20 load, unified indices
    assert tris == [(0, 1, 2)]


def test_placeholder_geoms_are_skipped():
    data = build(placeholder=True)
    m = acclaim_skn.model(data)
    got = acclaim_skn.meshes(data, m)
    # the rigid copy is garbage but the blended copy still reads; the shadow survives
    assert [g.kind for g in got] == ["blended", "shadow"]
    verts, _, ok, real = acclaim_skn.rigid_dl(data, m.b, m.b + m.geoms[0].dl_size)
    assert ok and not real


def test_identities_hold():
    data = build()
    for ident in acclaim_skn.IDENTITIES:
        held, detail = ident.check(data)
        assert held is True, f"{ident.name}: {detail}"


def test_identities_skip_placeholders():
    data = build(placeholder=True)
    for ident in acclaim_skn.IDENTITIES:
        held, detail = ident.check(data)
        assert held is not False, f"{ident.name}: {detail}"


def test_plugin_extracts_a_scene():
    from gcrip.plugins import acclaim_skn as plug

    data = build()
    assert plug.detect("DataGC/Anim/toy.SKN", data[:0x4C], len(data))
    assert not plug.detect("toy.bin", data[:0x4C], len(data))
    scenes = plug.extract(data, "DataGC/Anim/toy.SKN", None)
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene.name == "toy"
    assert [m.name for m in scene.materials] == ["mat"]
    assert len(scene.primitives) == 2
    assert scene.triangles == 3
    assert scene.extras["bones"] == ["ROOT", "HEAD"]
    assert scene.extras["objects"] == ["body", "head"]


def test_gdf_plugin_yields_the_skn():
    from gcrip.plugins import acclaim_gdf as gdf

    data = build()
    assert not gdf.detect("DataGC/Anim/toy.SKN", data[:0x4C], len(data))
