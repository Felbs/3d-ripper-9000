"""Godot project generation from recompiled stages."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from gcrip.export.gltf_merge import LevelBuilder
from gcrip.godot import export_godot
from tests.test_stage import tiny_gltf


def _fake_rip(tmp_path: Path) -> Path:
    rip = tmp_path / "rip"
    model = tiny_gltf(tmp_path, "prop")
    stage_dir = rip / "stages" / "TestStage"
    lb = LevelBuilder(stage_dir / "TestStage.gltf")
    lb.add_instance(model, "Room0/model", translation=(5, 0, 5), group="Room0")
    lb.add_instance(model, "pot.0", translation=(7, 0, 7), group="Room0_actors")
    lb.save()
    (stage_dir / "TestStage_report.json").write_text(
        json.dumps(
            {
                "stage": "TestStage",
                "spawns": [{"room": 0, "pos": [5.0, 1.0, 5.0], "rot_y_deg": 90.0}],
            }
        )
    )
    return rip


def _glb_json(path: Path) -> dict:
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    n = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + n])


def test_export_godot_project(tmp_path: Path):
    rip = _fake_rip(tmp_path)
    res = export_godot(rip, quiet=True)
    out = Path(res["out"])
    assert res["stages"] == ["TestStage"]

    proj = (out / "project.godot").read_text(encoding="utf-8")
    assert 'run/main_scene="res://scenes/TestStage.tscn"' in proj
    assert "move_forward" in proj and "rendering_method" in proj
    assert (out / "player.gd").exists() and (out / "player.tscn").exists()

    tscn = (out / "scenes" / "TestStage.tscn").read_text(encoding="utf-8")
    assert 'path="res://stages/TestStage.glb"' in tscn
    assert "DirectionalLight3D" in tscn and "WorldEnvironment" in tscn
    assert "5.0, 31.0, 5.0" in tscn  # player at spawn, lifted 30 units

    doc = _glb_json(out / "stages" / "TestStage.glb")
    names = [n.get("name", "") for n in doc["nodes"]]
    # room geometry gets the -col import suffix; actor props stay walk-through
    assert any(n.endswith("-col") for n in names)
    assert any(n == "pot.0" for n in names)
    # self-contained: images are buffer views, not file URIs
    assert all("uri" not in img for img in doc.get("images", []))


def test_export_godot_needs_built_stages(tmp_path: Path):
    rip = tmp_path / "rip"
    (rip / "stages").mkdir(parents=True)
    try:
        export_godot(rip, ["Nope"], quiet=True)
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "not built yet" in str(e)
