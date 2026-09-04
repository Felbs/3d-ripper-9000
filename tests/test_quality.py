"""Synthetic-fixture tests for the model quality auditor (gcrip/quality.py)."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from gcrip.quality import audit_game, audit_model, score_model

# -- fixture builder -------------------------------------------------------------------


def write_gltf(
    dirpath: Path,
    name: str,
    positions: np.ndarray,
    triangles: np.ndarray,
    image_uri: str | None = None,
    textured_material: bool = False,
) -> Path:
    """Write a minimal glTF 2.0 + sibling .bin like the gcrip exporter does."""
    dirpath.mkdir(parents=True, exist_ok=True)
    pos = np.asarray(positions, dtype="<f4")
    idx = np.asarray(triangles, dtype="<u2").reshape(-1)
    pos_bytes = pos.tobytes()
    idx_bytes = idx.tobytes()
    if len(pos_bytes) % 4:
        pos_bytes += b"\0" * (4 - len(pos_bytes) % 4)
    bin_path = dirpath / f"{name}.bin"
    bin_path.write_bytes(pos_bytes + idx_bytes)
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "mode": 4, "material": 0}
                ]
            }
        ],
        "materials": [
            {
                "pbrMetallicRoughness": (
                    {"baseColorTexture": {"index": 0}} if textured_material else {}
                )
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(pos),
                "type": "VEC3",
                "min": pos.min(axis=0).tolist(),
                "max": pos.max(axis=0).tolist(),
            },
            {"bufferView": 1, "componentType": 5123, "count": len(idx), "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos) * 12, "target": 34962},
            {
                "buffer": 0,
                "byteOffset": len(pos_bytes),
                "byteLength": len(idx_bytes),
                "target": 34963,
            },
        ],
        "buffers": [{"byteLength": len(pos_bytes) + len(idx_bytes), "uri": f"{name}.bin"}],
    }
    if image_uri is not None:
        gltf["images"] = [{"uri": image_uri}]
        gltf["samplers"] = [{}]
        gltf["textures"] = [{"source": 0, "sampler": 0}]
    path = dirpath / f"{name}.gltf"
    path.write_text(json.dumps(gltf), encoding="utf-8")
    return path


def grid_mesh(n: int = 20, offset=(0.0, 0.0, 0.0)) -> tuple[np.ndarray, np.ndarray]:
    """A subdivided (n x n) unit-square grid: a well-behaved dense mesh."""
    xs, ys = np.meshgrid(np.linspace(0, 1, n + 1), np.linspace(0, 1, n + 1))
    pos = np.stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)], axis=1) + np.asarray(offset)
    tris = []
    for r in range(n):
        for c in range(n):
            a = r * (n + 1) + c
            b, d, e = a + 1, a + n + 1, a + n + 2
            tris.append([a, b, e])
            tris.append([a, e, d])
    return pos.astype(np.float32), np.asarray(tris, dtype=np.int64)


def cube_mesh() -> tuple[np.ndarray, np.ndarray]:
    """A clean cube, subdivided so it has enough triangles for the spaghetti check."""
    parts_p, parts_t = [], []
    base = 0
    # six faces, each a 6x6 grid rotated into place
    for axis, sign in [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]:
        p, t = grid_mesh(6)
        face = np.zeros_like(p)
        other = [i for i in range(3) if i != axis]
        face[:, other[0]] = p[:, 0]
        face[:, other[1]] = p[:, 1]
        face[:, axis] = float(sign)
        parts_p.append(face)
        parts_t.append(t + base)
        base += len(p)
    return np.concatenate(parts_p), np.concatenate(parts_t)


# -- audit_model metrics ---------------------------------------------------------------


def test_clean_cube_scores_ok(tmp_path):
    pos, tris = cube_mesh()
    path = write_gltf(tmp_path, "cube", pos, tris, textured_material=True)
    m = audit_model(path)
    assert m["nonfinite_pct"] == 0
    assert m["median_edge_ratio"] < 0.15
    assert m["degenerate_edge_pct"] == 0
    assert m["dup_top_share"] < 0.3
    score, reasons = score_model(m)
    assert score == "ok", reasons


def test_spaghetti_shuffle_scores_garbage(tmp_path):
    pos, tris = grid_mesh(20)
    rng = np.random.default_rng(7)
    shuffled = rng.permutation(tris.reshape(-1)).reshape(-1, 3)
    path = write_gltf(tmp_path, "spag", pos, shuffled)
    m = audit_model(path)
    assert m["median_edge_ratio"] > 0.25
    score, reasons = score_model(m)
    assert score == "garbage"
    assert "spaghetti" in reasons


def test_collapsed_positions_score_garbage(tmp_path):
    pos, tris = grid_mesh(10)
    pos[:] = [1.0, 2.0, 3.0]  # every vertex at the same point
    path = write_gltf(tmp_path, "flat", pos, tris)
    m = audit_model(path)
    score, reasons = score_model(m)
    assert score == "garbage"
    assert "collapsed_extent" in reasons
    assert m["dup_top_share"] == 1.0


def test_nan_positions_score_garbage(tmp_path):
    pos, tris = grid_mesh(10)
    pos[5] = [np.nan, 0.0, 0.0]
    path = write_gltf(tmp_path, "nan", pos, tris)
    m = audit_model(path)
    assert m["nonfinite_pct"] > 0
    score, reasons = score_model(m)
    assert score == "garbage"
    assert "nan_positions" in reasons


def test_two_component_fragment_is_detected(tmp_path):
    p1, t1 = grid_mesh(8)
    p2, t2 = grid_mesh(8, offset=(5.0, 0.0, 0.0))
    pos = np.concatenate([p1, p2])
    tris = np.concatenate([t1, t2 + len(p1)])
    path = write_gltf(tmp_path, "frag", pos, tris)
    m = audit_model(path)
    assert m["n_components"] == 2
    assert abs(m["largest_component_share"] - 0.5) < 0.01


def test_tiny_model_vs_siblings_is_suspect(tmp_path):
    pos, tris = grid_mesh(2)  # 9 vertices
    path = write_gltf(tmp_path, "tiny", pos, tris)
    m = audit_model(path)
    score, reasons = score_model(m, game_ctx={"median_vertices": 5000.0})
    assert score == "suspect"
    assert "tiny_vs_siblings" in reasons


def test_missing_texture_file_is_suspect(tmp_path):
    pos, tris = grid_mesh(10)
    path = write_gltf(
        tmp_path, "broke", pos, tris, image_uri="broke_tex/gone.png", textured_material=True
    )
    m = audit_model(path)
    assert m["missing_texture_count"] == 1
    score, reasons = score_model(m)
    assert score == "suspect"
    assert "missing_texture_files" in reasons


# -- audit_game end to end -------------------------------------------------------------


def test_audit_game_untextured_and_report(tmp_path):
    gid = "GTEST1"
    gdir = tmp_path / gid
    pos, tris = grid_mesh(20)
    # a textured model (image present on disk)
    tex_dir = gdir / "good_tex"
    tex_dir.mkdir(parents=True)
    (tex_dir / "t.png").write_bytes(struct.pack(">I", 0x89504E47))
    write_gltf(gdir, "good", pos, tris, image_uri="good_tex/t.png", textured_material=True)
    # an untextured model in an otherwise-textured game
    write_gltf(gdir, "bare", pos, tris)
    # a garbage model
    rng = np.random.default_rng(3)
    write_gltf(gdir, "spag", pos, rng.permutation(tris.reshape(-1)).reshape(-1, 3))
    models = [
        {"out_rel": "good.gltf", "triangles": 800, "vertices": 441, "textures": 2},
        {"out_rel": "bare.gltf", "triangles": 800, "vertices": 441, "textures": 0},
        {"out_rel": "spag.gltf", "triangles": 800, "vertices": 441, "textures": 2},
        {"out_rel": "dup.gltf", "triangles": 800, "textures": 0, "duplicate_of": "good.gltf"},
        {"out_rel": "fail.gltf", "triangles": 0, "textures": 0, "error": "boom"},
    ]
    (gdir / "rip_results.json").write_text(
        json.dumps({"game_id": gid, "title": "Test Game", "models": models}), encoding="utf-8"
    )
    report, flags = audit_game(tmp_path, gid)
    assert report["models_scored"] == 3  # duplicate + errored are not scored
    assert report["garbage"] == 1
    assert report["untextured"] == 1
    assert flags[f"{gid}/spag.gltf"]["score"] == "garbage"
    assert flags[f"{gid}/bare.gltf"]["score"] == "untextured"
    assert f"{gid}/good.gltf" not in flags
    assert report["worst"][0]["out_rel"] == "spag.gltf"  # garbage sorts first


def test_audit_game_unreadable_model_is_suspect(tmp_path):
    gid = "GTEST2"
    gdir = tmp_path / gid
    gdir.mkdir()
    models = [{"out_rel": "missing.gltf", "triangles": 100, "vertices": 80, "textures": 1}]
    (gdir / "rip_results.json").write_text(
        json.dumps({"game_id": gid, "title": "T", "models": models}), encoding="utf-8"
    )
    report, flags = audit_game(tmp_path, gid)
    assert flags[f"{gid}/missing.gltf"]["reasons"] == ["unreadable"]
    assert report["suspect"] == 1
