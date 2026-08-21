"""DZB collision parsing."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import dzb


def build_dzb(verts, tris, groups, infs) -> bytes:
    """tris = [(v0,v1,v2,inf_idx,grp_idx)], groups = [(name, attr, parent, rot, trans)],
    infs = [pass_flag] or [(inf0, inf1, inf2, inf3)]."""
    names = bytearray()
    name_offs = []
    header_size = 0x30
    # layout: header | names | verts | tris | groups | infs  (blocks/tree empty)
    for name, *_ in groups:
        name_offs.append(header_size + len(names))
        names += name.encode() + b"\0"
    o_vtx = header_size + len(names)
    o_tri = o_vtx + len(verts) * 12
    o_grp = o_tri + len(tris) * 10
    o_inf = o_grp + len(groups) * 0x34

    out = bytearray(
        struct.pack(
            ">12I",
            len(verts), o_vtx, len(tris), o_tri, 0, 0, 0, 0,
            len(groups), o_grp, len(infs), o_inf,
        )
    )
    out += names
    for v in verts:
        out += struct.pack(">3f", *v)
    for t in tris:
        out += struct.pack(">5H", *t)
    for (_name, attr, parent, rot, trans), noff in zip(groups, name_offs, strict=True):
        out += struct.pack(">I", noff)
        out += struct.pack(">3f", 1.0, 1.0, 1.0)  # scale
        out += struct.pack(">3h", *rot) + b"\0\0"  # rot + pad
        out += struct.pack(">3f", *trans)
        out += struct.pack(">hh", parent, -1)  # parent, sibling
        out += struct.pack(">hh", -1, 0)  # child, room
        out += struct.pack(">hh", 0, 0)  # 0x2C, tree
        out += struct.pack(">I", attr)
    for inf in infs:
        words = inf if isinstance(inf, tuple) else (0, 0, 0, inf)
        out += struct.pack(">4I", *words)
    return bytes(out)


def test_dzb_surfaces_and_pass_flags():
    verts = [(0, 0, 0), (10, 0, 0), (0, 0, 10), (0, 5, 0)]
    tris = [
        (0, 1, 2, 0, 0),  # solid ground
        (0, 1, 3, 1, 0),  # solid but Link passes through -> excluded from walkable
        (0, 2, 3, 0, 1),  # water group
        (1, 2, 3, 0, 2),  # lava group
    ]
    groups = [
        ("ground", 0x0, -1, (0, 0, 0), (0, 0, 0)),
        ("pool", dzb.ATTR_WATER, -1, (0, 0, 0), (0, 0, 0)),
        ("magma", dzb.ATTR_LAVA, -1, (0, 0, 0), (0, 0, 0)),
    ]
    infs = [0, dzb.PASS_LINK]
    d = dzb.parse(build_dzb(verts, tris, groups, infs))
    assert [g.surface for g in d.groups] == ["solid", "water", "lava"]
    sv, st = d.mesh("solid")
    assert len(st) == 1  # the pass-through tri is dropped
    sv2, st2 = d.mesh("solid", walkable_only=False)
    assert len(st2) == 2
    _, wt = d.mesh("water")
    _, lt = d.mesh("lava")
    assert len(wt) == 1 and len(lt) == 1


def test_dzb_group_transform_baked():
    verts = [(0, 0, 0), (10, 0, 0), (0, 0, 10)]
    tris = [(0, 1, 2, 0, 0)]
    # translated group, +90 degrees about Y (0x4000): x -> z, z -> -x... baked into verts
    groups = [("platform", 0x0, -1, (0, 0x4000, 0), (100.0, 50.0, 0.0))]
    d = dzb.parse(build_dzb(verts, tris, groups, [0]))
    sv, st = d.mesh("solid")
    assert len(st) == 1
    assert np.allclose(sv[:, 1], 50.0)  # translation applied
    spans = sv.max(0) - sv.min(0)
    assert spans[0] > 5 and spans[2] > 5  # rotated footprint still 10x10 in XZ
    corners = {tuple(np.round(v).astype(int)) for v in sv}
    assert (100, 50, 0) in corners  # origin vertex lands on the group translation


def test_dzb_property_decode_and_tags():
    # a floor quad (y=0) plus three vertical walls in the XY plane, one per wall code
    verts = [
        (0, 0, 0), (10, 0, 0), (0, 0, 10),  # floor
        (0, 0, 20), (10, 0, 20), (10, 100, 20), (0, 100, 20),  # wall quad corners
    ]
    inf1 = lambda wall, special=0, attr=0, ground=0, link=0: (  # noqa: E731
        link | (wall << 8) | (special << 12) | (attr << 16) | (ground << 21)
    )
    infs = [
        # floor: cam 7, sound 3, exit 5, color 0x12, no shadow; attr grass(4), ground 8
        ((7 | (3 << 8) | (5 << 13) | (0x12 << 19) | (1 << 27)), inf1(0, 1, 4, 8, 0x2A), 0, 0),
        (0, inf1(dzb.WALL_LADDER), 0, 0),
        (0, inf1(dzb.WALL_CLIMB), 0, dzb.HOOKSHOT_STICK),
        (0, inf1(dzb.WALL_NOHANG), 0, 0),
        (0, inf1(dzb.WALL_PLAIN), (9 | (2 << 8) | (3 << 16) | (4 << 24)), dzb.PASS_LINK),
    ]
    tris = [
        (0, 1, 2, 0, 0),  # floor, slide special code
        (3, 4, 5, 1, 0),  # ladder wall
        (3, 5, 6, 2, 0),  # vine wall + hookshot sticks
        (3, 4, 6, 3, 0),  # no-hang wall
        (4, 5, 6, 4, 0),  # plain wall Link passes through (fence)
    ]
    groups = [("room", 0x0, -1, (0, 0, 0), (0, 0, 0))]
    d = dzb.parse(build_dzb(verts, tris, groups, infs))

    p0 = d.properties[0]
    assert (p0.cam_id, p0.sound_id, p0.exit_index, p0.poly_color) == (7, 3, 5, 0x12)
    assert p0.no_shadow
    assert (p0.link_no, p0.wall_code, p0.special_code) == (0x2A, 0, 1)
    assert (p0.attribute_code, p0.ground_code) == (4, 8)
    p4 = d.properties[4]
    assert (p4.cam_move_bg, p4.room_cam_id, p4.room_path_id, p4.room_path_point) == (9, 2, 3, 4)
    assert p4.link_through and not p4.hookshot
    assert d.properties[2].hookshot and d.properties[1].wall == "ladder"

    assert list(d.tri_wall) == [0, 4, 1, 2, 0]
    assert list(d.is_wall()) == [False, True, True, True, True]
    assert d.tag_counts() == {
        "ladder": 1, "ladder_top": 0, "climb": 1, "nohang": 1, "grab": 0,
        "hang": 2,  # ladder + vine walls; nohang and Link-pass-through excluded
        "hookshot": 1, "slide": 1,
    }
    _, lt = d.tagged("ladder")
    assert len(lt) == 1
    # existing surface API still works and still drops the pass-through tri
    _, st = d.mesh("solid")
    assert len(st) == 4
    _, st_all = d.mesh("solid", walkable_only=False)
    assert len(st_all) == 5
    lv, lt2 = d.mesh_by(d.tag_mask("ladder") | d.tag_mask("climb"))
    assert len(lt2) == 2 and lv[:, 1].max() == 100
