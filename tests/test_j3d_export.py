import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from gcrip.export import gltf
from gcrip.formats import bti, j3d


def test_triangulate():
    assert j3d.triangulate(j3d.PRIM_TRIANGLES, 6).tolist() == [[0, 1, 2], [3, 4, 5]]
    assert j3d.triangulate(j3d.PRIM_TRISTRIP, 5).tolist() == [
        [0, 1, 2],
        [1, 3, 2],
        [2, 3, 4],
    ]
    assert j3d.triangulate(j3d.PRIM_TRIFAN, 4).tolist() == [[0, 1, 2], [0, 2, 3]]
    assert j3d.triangulate(j3d.PRIM_QUADS, 4).tolist() == [[0, 1, 2], [0, 2, 3]]
    assert len(j3d.triangulate(j3d.PRIM_LINES, 4)) == 0


def _tex(name="t"):
    return bti.BtiTexture(name, 4, 4, 4, 1, 1, None, None, 0, 1, 1, 1, b"\x00" * 32)


def _model():
    """Two joints: root at origin, child translated +10 in X and rotated 90deg about Z.
    Shape 0 is rigidly bound to the child joint (so its verts are joint-local).
    Shape 1 is envelope-weighted 50/50 between both joints (verts in model space)."""
    root = j3d.Joint(0, "root", None, (1, 1, 1), (0, 0, 0), (0, 0, 0), 0, (0,) * 3, (0,) * 3)
    child = j3d.Joint(
        1, "child", 0, (1, 1, 1), (0, 0, math.pi / 2), (10, 0, 0), 0, (0,) * 3, (0,) * 3
    )
    root.children = [1]
    j3d._joint_matrices([root, child], [0])
    vd = j3d.VertexData()
    vd.pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [5, 5, 5]], np.float32)
    vd.nrm = np.array([[0, 0, 1]], np.float32)
    vd.tex[0] = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    tri = j3d.Primitive(
        j3d.PRIM_TRIANGLES,
        {
            j3d.VA_PNMTXIDX: np.array([0, 0, 0]),
            j3d.VA_POS: np.array([0, 1, 2]),
            j3d.VA_NRM: np.array([0, 0, 0]),
            j3d.VA_TEX0: np.array([0, 1, 2]),
        },
    )
    shape0 = j3d.Shape(
        0,
        0,
        [(j3d.VA_PNMTXIDX, 1), (j3d.VA_POS, 3), (j3d.VA_NRM, 3), (j3d.VA_TEX0, 3)],
        [j3d.Packet([1], [tri])],
        (0,) * 3,
        (0,) * 3,
        material=0,
    )
    tri2 = j3d.Primitive(
        j3d.PRIM_TRIANGLES,
        {
            j3d.VA_PNMTXIDX: np.array([0, 0, 0]),
            j3d.VA_POS: np.array([3, 1, 2]),
            j3d.VA_NRM: np.array([0, 0, 0]),
            j3d.VA_TEX0: np.array([0, 1, 2]),
        },
    )
    shape1 = j3d.Shape(
        1, 3, shape0.attributes, [j3d.Packet([2], [tri2])], (0,) * 3, (0,) * 3, material=0
    )
    mat = j3d.Material(
        0,
        "m",
        [0] + [-1] * 7,
        [j3d.TevOrder(0, 0, 0)],
        [j3d.TexGen(1, 4, 60)],
        2,
        0,
        0,
        0,
        7,
        0,
        0,
        7,
        0,
        True,
        (1, 1, 1, 1),
    )
    return j3d.Model(
        name="test",
        magic="J3D2bmd3",
        joints=[root, child],
        root_joints=[0],
        vertices=vd,
        envelopes=[j3d.Envelope([0, 1], [0.5, 0.5])],
        inv_bind=[np.eye(4), np.linalg.inv(child.world)],
        draw_matrices=[j3d.DrawMatrix(False, 0), j3d.DrawMatrix(False, 1), j3d.DrawMatrix(True, 0)],
        shapes=[shape0, shape1],
        materials=[mat],
        textures=[_tex()],
        inf1=[],
    )


