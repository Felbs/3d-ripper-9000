"""Luigi's Mansion .mdl / .bin parsers and plugin on synthetic models."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import lm_bin, lm_mdl
from gcrip.plugins import lm


def _inv_bind(tx: float, ty: float, tz: float) -> bytes:
    """3x4 inverse bind matrix of a pure translation (tx, ty, tz)."""
    return struct.pack(">12f", 1, 0, 0, -tx, 0, 1, 0, -ty, 0, 0, 1, -tz)


def build_mdl() -> bytes:
    """Two joints (root, child at +10 x).  Shape 0: a triangle rigid on joint 1 (stored in
    joint space), shape 1: a triangle on weight entry 0 (bind space, 0.25/0.75)."""
    positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [5, 5, 5], [6, 5, 5], [5, 6, 5]], ">f4")
    normals = np.array([[0, 0, 1]], ">f4")
    texcoords = np.array([[0, 0], [1, 0], [0, 1]], ">f4")
    out = bytearray(b"\0" * 0x80)
    # packet 0 (joint 1 via slot 0), packet 1 (weight entry 0 = matrix index 2)
    dl0 = struct.pack(">BH", 0x90, 3)
    for i in range(3):
        dl0 += struct.pack(">bbbHHH", 0, 0, 0, i, 0, i)
    dl0 += b"\0" * ((-len(dl0)) % 32)
    dl1 = struct.pack(">BH", 0x90, 3)
    for i in range(3):
        dl1 += struct.pack(">bbbHHH", 0, 0, 0, 3 + i, 0, i)
    dl1 += b"\0" * ((-len(dl1)) % 32)
    dl0_off = len(out)
    out += dl0
    dl1_off = len(out)
    out += dl1
    tex_off = len(out)
    out += struct.pack(">BBHH", 10, 0, 8, 8) + b"\0" * 26  # CMPR 8x8
    # one CMPR block: c0 = red (0xF800), c1 = red, all indices 0
    out += (struct.pack(">HH", 0xF800, 0xF800) + b"\0" * 4) * 4
    mat_off = len(out)
    for k in range(2):
        m = bytes([255, 255, 255, 255]) + struct.pack(">HBBB", 0, k, 1, 0) + b"\0" * 23
        for s in range(8):
            m += struct.pack(">HH7f", 0, 0 if s == 0 else 0xFFFF, *([0.0] * 7))
        out += m
    samp_off = len(out)
    out += struct.pack(">HHBBBB", 0, 0xFFFF, 1, 0, 0, 0)
    shape_off = len(out)
    out += struct.pack(">BBBBHH", 1, 0, 0x26, 0, 1, 0)
    out += struct.pack(">BBBBHH", 1, 0, 0x26, 0, 1, 1)
    draw_off = len(out)
    out += struct.pack(">HH", 0, 0) + struct.pack(">HH", 1, 1)
    packet_off = len(out)
    out += struct.pack(">IIHH10H", dl0_off, len(dl0), 2, 1, 1, *([0xFFFF] * 9))
    out += struct.pack(">IIHH10H", dl1_off, len(dl1), 2, 1, 2, *([0xFFFF] * 9))
    out += b"\0" * 64  # "LOD" packets (ignored)
    texarr_off = len(out)
    out += struct.pack(">I", tex_off)
    pos_off = len(out)
    out += positions.tobytes()
    nrm_off = len(out)
    out += normals.tobytes()
    tc_off = len(out)
    out += texcoords.tobytes()
    node_off = len(out)
    out += struct.pack(">6HI", 0, 1, 0, 0, 1, 0, 0)  # root: has child, draws element 0
    out += struct.pack(">6HI", 1, 0, 0, 0, 1, 1, 0)  # child: draws element 1
    matrix_off = len(out)
    out += _inv_bind(0, 0, 0) + _inv_bind(10, 0, 0)
    weight_off = len(out)
    out += struct.pack(">ff", 0.25, 0.75)
    widx_off = len(out)
    out += struct.pack(">HH", 0, 1)
    wcnt_off = len(out)
    out += bytes([2])
    struct.pack_into(">I10H", out, 0, lm_mdl.MAGIC, 2, 0, 2, 2, 1, 2, 6, 1, 0, 3)
    struct.pack_into(">6H", out, 0x20, 1, 0, 1, 2, 2, 2)
    struct.pack_into(
        ">10I",
        out,
        0x30,
        node_off,
        packet_off,
        matrix_off,
        weight_off,
        widx_off,
        wcnt_off,
        pos_off,
        nrm_off,
        0,
        tc_off,
    )
    struct.pack_into(">6I", out, 0x60, texarr_off, 0, mat_off, samp_off, shape_off, draw_off)
    return bytes(out)


def test_mdl_parse():
    m = lm_mdl.parse(build_mdl())
    assert m.joint_count == 2 and len(m.positions) == 6 and len(m.texcoords) == 3
    assert [n.parent for n in m.nodes] == [-1, 0]
    assert m.weights == [[(0, 0.25), (1, 0.75)]]
    assert [t.fmt for t in m.textures] == [14]
    assert m.materials[0].samplers[0] == 0 and m.materials[0].samplers[1] == 0xFFFF
    assert m.materials[1].alpha_flags == 1
    assert m.draw_elements == [(0, 0), (1, 1)]
    fields = lm_mdl.vertex_fields(m, m.shapes[0])
    assert [f for f, _ in fields] == ["mtx", "t0mtx", "t1mtx", "pos", "nrm", "tex0"]
    prims = lm_mdl.parse_display_list(m.packets[0].data, fields)
    assert len(prims) == 1 and list(prims[0][1]["pos"]) == [0, 1, 2]


def test_mdl_scene():
    data = build_mdl()
    assert lm.detect("model/luige.mdl", data[:64], len(data))
    assert not lm.detect("model/luige.mdl", b"\0" * 64, len(data))
    scenes = lm.extract(data, "model/luige.mdl", None)
    assert len(scenes) == 1
    sc = scenes[0]
    assert len(sc.joints) == 2 and sc.joints[1].parent == 0
    np.testing.assert_allclose(sc.joints[1].translation, [10, 0, 0])
    assert sc.materials[0].texture == "tex00" and not sc.materials[0].clamp_u
    assert sc.materials[0].clamp_v and sc.materials[1].alpha_blend
    assert tuple(sc.textures["tex00"][0, 0]) == (255, 0, 0, 255)
    rigid = next(p for p in sc.primitives if p.material == 0)
    np.testing.assert_allclose(rigid.positions[1], [11, 0, 0], atol=1e-5)  # joint space + 10
    assert rigid.joints[0, 0] == 1 and rigid.weights[0, 0] == 1.0
    weighted = next(p for p in sc.primitives if p.material == 1)
    np.testing.assert_allclose(weighted.positions[0], [5, 5, 5])
    assert list(weighted.joints[0][:2]) == [0, 1]
    np.testing.assert_allclose(weighted.weights[0][:2], [0.25, 0.75])


def build_bin() -> bytes:
    """Room with a root node and one child (rotated 90 deg about Y, moved +100 x) drawing
    a textured quad batch."""
    out = bytearray(b"\x02" + b"room".ljust(11, b"\0") + b"\0" * (21 * 4))
    offs = [0] * 21
    offs[0] = len(out)
    out += struct.pack(">HHBBHI", 8, 8, 4, 0, 0, 12)  # RGB565 8x8, data right after header
    out += b"\x07\xe0" * 64  # green
    offs[1] = len(out)
    out += struct.pack(">hHBB", 0, 0xFFFF, 1, 2) + b"\0" * 14
    offs[2] = len(out)
    out += struct.pack(">12h", 0, 0, 0, 10, 0, 0, 10, 10, 0, 0, 10, 0)
    offs[3] = len(out)
    out += struct.pack(">3f", 0, 0, 1)
    offs[6] = len(out)
    out += struct.pack(">8f", 0, 0, 1, 0, 1, 1, 0, 1)
    offs[10] = len(out)
    out += bytes([1, 1, 0, 255, 128, 0, 255, 0]) + struct.pack(">8h", 0, *([-1] * 7))
    out += struct.pack(">8h", *([0] * 8))
    offs[11] = len(out)
    dl = struct.pack(">BH", 0x80, 4)
    for i in range(4):
        dl += struct.pack(">HHH", i, 0, i)
    dl += b"\0" * ((-len(dl)) % 32)
    out += struct.pack(">HHIBBBBI", 2, len(dl) // 32, 0x2600, 1, 2, 1, 0, 0x18) + b"\0" * 8
    out += dl
    offs[12] = len(out)

    def node(parent, child, nxt, prev, flags, rot, pos, parts_off, n_parts):
        b = struct.pack(">4h", parent, child, nxt, prev) + bytes([0, flags, 0, 0])
        b += struct.pack(">3f", 1, 1, 1) + struct.pack(">3f", *rot) + struct.pack(">3f", *pos)
        b += struct.pack(">6f", 0, 0, 0, 1, 1, 1) + struct.pack(">f", 0)
        b += struct.pack(">HHI", n_parts, 0, parts_off)
        return b + b"\0" * (0x8C - len(b))

    out += node(-1, 1, -1, -1, 0, (0, 0, 0), (0, 0, 0), 0x8C * 2, 0)
    out += node(0, -1, -1, -1, 0x48, (0, 90, 0), (100, 0, 0), 0x8C * 2, 1)
    out += struct.pack(">hh", 0, 0)
    struct.pack_into(">21I", out, 0x0C, *offs)
    return bytes(out)


def test_bin_parse_and_scene():
    data = build_bin()
    assert lm_bin.looks_like_bin(data[:64], len(data))
    assert lm.detect("Iwamoto/map1/room.bin", data[:64], len(data))
    assert not lm.detect("Iwamoto/map1/room.bin", b"\x02" + b"\0" * 63, len(data))
    m = lm_bin.parse(data)
    assert m.name == "room" and len(m.textures) == 1 and m.textures[0].fmt == 4
    assert m.samplers[0].wrap_u == 1 and m.samplers[0].wrap_v == 2
    assert len(m.positions) == 4 and len(m.texcoords[0]) == 4
    assert m.shaders[0].tint == (255, 128, 0, 255) and m.shaders[0].samplers[0] == 0
    assert [n.parent for n in m.nodes] == [-1, 0]
    assert m.nodes[1].parts == [(0, 0)] and m.nodes[1].render_flags == 0x48
    assert list(m.batches) == [0] and m.batches[0].attribs == 0x2600
    scenes = lm.extract(data, "Iwamoto/map1/room.bin", None)
    sc = scenes[0]
    assert sc.name == "room" and len(sc.joints) == 2
    assert sc.materials[0].texture == "tex00" and sc.materials[0].mirror_v
    assert sc.materials[0].alpha_blend and sc.materials[0].unlit
    np.testing.assert_allclose(sc.materials[0].base_color, (1.0, 128 / 255, 0.0, 1.0))
    assert tuple(sc.textures["tex00"][0, 0]) == (0, 255, 0, 255)
    p = sc.primitives[0]
    assert len(p.indices) == 6 and p.joints[0, 0] == 1
    # (10, 0, 0) in node space -> rotated 90 deg about Y -> (0, 0, -10), then +100 x
    np.testing.assert_allclose(p.positions[1], [100, 0, -10], atol=1e-5)
    assert p.uvs is not None and p.normals is not None
