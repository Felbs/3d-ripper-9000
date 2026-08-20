"""Turn recompiled stages into a ready-to-open Godot 4 project.

    gcrip godot out/rip/GZLE01 M_NewD2 sea_r44     # these stages
    gcrip godot out/rip/GZLE01 --all               # every built stage

Writes <ripdir>/godot/ containing project.godot, a third-person player controller,
and one scene per stage: the stage packed as a self-contained .glb (room geometry
nodes carry Godot's `-col` import suffix, so the engine builds static trimesh
collision on import), a sun + sky, and the player standing on the stage's first
spawn point (PLYR entry from the game's own placement data).

Open the folder with Godot 4 (godotengine.org, free/open source) and press F5:
WASD/arrows to walk, mouse to look, Space to jump, Shift to sprint, Esc to
release the mouse. Each stage scene under scenes/ can be run on its own (F6).

glTF and Godot share the same coordinate system (Y-up, right-handed), so game
positions carry straight over; 100 game units are roughly one meter.
"""

from __future__ import annotations

import contextlib
import json
import math
import shutil
import time
from pathlib import Path

from gcrip.export import glb as glbmod

# Godot physical keycodes
_KEYS = {
    "W": 87, "A": 65, "S": 83, "D": 68, "SPACE": 32, "SHIFT": 4194325,
    "LEFT": 4194319, "UP": 4194320, "RIGHT": 4194321, "DOWN": 4194322,
}  # fmt: skip


def _key_event(code: int) -> str:
    return (
        'Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"",'
        '"device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,'
        '"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,'
        f'"physical_keycode":{code},"key_label":0,"unicode":0,"location":0,'
        '"echo":false,"script":null)'
    )


def _action(*codes: int) -> str:
    events = ", ".join(_key_event(c) for c in codes)
    return '{\n"deadzone": 0.5,\n"events": [' + events + "]\n}"


_PLAYER_GD = """extends CharacterBody3D
# gcrip third-person controller. World scale: ~100 game units per meter.

const SPEED := 800.0
const SPRINT := 1800.0
const JUMP := 550.0
const GRAVITY := 1600.0

@onready var arm: SpringArm3D = $SpringArm3D
var start_pos := Vector3.ZERO

func _ready() -> void:
    start_pos = global_position
    Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
        rotation.y -= event.relative.x * 0.003
        arm.rotation.x = clampf(arm.rotation.x - event.relative.y * 0.003, -1.4, 1.4)
    if event.is_action_pressed("ui_cancel"):
        if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
            Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
        else:
            Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _physics_process(delta: float) -> void:
    if not is_on_floor():
        velocity.y -= GRAVITY * delta
    elif Input.is_action_just_pressed("jump"):
        velocity.y = JUMP
    var dir2 := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
    var dir3 := (transform.basis * Vector3(dir2.x, 0.0, dir2.y)).normalized()
    var spd := SPRINT if Input.is_action_pressed("sprint") else SPEED
    velocity.x = dir3.x * spd
    velocity.z = dir3.z * spd
    move_and_slide()
    if global_position.y < start_pos.y - 50000.0:  # fell out of the world
        global_position = start_pos
        velocity = Vector3.ZERO
"""

_PLAYER_TSCN = """[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://player.gd" id="1"]

[sub_resource type="CapsuleShape3D" id="cap"]
radius = 40.0
height = 160.0

[node name="Player" type="CharacterBody3D"]
script = ExtResource("1")

[node name="Collision" type="CollisionShape3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 80, 0)
shape = SubResource("cap")

[node name="SpringArm3D" type="SpringArm3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 160, 0)
spring_length = 450.0
collision_mask = 1

[node name="Camera3D" type="Camera3D" parent="SpringArm3D"]
near = 5.0
far = 1000000.0
"""


def _sun_basis() -> str:
    """DirectionalLight3D basis: pitched down 50deg, turned 30deg."""
    rx, ry = math.radians(-50), math.radians(30)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    # R = Ry @ Rx, column-major columns written row by row for Transform3D
    m = [
        [cy, sy * sx, sy * cx],
        [0.0, cx, -sx],
        [-sy, cy * sx, cy * cx],
    ]
    nums = [m[r][c] for r in range(3) for c in range(3)]
    return ", ".join(f"{v:.5f}" for v in nums)


def _stage_tscn(name: str, spawn: tuple[float, float, float]) -> str:
    x, y, z = spawn
    return f"""[gd_scene load_steps=6 format=3]

[ext_resource type="PackedScene" path="res://stages/{name}.glb" id="1"]
[ext_resource type="PackedScene" path="res://player.tscn" id="2"]

[sub_resource type="ProceduralSkyMaterial" id="sky"]
sky_top_color = Color(0.24, 0.44, 0.72, 1)
sky_horizon_color = Color(0.65, 0.78, 0.9, 1)

[sub_resource type="Sky" id="skyres"]
sky_material = SubResource("sky")

[sub_resource type="Environment" id="env"]
background_mode = 2
sky = SubResource("skyres")
ambient_light_source = 3
tonemap_mode = 2

[node name="{name}" type="Node3D"]

[node name="Level" parent="." instance=ExtResource("1")]

[node name="Sun" type="DirectionalLight3D" parent="."]
transform = Transform3D({_sun_basis()}, 0, 10000, 0)
light_energy = 1.3
shadow_enabled = true

[node name="Env" type="WorldEnvironment" parent="."]
environment = SubResource("env")

[node name="Player" parent="." instance=ExtResource("2")]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {x:.1f}, {y + 30:.1f}, {z:.1f})
"""


