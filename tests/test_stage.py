"""DZR/DZS parsing and level glTF merging."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from gcrip.export.gltf_merge import LevelBuilder
from gcrip.formats import dzs

# ---------------------------------------------------------------- dzs builder


def build_dz(chunks: list[tuple[bytes, list[bytes]]]) -> bytes:
    """chunks = [(fourcc, [entry bytes, ...])]; offsets computed like the real files."""
    head = struct.pack(">I", len(chunks))
    table_size = 4 + 12 * len(chunks)
    body = bytearray()
    table = bytearray()
    for cc, entries in chunks:
        off = table_size + len(body)
        table += struct.pack(">4sII", cc, len(entries), off)
        for e in entries:
            body += e
    return head + bytes(table) + bytes(body)


def actor_entry(name: bytes, params=0, pos=(0.0, 0.0, 0.0), rot=(0, 0, 0), enemy=0xFFFF):
    return struct.pack(">8sI3f3hH", name, params, *pos, *rot, enemy)


def scob_entry(name: bytes, scale=(10, 10, 10), **kw):
    return actor_entry(name, **kw) + bytes(scale) + b"\xff"


def mult_entry(tx, tz, ry, room, wave=0):
    return struct.pack(">ffHBb", tx, tz, ry & 0xFFFF, room, wave)


def test_dzs_parse_actors_and_layers():
    data = build_dz(
        [
            (b"ACTR", [actor_entry(b"Bk", params=0x1234, pos=(1, 2, 3), rot=(0, 0x4000, 0))]),
            (b"ACT2", [actor_entry(b"kusax1")]),
            (b"SCOB", [scob_entry(b"Kanban", scale=(20, 10, 5), pos=(-5, 0, 5))]),
            (b"MULT", [mult_entry(-200000.0, 300000.0, 0x8000, 44)]),
        ]
    )
    d = dzs.parse(data)
    assert set(d.chunks) == {"ACTR", "ACT2", "SCOB", "MULT"}
    actr = [p for p in d.placements if p.chunk == "ACTR"]
    assert [p.layer for p in actr] == [-1, 2]
    assert actr[0].name == "Bk" and actr[0].params == 0x1234
    assert actr[0].pos == (1.0, 2.0, 3.0)
    assert math.isclose(actr[0].rot_y_deg, 90.0)
    scob = next(p for p in d.placements if p.chunk == "SCOB")
    assert scob.scale == (2.0, 1.0, 0.5)
    assert scob.pos == (-5.0, 0.0, 5.0)
    t = d.mult[44]
    assert (t.trans_x, t.trans_z) == (-200000.0, 300000.0)
    assert math.isclose(t.rot_y_deg, -180.0)


# ------------------------------------------------------------- merge fixtures


def tiny_gltf(dirpath: Path, name: str, *, hidden_clone=False) -> Path:
    """One triangle with a texture; optionally a hidden variant-clone node."""
    import numpy as np

    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], "<f4")
    idx = np.array([0, 1, 2], "<u2")
    blob = pos.tobytes() + idx.tobytes()
    (dirpath / f"{name}.bin").write_bytes(blob)
    (dirpath / f"{name}_tex").mkdir(exist_ok=True)
    (dirpath / f"{name}_tex" / "t.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0, "translation": [0.0, 2.0, 0.0]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{}],
        "images": [{"uri": f"{name}_tex/t.png"}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
             "min": [0, 0, 0], "max": [1, 1, 0]},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6},
        ],
        "buffers": [{"uri": f"{name}.bin", "byteLength": len(blob)}],
    }
    if hidden_clone:
        doc["nodes"].append(
            {
                "name": f"{name}@clone",
                "mesh": 0,
                "extras": {"gcrip_variant_of": "m"},
                "extensions": {"KHR_node_visibility": {"visible": False}},
            }
        )
        doc["scenes"][0]["nodes"].append(1)
        doc["extensionsUsed"] = ["KHR_node_visibility"]
    p = dirpath / f"{name}.gltf"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_merge_instances_share_meshes(tmp_path: Path):
    a = tiny_gltf(tmp_path, "a")
    b = tiny_gltf(tmp_path, "b", hidden_clone=True)
    out = tmp_path / "level" / "level.gltf"
    lb = LevelBuilder(out, flatten=False)
    assert lb.add_instance(a, "a.0", translation=(10, 0, 0)) is not None
    a1 = lb.add_instance(a, "a.1", translation=(20, 0, 0), rot_y_deg=90, group="Room0")
    assert a1 is not None
    assert lb.add_instance(b, "b.0", scale=(2.0, 2.0, 2.0), group="Room0") is not None
    lb.save()

    doc = json.loads(out.read_text(encoding="utf-8"))
    # two unique models -> two meshes even with three instances
    assert len(doc["meshes"]) == 2
    # hidden clone stripped
    assert not any("clone" in (n.get("name") or "") for n in doc["nodes"])
    assert not any("extensions" in n for n in doc["nodes"])
    # instance roots: a.0 at scene level; Room0 group holds a.1 + b.0
    names = {n.get("name"): i for i, n in enumerate(doc["nodes"])}
    scene_nodes = doc["scenes"][0]["nodes"]
    assert names["a.0"] in scene_nodes and names["Room0"] in scene_nodes
    room0 = doc["nodes"][names["Room0"]]
    assert set(room0["children"]) == {names["a.1"], names["b.0"]}
    # rotation quaternion for 90 deg about Y
    a1 = doc["nodes"][names["a.1"]]
    assert math.isclose(a1["rotation"][1], math.sin(math.radians(45)), rel_tol=1e-6)
    # the second 'a' instance clones the subtree but reuses mesh 0
    kids0 = doc["nodes"][names["a.0"]]["children"]
    kids1 = doc["nodes"][names["a.1"]]["children"]
    assert kids0 != kids1
    assert doc["nodes"][kids0[0]]["mesh"] == doc["nodes"][kids1[0]]["mesh"]
    # inner node TRS preserved on the clone
    assert doc["nodes"][kids1[0]]["translation"] == [0.0, 2.0, 0.0]
    # image URIs relative to the level dir
    assert all(img["uri"].startswith("../") for img in doc["images"])
    # single merged buffer exists and is 4-aligned per model
    assert (out.parent / "level.bin").stat().st_size >= 84
    # accessors of the second model rebased past the first model's bufferViews
    assert doc["accessors"][2]["bufferView"] == 2


def test_merge_skinned_instance_gets_own_skin(tmp_path: Path):
    import numpy as np

    ibm = np.eye(4, dtype="<f4").tobytes()
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], "<f4").tobytes()
    blob = pos + ibm
    (tmp_path / "s.bin").write_bytes(blob)
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0, 2]}],
        "nodes": [
            {"name": "joint"},
            {"name": "skinned", "mesh": 0, "skin": 0},
            {"name": "wrap", "children": [1]},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "skins": [{"inverseBindMatrices": 1, "joints": [0], "skeleton": 0}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 1, "type": "MAT4"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 64},
        ],
        "buffers": [{"uri": "s.bin", "byteLength": len(blob)}],
    }
    src = tmp_path / "s.gltf"
    src.write_text(json.dumps(doc), encoding="utf-8")

    out = tmp_path / "lvl" / "lvl.gltf"
    lb = LevelBuilder(out, flatten=False)
    assert lb.add_instance(src, "s.0") is not None
    assert lb.add_instance(src, "s.1", translation=(5, 0, 0)) is not None
    lb.save()
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert len(merged["skins"]) == 2
    j0 = merged["skins"][0]["joints"]
    j1 = merged["skins"][1]["joints"]
    assert j0 != j1  # each instance poses its own joints
    assert merged["skins"][0]["inverseBindMatrices"] == merged["skins"][1]["inverseBindMatrices"]
    skinned = [n for n in merged["nodes"] if n.get("name") == "skinned"]
    assert sorted(n["skin"] for n in skinned) == [0, 1]


def test_flatten_bakes_transforms_and_drops_rigs(tmp_path: Path):
    a = tiny_gltf(tmp_path, "a", hidden_clone=True)
    out = tmp_path / "flat" / "flat.gltf"
    lb = LevelBuilder(out)  # flatten is the default
    assert lb.add_instance(a, "a.0") is not None
    assert lb.add_instance(a, "a.1", translation=(100, 0, 0)) is not None
    lb.save()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert "skins" not in doc
    # one combined mesh, two single-node instances carrying it directly
    assert len(doc["meshes"]) == 1
    inst = [n for n in doc["nodes"] if "mesh" in n]
    assert len(inst) == 2 and all("children" not in n for n in inst)
    # the source node's translation [0,2,0] is baked into POSITION bounds
    pos_acc = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert pos_acc["min"][1] == 2.0 and pos_acc["max"][1] == 3.0
    # instance placement stays on the node
    assert doc["nodes"][[i for i, n in enumerate(doc["nodes"]) if n.get("name") == "a.1"][0]][
        "translation"
    ] == [100.0, 0.0, 0.0]


def scls_entry(dest: bytes, spawn=0, room=0, fade=0):
    return struct.pack(">8s3Bb", dest, spawn, room, fade, -1)


def test_dzs_parse_scls():
    data = build_dz([(b"SCLS", [scls_entry(b"Ojhous", 3, 44), scls_entry(b"sea", 1, 2)])])
    d = dzs.parse(data)
    assert len(d.scls) == 2
    assert d.scls[0].dest_stage == "Ojhous"
    assert (d.scls[0].spawn, d.scls[0].room) == (3, 44)
    assert d.scls[1].dest_stage == "sea"


def test_bind_exits_by_arrival_inversion():
    from gcrip.formats.dzs import Exit
    from gcrip.stage import _bind_exits

    class FakeDisc:
        def all_scls(self):
            return {
                "Ojhous": [Exit("sea", 3, 44, 0)],   # interior returns to sea r44 spawn 3
                "Omasao": [Exit("sea", 5, 44, 0)],
                "Nowhere": [Exit("sea", 9, 40, 0)],  # returns to a different island
            }

        def incoming_exits(self, stage_name):
            out = set()
            for other, entries in self.all_scls().items():
                for e in entries:
                    if e.dest_stage == stage_name:
                        out.add((other, e.room, e.spawn))
            return sorted(out)

    own = [Exit("Ojhous", 0, 0, 0), Exit("Omasao", 0, 0, 0)]  # sea's exit table
    doors = [
        {"room": 44, "pos": [100.0, 0.0, 100.0], "rot": 0.0},
        {"room": 44, "pos": [900.0, 0.0, 900.0], "rot": 90.0},
    ]
    spawns = [
        {"room": 44, "id": 3, "pos": [150.0, 0.0, 100.0], "rot_y_deg": 0.0},
        {"room": 44, "id": 5, "pos": [900.0, 0.0, 850.0], "rot_y_deg": 0.0},
        {"room": 40, "id": 9, "pos": [99999.0, 0.0, 0.0], "rot_y_deg": 0.0},
    ]
    exits = _bind_exits(FakeDisc(), "sea", own, doors, spawns)
    got = {e["dest_stage"]: e["pos"] for e in exits}
    assert got == {"Ojhous": [100.0, 0.0, 100.0], "Omasao": [900.0, 0.0, 900.0]}
