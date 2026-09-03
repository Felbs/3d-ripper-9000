"""Acclaim ``.GDF`` meshes (gcrip.formats.acclaim_gdf).

`docs/OPEN.md` recorded this as blocked because `brewers.GDF` "has none [no display lists] at
any stride".  It has 182.  They were being looked for behind the attribute block, and the
attribute block was in the wrong place - `len(file) - attributes - trailing` is right on the two
small samples by coincidence and lands in the middle of the vertices on the big one.

The tests pin the two identities that settled it: a mesh's declared radius is the largest `|v|`
over its decoded positions, and the groups' declared triangle counts are what the display lists
produce.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import acclaim_gdf


def vertex(code: int, pos, uv=(0.0, 0.0)) -> bytes:
    if code == 1:
        return struct.pack(">3f", *pos)
    if code == 3:
        return struct.pack(">3f", *pos) + b"\xff\xfd\xfd\xff" + struct.pack(">2f", *uv)
    return struct.pack(">3f", *pos) + struct.pack(">3f", 0.0, 1.0, 0.0) + struct.pack(">2f", *uv)


def strip_list(indices, width: int) -> bytes:
    out = bytearray([acclaim_gdf.STRIP]) + struct.pack(">H", len(indices))
    for i in indices:
        out += struct.pack(">H", i) * width
    return bytes(out)


def triangle_list(indices, width: int) -> bytes:
    out = bytearray([acclaim_gdf.TRIANGLES]) + struct.pack(">H", len(indices))
    for i in indices:
        out += struct.pack(">H", i) * width
    return bytes(out)


def build(meshes, name: str = "TestModel", materials=("mat0",)) -> bytes:
    """`meshes` = [(name, code, [positions], display-list bytes, triangles)]."""
    attrs = bytearray()
    lists = bytearray()
    mesh_records = bytearray()
    group_records = bytearray()
    for i, (nm, code, positions, dl, tris) in enumerate(meshes):
        voff = len(attrs)
        for p in positions:
            attrs += vertex(code, p)
        radius = max(float(np.linalg.norm(p)) for p in positions)
        raw = nm.encode("latin-1")
        mesh_records += (raw + bytes(16 - len(raw)))[:16]
        mesh_records += struct.pack(">3IIfII", 0x10, i, 1, len(positions), radius, code, voff)
        group_records += struct.pack(">7I", 0, 0, min(i, len(materials) - 1), len(lists), len(dl), 0, tris)
        group_records += bytes(acclaim_gdf.GROUP_RECORD - 28)
        lists += dl
    raw = name.encode("latin-1")
    head = bytearray((raw + bytes(acclaim_gdf.NAME_LEN - len(raw)))[: acclaim_gdf.NAME_LEN])
    head += struct.pack(">6I", len(materials), 0, len(meshes), len(meshes), len(attrs), len(lists))
    for m in materials:
        mb = m.encode("latin-1")
        head += (mb + bytes(acclaim_gdf.MATERIAL_NAME - len(mb)))[: acclaim_gdf.MATERIAL_NAME]
    return bytes(head + mesh_records + group_records + attrs + lists)


CUBE = [(1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 3.0), (1.0, 1.0, 1.0), (2.0, 0.0, 1.0)]


def test_a_strip_reads_back_as_triangles():
    dl = strip_list([0, 1, 2, 3, 4], 3)
    data = build([("bat", 2, CUBE, dl, 3)])
    m = acclaim_gdf.model(data)
    assert m.name == "TestModel"
    assert len(m.meshes) == 1 and m.meshes[0].stride == 32
    assert acclaim_gdf.all_triangles(data, m, m.meshes[0]) == [
        (0, 1, 2),
        (2, 1, 3),
        (2, 3, 4),
    ]


def test_the_position_only_code_spends_one_index_a_vertex():
    """The display list's index width follows the mesh's attribute code - one for code 1,
    three for the others.  Reading three everywhere walks off the end of the list."""
    dl = triangle_list([0, 1, 2, 2, 3, 4], 1)
    data = build([("bat_shadow", 1, CUBE, dl, 2)])
    m = acclaim_gdf.model(data)
    assert m.meshes[0].stride == 12
    assert acclaim_gdf.all_triangles(data, m, m.meshes[0]) == [(0, 1, 2), (2, 3, 4)]


def test_the_radius_identity_holds_and_can_fail():
    from gcrip import identities

    dl = strip_list([0, 1, 2, 3, 4], 3)
    data = build([("bat", 2, CUBE, dl, 3)])
    results = {r.identity.name: r for r in identities.check(acclaim_gdf, data)}
    assert results["the bounding radius is the largest vertex"].held is True

    m = acclaim_gdf.model(data)
    hurt = bytearray(data)
    struct.pack_into(">f", hurt, m.base - 0, 0.0)  # damage the first vertex
    at = acclaim_gdf.HEADER + acclaim_gdf.MATERIAL_NAME + 16 + 16
    struct.pack_into(">f", hurt, at, 99.0)  # ... and claim a radius nothing reaches
    hurt_results = {r.identity.name: r for r in identities.check(acclaim_gdf, bytes(hurt))}
    assert hurt_results["the bounding radius is the largest vertex"].held is False


def test_the_declared_triangle_count_is_checked():
    from gcrip import identities

    dl = strip_list([0, 1, 2, 3, 4], 3)
    data = build([("bat", 2, CUBE, dl, 3)])
    results = {r.identity.name: r for r in identities.check(acclaim_gdf, data)}
    assert results["the display lists produce the declared triangles"].held is True

    hurt = bytearray(data)
    m = acclaim_gdf.model(data)
    groups_at = acclaim_gdf.HEADER + acclaim_gdf.MATERIAL_NAME + acclaim_gdf.MESH_RECORD
    struct.pack_into(">I", hurt, groups_at + 24, 99)
    hurt_results = {r.identity.name: r for r in identities.check(acclaim_gdf, bytes(hurt))}
    assert hurt_results["the display lists produce the declared triangles"].held is False


def test_a_bone_name_table_is_not_read_as_meshes():
    """A `.SKN` carries a 23-bone name table where a `.GDF` has its mesh records.  Accepted on
    the header alone it produces four-billion-triangle counts; it has to be declined."""
    head = bytearray(b"Kangaroos" + bytes(acclaim_gdf.NAME_LEN - 9))
    head += struct.pack(">6I", 2, 23, 4, 5, 14624, 10880)
    head += bytes(acclaim_gdf.MATERIAL_NAME * 2)
    head += b"ROOT" + bytes(28) + b"L_UP_LEG" + bytes(24)
    with pytest.raises(acclaim_gdf.GdfError):
        acclaim_gdf.model(bytes(head) + bytes(30000))


def test_the_plugin_makes_one_primitive_a_group():
    from gcrip.plugins import acclaim_gdf as plugin

    dl = strip_list([0, 1, 2, 3, 4], 3)
    data = build([("bat", 2, CUBE, dl, 3)], materials=("two_tone_bat",))
    assert plugin.detect("m/bat.GDF", data[:64], len(data))
    scenes = plugin.extract(data, "m/bat.GDF", None)
    assert len(scenes) == 1
    assert scenes[0].triangles == 3
    assert scenes[0].materials[0].name == "two_tone_bat"
    assert scenes[0].primitives[0].material < len(scenes[0].materials)


def test_a_file_with_no_triangles_says_so():
    from gcrip.plugins import acclaim_gdf as plugin

    # a strip whose corners are the same vertex: a display list that decodes to nothing
    data = build([("bat", 2, CUBE, strip_list([1, 1, 1], 3), 0)])
    with pytest.raises(acclaim_gdf.GdfError, match="no triangles"):
        plugin.extract(data, "m/bat.GDF", None)