def test_export_bakes_rigid_vertices_and_writes_valid_gltf(tmp_path):
    model = _model()
    st = gltf.export(model, tmp_path / "m", flip_winding=False)
    assert st.shapes == 2 and st.triangles == 2 and st.skinned
    g = json.loads((tmp_path / "m.gltf").read_text())
    binf = (tmp_path / "m.bin").read_bytes()
    assert (tmp_path / "m_tex" / "t.png").exists()
    # rigid shape's vertex (1,0,0) in child-local -> child world = T(10,0,0)*Rz(90) -> (10,1,0)
    # one mesh (and node) per shape
    assert len(g["meshes"]) == 2
    prim = g["meshes"][0]["primitives"][0]
    acc = g["accessors"][prim["attributes"]["POSITION"]]
    view = g["bufferViews"][acc["bufferView"]]
    pos = np.frombuffer(
        binf[view["byteOffset"] : view["byteOffset"] + view["byteLength"]], np.float32
    ).reshape(-1, 3)
    assert any(np.allclose(p, [10, 1, 0], atol=1e-5) for p in pos)
    assert any(np.allclose(p, [10, 0, 0], atol=1e-5) for p in pos)
    # weighted shape's vertex (5,5,5) stays in model space
    prim1 = g["meshes"][1]["primitives"][0]
    acc = g["accessors"][prim1["attributes"]["POSITION"]]
    view = g["bufferViews"][acc["bufferView"]]
    pos1 = np.frombuffer(
        binf[view["byteOffset"] : view["byteOffset"] + view["byteLength"]], np.float32
    ).reshape(-1, 3)
    assert any(np.allclose(p, [5, 5, 5]) for p in pos1)
    # weights: 0.5/0.5 on joints 0 and 1
    acc = g["accessors"][prim1["attributes"]["WEIGHTS_0"]]
    view = g["bufferViews"][acc["bufferView"]]
    w = np.frombuffer(
        binf[view["byteOffset"] : view["byteOffset"] + view["byteLength"]], np.float32
    ).reshape(-1, 4)
    assert np.allclose(w[:, :2], 0.5)
    # skin / nodes
    assert g["skins"][0]["joints"] == [0, 1]
    assert g["nodes"][0]["name"] == "root" and g["nodes"][0]["children"] == [1]
    assert np.allclose(g["nodes"][1]["translation"], [10, 0, 0])
    assert g["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"] == 0
    mesh_nodes = [n for n in g["nodes"] if "mesh" in n]
    assert all(n["skin"] == 0 for n in mesh_nodes)


def test_detect_variants():
    model = _model()
    base = model.materials[0]
    import dataclasses

    model.materials = [
        dataclasses.replace(base, index=0, name="eyeL"),
        dataclasses.replace(base, index=1, name="eyeLdamA"),
        dataclasses.replace(base, index=2, name="ear"),
        dataclasses.replace(base, index=3, name="ear(2)"),
    ]
    shapes = []
    for i in range(4):
        sh = dataclasses.replace(model.shapes[0], index=i, material=i, joint=0)
        shapes.append(sh)
    model.shapes = shapes
    assert gltf.detect_variants(model) == {1: 0}


REAL_ISO = os.environ.get("GCRIP_TEST_ISO")


@pytest.mark.skipif(not REAL_ISO, reason="set GCRIP_TEST_ISO to a legally dumped GC image")
def test_real_disc_rip_subset(tmp_path):
    from gcrip.rip import rip

    res = rip(Path(REAL_ISO), tmp_path, quiet=True, limit=20)
    assert any(m.out_rel for m in res.models)
    assert not [m for m in res.models if m.error and not m.error.startswith("skipped")]


def test_detail_layer_is_baked_into_one_texture(tmp_path):
    """Base x detail textures in the same UV space (Wind Waker eye white x pupil)
    are multiplied into a single baked PNG used as the material's base color."""
    import dataclasses

    model = _model()
    white = _tex("eyewhite")
    white.data = bytes([0xFF]) * 32  # RGB565 all-white 4x4
    pupil = _tex("pupil")
    pupil.data = bytes([0x00]) * 32  # black
    model.textures = [white, pupil]
    m = model.materials[0]
    model.materials = [
        dataclasses.replace(
            m,
            tex_slots=[0, 1] + [-1] * 6,
            tev_orders=[j3d.TevOrder(1, 1, 0), j3d.TevOrder(0, 0, 0)],
            texgens=[j3d.TexGen(1, 4, 60), j3d.TexGen(1, 4, 33)],
            tex_matrices=[None, j3d.TexMtx((0.5, 0.5), (1, 1), 0.0, (0.1, 0.0))] + [None] * 8,
        )
    ]
    assert model.materials[0].detail()[0] == 1
    st = gltf.export(model, tmp_path / "e")
    g = json.loads((tmp_path / "e.gltf").read_text())
    idx = g["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    assert g["textures"][idx]["name"] == "eyewhite_x_pupil"
    assert (tmp_path / "e_tex" / "eyewhite_x_pupil.png").exists()
    assert g["materials"][0]["extras"]["gcrip_composite"] == ["eyewhite", "pupil"]
    assert st.texture_images[-1][..., :3].max() == 0  # white * black = black
