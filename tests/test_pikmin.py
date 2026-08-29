"""Pikmin 1 .mod parser and plugin on a synthetic model: one textured triangle rigidly bound
to a child joint, one envelope-weighted triangle, an untextured material, and a .txe."""

from __future__ import annotations

import math
import struct

import numpy as np

from gcrip.formats import pikmin_mod as pm
from gcrip.plugins import pikmin


def _chunk(cid: int, payload: bytes) -> bytes:
    body = payload + b"\0" * ((-(8 + len(payload))) % 0x20)
    return struct.pack(">II", cid, len(body)) + body


def _counted(cid: int, count: int, body: bytes) -> bytes:
    head = struct.pack(">I", count)
    head += b"\0" * ((-(8 + len(head))) % 0x20)
    return _chunk(cid, head + body)


def _material(
    flags: int, tex: int, colour: bytes, tev: int = 0, pvw_tex: int | None = None
) -> bytes:
    b = struct.pack(">Ii", flags, tex) + colour
    if flags & pm.MATFLAG_PVW:
        b += struct.pack(">i", tev)
        b += colour + struct.pack(">If", 0, 1.0) + struct.pack(">II", 0, 0)  # polygon colour
        b += struct.pack(">If", 1, 0.0)  # lighting
        b += struct.pack(">4I", 0, 0, 0, 0)  # pe
        b += struct.pack(">I3f", 0, 1, 1, 1)  # texture info: scale
        b += struct.pack(">I", 0)  # texgen count
        if pvw_tex is None:
            b += struct.pack(">I", 0)
        else:
            b += struct.pack(">I", 1)
            b += struct.pack(">i", pvw_tex) + b"\0" * 8 + struct.pack(">II", 0xFF, 0)
            b += struct.pack(">8f", *([1.0] * 8))
            b += struct.pack(">III", 0, 0, 0)
    return b


def _tev_info() -> bytes:
    b = b""
    for _ in range(3):
        b += struct.pack(">4h", 255, 255, 255, 255) + struct.pack(">If", 0, 1.0)
        b += struct.pack(">II", 0, 0)
    b += b"\xff" * 16 + struct.pack(">I", 1) + b"\0" * 32
    return b


def _display_list(flags: int, verts: list[tuple]) -> bytes:
    fields = pm.vertex_fields(flags)
    out = struct.pack(">BH", pm.PRIM_TRIANGLES, len(verts))
    for v in verts:
        for (_, t), val in zip(fields, v, strict=True):
            out += struct.pack(">B" if t == ">u1" else ">H", val)
    return out


def _disp_list_chunk(flags: int, faces: int, dl: bytes, at: int) -> bytes:
    """`at` = offset of this header inside the (32-aligned) mesh chunk body: the reader
    aligns to an absolute 32-byte boundary before the display-list bytes."""
    b = struct.pack(">III", flags, faces, len(dl))
    b += b"\0" * ((-(at + len(b))) % 0x20)
    return b + dl


def build_mod() -> bytes:
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], np.float32)
    nrm = np.array([[0, 0, 1], [0, 1, 0]], np.float32)
    uv = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    tex = pm.TexImg(8, 8, 0, 1, b"\xf8\x00" * 64)  # Pikmin format 0 = RGB565, red

    out = _chunk(pm.CHUNK_HEADER, b"\0" * 0x18 + struct.pack(">HBBI", 2001, 4, 5, 0))
    out += _counted(pm.CHUNK_POS, len(pos), pos.astype(">f4").tobytes())
    out += _counted(pm.CHUNK_NRM, len(nrm), nrm.astype(">f4").tobytes())
    out += _counted(pm.CHUNK_TEX0, len(uv), uv.astype(">f4").tobytes())
    texb = struct.pack(">HHII", tex.width, tex.height, tex.fmt, 1) + b"\0" * 16
    texb += struct.pack(">I", len(tex.data)) + tex.data
    out += _counted(pm.CHUNK_TEXTURE, 1, texb)
    out += _counted(pm.CHUNK_TEXATTR, 1, struct.pack(">HHHHf", 0, 0, pm.TILE_CLAMP_S, 0, 0.0))
    mats = _tev_info()
    mats += _material(pm.MATFLAG_PVW | pm.MATFLAG_OPAQUE, -1, bytes([255, 0, 0, 255]), 0, 0)
    mats += _material(pm.MATFLAG_ALPHA_BLEND, -1, bytes([0, 0, 255, 128]))
    out += _chunk(pm.CHUNK_MATERIAL, struct.pack(">II", 2, 1) + b"\0" * 0x10 + mats)
    # vertex matrices: 0 -> joint 1 (rigid), 1 -> envelope 0
    out += _counted(pm.CHUNK_VTXMTX, 2, struct.pack(">hh", 1, -1))
    out += _counted(pm.CHUNK_ENVELOPE, 1, struct.pack(">HHfHf", 2, 0, 0.25, 1, 0.75))
    flags = pm.MESH_PNMTX | pm.MESH_TEX0
    dl0 = _display_list(flags, [(0, 0, 0, 0), (0, 1, 0, 1), (0, 2, 0, 2)])
    # mesh: parent joint, flags, 1 group; group: 1 dep, 1 display list
    meshes = struct.pack(">iIIIhI", 1, flags, 1, 1, 0, 1)
    meshes += _disp_list_chunk(2, 1, dl0, len(meshes))
    dl1 = _display_list(pm.MESH_PNMTX, [(0, 3, 1), (0, 4, 1), (0, 5, 1)])
    meshes += struct.pack(">iIIIhI", 0, pm.MESH_PNMTX, 1, 1, 1, 1)
    meshes += _disp_list_chunk(0, 1, dl1, len(meshes))
    out += _counted(pm.CHUNK_MESH, 2, meshes)
    joints = struct.pack(">ii", -1, 0) + struct.pack(">7f", 0, 0, 0, 1, 1, 1, 1)
    joints += struct.pack(">9f", 1, 1, 1, 0, 0, 0, 0, 0, 0) + struct.pack(">I", 1)
    joints += struct.pack(">HH", 1, 1)
    joints += struct.pack(">ii", 0, 0) + struct.pack(">7f", 0, 0, 0, 1, 1, 1, 1)
    joints += struct.pack(">9f", 1, 1, 1, 0, 0, math.pi / 2, 10, 0, 0) + struct.pack(">I", 1)
    joints += struct.pack(">HH", 0, 0)
    out += _counted(pm.CHUNK_JOINT, 2, joints)
    names = b"".join(struct.pack(">I", len(n)) + n for n in (b"root", b"arm"))
    out += _counted(pm.CHUNK_JOINT_NAME, 2, names)
    out += _chunk(pm.CHUNK_END, b"")
    return out