def _project_godot(title: str, main_scene: str) -> str:
    k = _KEYS
    return f"""; generated by gcrip godot - open this folder with Godot 4
config_version=5

[application]

config/name={json.dumps(title)}
run/main_scene="res://scenes/{main_scene}.tscn"
config/features=PackedStringArray("4.2")

[input]

move_forward={_action(k["W"], k["UP"])}
move_back={_action(k["S"], k["DOWN"])}
move_left={_action(k["A"], k["LEFT"])}
move_right={_action(k["D"], k["RIGHT"])}
jump={_action(k["SPACE"])}
sprint={_action(k["SHIFT"])}

[rendering]

renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""


def _godot_glb(stage_gltf: Path, out_glb: Path) -> int:
    """Pack a stage for Godot: room-geometry nodes get the -col import suffix so the
    engine builds static trimesh collision for them. Returns collider node count."""
    doc = json.loads(stage_gltf.read_text(encoding="utf-8"))
    groups = {
        i
        for i, n in enumerate(doc.get("nodes", []))
        if (n.get("name") or "").startswith("Room") and "children" in n and "mesh" not in n
    }
    room_children = set()
    for gi in groups:
        name = doc["nodes"][gi].get("name", "")
        if name.endswith("_actors"):
            continue
        room_children.update(doc["nodes"][gi].get("children", []))
    n_col = 0
    for i, node in enumerate(doc.get("nodes", [])):
        if i in room_children and "mesh" in node:
            node["name"] = (node.get("name") or f"room{i}").replace("/", "_") + "-col"
            n_col += 1
    tmp = stage_gltf.with_suffix(".godot.gltf")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    try:
        out_glb.parent.mkdir(parents=True, exist_ok=True)
        out_glb.write_bytes(glbmod.pack(tmp))
    finally:
        tmp.unlink(missing_ok=True)
    return n_col


def export_godot(
    rip_dir: Path,
    stages: list[str] | None = None,
    *,
    out_dir: Path | None = None,
    quiet: bool = False,
) -> dict:
    t0 = time.monotonic()
    rip_dir = Path(rip_dir)
    stages_root = rip_dir / "stages"
    if not stages_root.is_dir():
        raise SystemExit(f"{stages_root} not found - run `gcrip stage <ripdir> ...` first")
    available = {d.name: d for d in stages_root.iterdir() if d.is_dir() and list(d.glob("*.gltf"))}
    if not stages:
        stages = sorted(available, key=str.lower)
    missing = [s for s in stages if s not in available]
    if missing:
        raise SystemExit(
            f"stage(s) not built yet: {', '.join(missing)} - run `gcrip stage` for them first "
            f"(built: {len(available)})"
        )

    out_dir = Path(out_dir) if out_dir else rip_dir / "godot"
    (out_dir / "stages").mkdir(parents=True, exist_ok=True)
    (out_dir / "scenes").mkdir(parents=True, exist_ok=True)

    title = "gcrip level viewer"
    manifest = rip_dir / "disc_manifest.json"
    if manifest.exists():
        with contextlib.suppress(OSError, ValueError, KeyError):
            title = json.loads(manifest.read_text(encoding="utf-8"))["game"]["title"]

    done = []
    for name in stages:
        d = available[name]
        gltf_path = sorted(d.glob("*.gltf"))[0]
        rep = {}
        rep_path = d / f"{gltf_path.stem}_report.json"
        if rep_path.exists():
            try:
                rep = json.loads(rep_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                rep = {}
        spawns = rep.get("spawns") or []
        spawn = tuple(spawns[0]["pos"]) if spawns else (0.0, 500.0, 0.0)
        n_col = _godot_glb(gltf_path, out_dir / "stages" / f"{name}.glb")
        (out_dir / "scenes" / f"{name}.tscn").write_text(
            _stage_tscn(name, spawn), encoding="utf-8"
        )
        done.append(name)
        if not quiet:
            size = (out_dir / "stages" / f"{name}.glb").stat().st_size >> 20
            print(f"  {name:14} {size:4d} MB glb, {n_col} colliders, "
                  f"spawn {tuple(round(v) for v in spawn)}")  # fmt: skip

    (out_dir / "player.gd").write_text(_PLAYER_GD, encoding="utf-8")
    (out_dir / "player.tscn").write_text(_PLAYER_TSCN, encoding="utf-8")
    (out_dir / "project.godot").write_text(_project_godot(title, done[0]), encoding="utf-8")
    seconds = round(time.monotonic() - t0, 1)
    if not quiet:
        print(
            f"{len(done)} stages -> {out_dir}\n"
            f"Open that folder with Godot 4 (godotengine.org) and press F5. "
            f"WASD + mouse, Space jump, Shift sprint, Esc frees the mouse."
        )
    return {"out": str(out_dir), "stages": done, "seconds": seconds}


def clean(out_dir: Path) -> None:
    shutil.rmtree(out_dir, ignore_errors=True)
