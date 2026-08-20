"""DZB collision parsing."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import dzb


def build_dzb(verts, tris, groups, infs) -> bytes:
    """tris = [(v0,v1,v2,inf_idx,grp_idx)], groups = [(name, attr, parent, rot, trans)],
    infs = [pass_flag]."""
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
    for pf in infs:
        out += struct.pack(">4I", 0, 0, 0, pf)
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