def test_parse_round_trip():
    m = pm.parse(build_mod())
    assert m.date == (2001, 4, 5)
    assert len(m.positions) == 6 and len(m.normals) == 2 and len(m.texcoords[0]) == 3
    assert [t.fmt for t in m.textures] == [0]
    assert m.tex_attrs[0].tiling == pm.TILE_CLAMP_S
    assert [mat.flags for mat in m.materials] == [0x101, 0x400]
    assert m.materials[0].tex_attr == 0 and m.materials[1].tex_attr == -1
    assert m.materials[0].lighting_flags == 1
    assert m.vtx_matrices == [1, -1]
    assert m.envelopes == [[(0, 0.25), (1, 0.75)]]
    assert [x.parent_joint for x in m.meshes] == [1, 0]
    assert m.meshes[0].groups[0].deps == [0] and m.meshes[0].groups[0].lists[0].cull == 2
    assert [j.name for j in m.joints] == ["root", "arm"]
    assert m.joints[1].matpolys == [(0, 0)]
    prims = pm.parse_display_list(m.meshes[0].groups[0].lists[0].data, m.meshes[0].flags)
    assert len(prims) == 1 and list(prims[0][1]["pos"]) == [0, 1, 2]


def test_detect_and_scene():
    data = build_mod()
    assert pikmin.detect("dataDir/pikis/redModel.mod", data[:64], len(data))
    assert not pikmin.detect("dataDir/pikis/redModel.mod", b"\0" * 64, len(data))
    assert not pikmin.detect("thing.bin", data[:64], len(data))
    scenes = pikmin.extract(data, "dataDir/pikis/redModel.mod", None)
    assert len(scenes) == 1
    sc = scenes[0]
    assert sc.name == "redModel"
    assert [j.name for j in sc.joints] == ["root", "arm"]
    assert sc.joints[1].parent == 0
    # joint 1 rotated 90 deg about Z: quaternion (0,0,sin45,cos45)
    assert abs(sc.joints[1].rotation[2] - math.sqrt(0.5)) < 1e-6
    assert sc.materials[0].texture == "tex00" and sc.materials[0].clamp_u
    assert sc.materials[0].double_sided and not sc.materials[1].double_sided
    assert sc.materials[1].alpha_blend and sc.materials[1].base_color[2] == 1.0
    assert sc.textures["tex00"].shape == (8, 8, 4)
    assert tuple(sc.textures["tex00"][0, 0]) == (255, 0, 0, 255)
    assert len(sc.primitives) == 2
    # the joint-1 primitive was moved into bind space: rotated 90 deg about Z, +10 in X
    rigid = next(p for p in sc.primitives if p.material == 0)
    np.testing.assert_allclose(rigid.positions[0], [10, 0, 0], atol=1e-6)
    np.testing.assert_allclose(rigid.positions[1], [10, 1, 0], atol=1e-6)  # (1,0,0) -> (0,1,0)
    assert rigid.joints[0, 0] == 1 and rigid.weights[0, 0] == 1.0
    assert rigid.uvs is not None and rigid.uvs.shape == (3, 2)
    weighted = next(p for p in sc.primitives if p.material == 1)
    np.testing.assert_allclose(weighted.positions[0], [0, 0, 1], atol=1e-6)
    assert list(weighted.joints[0][:2]) == [0, 1]
    np.testing.assert_allclose(weighted.weights[0][:2], [0.25, 0.75])


def test_txe():
    data = struct.pack(">HHH", 8, 4, 0x0105) + b"\0" * 26 + b"\x0f" * 32
    tex, flags = pm.parse_txe(data)
    assert (tex.width, tex.height, tex.fmt, flags) == (8, 4, 5, 1)
    assert pm.looks_like_txe(data)
    assert not pm.looks_like_txe(b"\0" * 64)
    img = pm.decode_texture(tex)
    assert img.shape == (4, 8, 4) and tuple(img[0, 0]) == (255, 255, 255, 0)
