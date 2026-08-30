"""AGG text meshes - High Voltage (Hunter: The Reckoning)."""

import numpy as np

from gcrip.formats import agg
from gcrip.plugins import agg as plugin

SAMPLE = """Mesh[1]
{
\tMesh "bak"
\t{
\t\tMatAssignment[1]
\t\t{
\t\t\t"sym3"
\t\t}
\t\tVertexArray[1]
\t\t{
\t\t\tVertexArray
\t\t\t{
\t\t\t\tVertexFormat { Pos3D Normal TxtCoord 1 }
\t\t\t\tVertex[4]
\t\t\t\t{
\t\t\t\t\t0.0 0.0 0.0  0.0 1.0 0.0  0.0 0.0
\t\t\t\t\t1.0 0.0 0.0  0.0 1.0 0.0  1.0 0.0
\t\t\t\t\t1.0 0.0 1.0  0.0 1.0 0.0  1.0 1.0
\t\t\t\t\t0.0 0.0 1.0  0.0 1.0 0.0  0.0 1.0
\t\t\t\t}
\t\t\t}
\t\t}
\t\tIndexArray[1]
\t\t{
\t\t\tIndexArray
\t\t\t{
\t\t\t\tIndex16Bit
\t\t\t\tIndex[6]// 2 Faces
\t\t\t\t{
\t\t\t\t\t0 1 2 // eOpenFile(symblx.agm)
\t\t\t\t\t0 2 3 // 2 Faces
\t\t\t\t}
\t\t\t}
\t\t}
%s\t}
}
"""

COMPONENTS = """\t\tMeshComponent[2]
\t\t{
\t\t\tMeshComponent
\t\t\t{
\t\t\t\tMatAssignment 0 // "sym3"
\t\t\t\tPosTransform 6 0
\t\t\t\tVertexGroup 0 0 3
\t\t\t\tIndexedTriangleGroup 0 0 3 // 1 Faces
\t\t\t}
\t\t\tMeshComponent
\t\t\t{
\t\t\t\tMatAssignment 0 // "sym3"
\t\t\t\tVertexGroup 0 0 4
\t\t\t\tIndexedTriangleGroup 0 3 3 // 1 Faces
\t\t\t}
\t\t}
"""


def build(components=True):
    return (SAMPLE % (COMPONENTS if components else "")).encode()


def test_the_vertex_format_gives_the_row_width():
    assert agg._columns("Pos3D Normal TxtCoord 1") == [("Pos3D", 3), ("Normal", 3), ("TxtCoord", 2)]
    assert agg._columns("Pos3D BlendWeight 1 DiffuseColor TxtCoord 0") == [
        ("Pos3D", 3),
        ("BlendWeight", 1),
        ("DiffuseColor", 4),
        ("TxtCoord", 0),
    ]


def test_an_unknown_token_refuses_the_row_rather_than_shifting_it():
    """A token of unknown width would move every column after it without any sign."""
    assert agg._columns("Pos3D Tangent TxtCoord 1") == []


def test_a_mesh_without_components_is_one_part():
    (part,) = agg.parts(build(components=False))
    assert part.name == "bak" and part.material == "sym3"
    assert len(part.positions) == 4 and len(part.indices) == 6
    assert part.uvs is not None and part.normals is not None
    assert np.allclose(part.normals[0], (0.0, 1.0, 0.0))


def test_a_component_slices_both_ranges():
    """VertexGroup counts vertices; IndexedTriangleGroup counts indices, not triangles."""
    first, second = agg.parts(build())
    assert len(first.positions) == 3 and len(first.indices) == 3
    assert len(second.positions) == 4 and len(second.indices) == 3


def test_the_material_name_comes_from_the_assignment_block_not_the_mesh_name():
    (part,) = agg.parts(build(components=False))
    assert part.material == "sym3"  # the mesh is called "bak" and is quoted too


def test_comments_inside_the_index_rows_are_ignored():
    (part,) = agg.parts(build(components=False))
    assert part.indices.tolist() == [0, 1, 2, 0, 2, 3]


def test_plugin_builds_one_scene_with_a_named_material():
    data = build()
    assert plugin.detect("SCENE/BAK.AGG", data[:64], len(data))
    assert not plugin.detect("SCENE/BAK.AGT", data[:64], len(data))
    (scene,) = plugin.extract(data, "UI__SCENE__BAK.AGG", None)
    assert scene.triangles == 2
    assert [m.name for m in scene.materials] == ["sym3"]
    assert {p.material for p in scene.primitives} == {0}
