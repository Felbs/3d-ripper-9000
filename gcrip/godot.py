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

# ruff: noqa: E501 - embedded GDScript/tscn templates
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
    "W": 87, "A": 65, "S": 83, "D": 68, "SPACE": 32, "SHIFT": 4194325, "CTRL": 4194326,
    "ESC": 4194305, "F1": 4194332,
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


def _joy_button(index: int) -> str:
    return (
        'Object(InputEventJoypadButton,"resource_local_to_scene":false,"resource_name":"",'
        f'"device":-1,"button_index":{index},"pressure":0.0,"pressed":false,"script":null)'
    )


def _joy_axis(axis: int, value: float) -> str:
    return (
        'Object(InputEventJoypadMotion,"resource_local_to_scene":false,"resource_name":"",'
        f'"device":-1,"axis":{axis},"axis_value":{value:.1f},"script":null)'
    )


def _action(*events: int | str, deadzone: float = 0.5) -> str:
    """Keys are given as ints (physical keycodes); pre-serialized joypad events as str."""
    parts = [_key_event(e) if isinstance(e, int) else e for e in events]
    return '{\n"deadzone": ' + f"{deadzone}" + ',\n"events": [' + ", ".join(parts) + "]\n}"


# Godot's SDL-mapped joypad ids (valid once the pad is known or calibrated)
JOY_A, JOY_B, JOY_X, JOY_Y = 0, 1, 2, 3
JOY_START, JOY_LSHOULDER, JOY_RSHOULDER = 6, 9, 10
AXIS_LX, AXIS_LY, AXIS_RX, AXIS_RY, AXIS_LT, AXIS_RT = 0, 1, 2, 3, 4, 5


_PLAYER_GD = """extends CharacterBody3D
# gcrip: Link's controller, driven by the real Wind Waker tuning constants.
#
# Every number below comes from zeldaret/tww  src/d/actor/d_a_player_HIO_data.inc,
# named by the memRip sweep (knowledge/gamecube/link-movement-constants.md). The
# game runs at 30 fps and its constants are per FRAME (units/frame, units/frame^2,
# frames, s16 angles where 0x8000 = 180 deg), so this project runs physics at 30 Hz
# and applies them 1:1. ~100 units = 1 m.

# --- move (daPy_HIO_move_c0) ---
const RUN_SPEED_MAX := 17.0          # move.run_speed_max          units/frame
const RUN_ACCEL := 3.5               # move.run_accel              units/frame^2 (x stick)
const DECEL_SCALE := 0.6             # move.decel_scale            remove 60% of remaining/frame
const DECEL_MIN_STEP := 1.8          # move.decel_min_step
const DECEL_MAX_STEP := 2.5          # move.decel_max_step
const WALK_RATIO := 0.5              # move.walk_speed_ratio       walk anim fully in
const TURN_MAX_STEP := 3000          # move.turn_yaw_max_step      s16/frame (16.5 deg)
const TURN_MIN_STEP := 100           # move.turn_yaw_min_step      s16/frame (0.55 deg)
const TURN_DIVISOR := 5.0            # move.turn_yaw_scale
# --- Z-target strafing (atnMove / atnMoveB) ---
const STRAFE_SPEED_MAX := 12.0       # atnMove.atn_strafe_speed_max
const STRAFE_BACK_MAX := 15.0        # atnMoveB.back_max_speed
const STRAFE_ACCEL := 5.0            # atnMove.atn_strafe_accel
const STRAFE_BACK_ACCEL := 2.5       # atnMoveB.back_accel
# --- gravity / air (autoJump) ---
const GRAVITY := -2.5                # autoJump.default_gravity     units/frame^2
const MAX_FALL_SPEED := -175.0       # autoJump.default_max_fall_speed
const AUTOJUMP_MIN_SPEED := 9.0      # autoJump.jump_min_speed
const AUTOJUMP_SCALE := 1.6          # autoJump.jump_speed_scale
const AUTOJUMP_ANGLE := 11000        # autoJump.jump_launch_angle   s16 (60.4 deg)
const AIR_ACCEL := 0.4               # autoJump.air_accel_to_run_speed
# --- backflip / side hop ---
const BACKFLIP_SPEED := 22.5         # backJump.backjump_speed
const BACKFLIP_SPEED_Y := 19.0       # backJump.backjump_speed_y
const BACKFLIP_GRAVITY := -3.0       # backJump.backjump_gravity
const SIDEHOP_SPEED := 30.0          # sideStep.hop_launch_speed
const SIDEHOP_ANGLE := 6200          # sideStep.hop_launch_angle    s16 (34.1 deg)
const SIDEHOP_GRAVITY := -2.4        # sideStep.hop_gravity
# --- roll ---
const ROLL_SPEED_MULT := 1.5         # roll.roll_speed_mult
const ROLL_SPEED_ADD := 0.5          # roll.roll_speed_add
const ROLL_SPEED_MIN := 5.0          # roll.roll_speed_min
const ROLL_FRAMES := 17              # roll.roll_anim_end_frame 19 at rate 1.1
const ROLL_CANCEL_FRAME := 15        # roll.roll_cancel_frame (17 anim frames / 1.1)
const ROLL_CRASH_MIN_SPEED := 10.0   # roll.crash_min_speed
const ROLL_CRASH_REBOUND := 0.4      # roll.crash_rebound_speed_mult
const ROLL_CRASH_REBOUND_Y := 7.0    # roll.crash_rebound_speed_y
# --- slip (sudden reversal) ---
const SLIP_RATIO := 0.6              # slip.slip_speed_ratio_threshold
# --- swim ---
const SWIM_SPEED_MAX := 18.0         # swim.swim_speed_max (x stick^2)
const SWIM_APPROACH_SCALE := 0.02    # swim.speed_approach_scale
const SWIM_APPROACH_MIN := 0.5       # swim.speed_approach_min_step
const SWIM_APPROACH_MAX := 2.0       # swim.speed_approach_max_step
const SWIM_TURN_MAX := 5000          # swim.turn_max_step  s16 (27.5 deg)
const SWIM_TURN_MIN := 1200          # swim.turn_min_step  s16 (6.6 deg)
const SWIM_TURN_DIVISOR := 17.0      # swim.turn_divisor
const SWIM_START_DEPTH := 90.0       # swim.swim_start_depth
const SWIM_RISE_ACCEL := 6.0         # swim.rise_accel
const SWIM_RISE_MAX := 9.5           # swim.rise_speed_max
# --- fall damage (fall.fall_height_damage*_m, meters x100) ---
const FALL_HARD_LANDING := 1000.0    # half the 1-heart height: hard landing, no damage
const FALL_DAMAGE_1 := 2000.0        # 1 heart
const FALL_DAMAGE_2 := 6000.0        # 2 hearts
# --- misc ---
const WALL_PUSH_REDUCE := 0.6        # basic.wall_push_speed_reduce
const ANIM_BLEND := 2.4 / 30.0       # basic.default_anm_morf_frames (2.4 frames)
# --- sword (cut / cutA / cutF / cutR / cutL / cutEA / cutEB / cutJump tables) ---
# per swing: clip, anim rate, start frame, end frame, cancel frame, lunge frame,
# lunge speed (base + 0.2 x entry speed), decel (scale, min, max), hit window [start, end)
const CUTS := {
    "cuta":  {"rate": 1.2, "start": 4.0, "end": 19, "cancel": 16.0, "lunge_f": 6.0, "lunge": 10.0, "dec": [0.7, 0.5, 2.6],  "hit": [5.0, 11.0]},
    "cutf":  {"rate": 1.2, "start": 4.0, "end": 19, "cancel": 17.0, "lunge_f": 6.0, "lunge": 8.0,  "dec": [0.7, 0.5, 0.95], "hit": [5.0, 12.0]},
    "cutr":  {"rate": 1.2, "start": 4.0, "end": 19, "cancel": 16.0, "lunge_f": 6.0, "lunge": 1.0,  "dec": [0.7, 0.5, 0.95], "hit": [6.0, 12.0]},
    "cutl":  {"rate": 1.2, "start": 4.0, "end": 18, "cancel": 16.0, "lunge_f": 6.0, "lunge": 1.0,  "dec": [0.7, 0.5, 0.95], "hit": [5.0, 10.0]},
    "cutea": {"rate": 1.0, "start": 4.0, "end": 19, "cancel": 99.0, "lunge_f": 6.0, "lunge": 15.0, "dec": [0.7, 0.5, 4.0],  "hit": [5.0, 11.0]},
    "cuteb": {"rate": 0.9, "start": 4.0, "end": 19, "cancel": 99.0, "lunge_f": 6.0, "lunge": 7.0,  "dec": [0.7, 0.5, 1.5],  "hit": [5.0, 11.0]},
}
const CUT_LUNGE_CARRY := 0.2         # cutX.lunge_speed_carry_ratio
const COMBO_WINDOW_FRAMES := 2       # cutX.combo_window_frames (m3522)
const SWORD_RADIUS := 20.0           # cut.hero_sword_at_radius
const SWORD_LENGTH_SCALE := 1.5      # cut.hero_sword_at_length_scale
const JATTACK := {"rate": 0.74, "start": 2.0, "end": 15, "speed": 18.0, "speed_y": 27.0, "gravity": -3.0, "hit": [13.0, 15.0]}
const JATTACK_AIR := {"rate": 0.8, "start": 1.0, "end": 15, "speed": 9.0, "speed_y": 18.0, "gravity": -3.0, "hit": [13.0, 15.0]}
const JATTACK_LAND := {"rate": 1.1, "start": 1.0, "end": 14, "cancel": 12.0}
# --- damage (dam / damage / laDamage tables) ---
const DAMAGE_INVINCIBLE_FRAMES := 30    # dam.damage_invincible_frames
const DAMAGE_ANIM := {"rate": 0.6, "start": 0.0, "end": 9}
const DAMAGE_KNOCKBACK_BASE := 13.0     # damage.damage_knockback_speed_base
const DAMAGE_KNOCKBACK_PER_VEC := 0.05  # damage.damage_knockback_speed_per_damage_vec
const DAMAGE_DECEL := [0.5, 0.25, 1.2]  # damage.damage_decel_scale / min / max
const LARGE_DAMAGE_SPEED := 25.0        # laDamage.fly_speed
const LARGE_DAMAGE_SPEED_Y := 60.0      # laDamage.fly_yspeed
const LARGE_DAMAGE_GRAVITY := -13.0     # laDamage.fly_gravity
const MAX_HEARTS_START := 3             # quarter hearts: 12

const S16_TO_RAD := PI / 32768.0

enum State { GROUND, AIR, ROLL, SWIM, LAND, ATTACK, JUMPCUT, JUMPCUT_LAND, DAMAGE }

@export var water_level := -1.0e9   # stage sets this (sea stages: 0)

@onready var cam_yaw: Node3D = $CamYaw
@onready var arm: SpringArm3D = $CamYaw/SpringArm3D
@onready var model: Node3D = get_node_or_null("Model")
var anim: AnimationPlayer = null
var current_clip := ""
var start_pos := Vector3.ZERO

var state: int = State.GROUND
var facing := 0.0          # radians, Link's heading (model faces +Z -> rotation.y = facing)
var speed := 0.0           # forward ground speed, units/frame
var air_vel := Vector3.ZERO  # horizontal velocity while airborne, units/frame
var gravity := GRAVITY
var roll_frame := 0
var land_frames := 0
var fall_start_y := 0.0
var strafe := Vector2.ZERO  # strafe velocity (x right, y forward) in target mode
var swim_speed := 0.0

# combat
var hearts_max := MAX_HEARTS_START * 4   # quarter hearts
var hearts := MAX_HEARTS_START * 4
var invincible := 0                      # frames
var combo := 0                           # m34C4: swings in the current chain
var combo_timer := 0                     # m3522
var cut: Dictionary = {}
var cut_frame := 0.0                     # current animation frame of the swing
var cut_entry_speed := 0.0
var hit_targets := {}                    # bodies already hit by this swing
var jattack: Dictionary = {}
var damage_dir := Vector3.ZERO
@onready var sword_pivot: Node3D = get_node_or_null("SwordPivot")
@onready var sword_area: Area3D = get_node_or_null("SwordPivot/SwordHit")
@onready var sword_shape: CollisionShape3D = get_node_or_null("SwordPivot/SwordHit/Shape")
@onready var hud_hearts: Label = get_node_or_null("HUD/Hearts")

func _ready() -> void:
    start_pos = global_position
    fall_start_y = global_position.y
    facing = model.rotation.y if model else 0.0
    Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
    if model:
        anim = model.find_child("AnimationPlayer", true, false)
    add_to_group("player")
    _sword_active(false)
    _update_hud()

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
        _orbit(event.relative.x * 0.003, event.relative.y * 0.003)
    if event.is_action_pressed("ui_cancel"):
        if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
            Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
        else:
            Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _orbit(dx: float, dy: float) -> void:
    cam_yaw.rotation.y -= dx
    arm.rotation.x = clampf(arm.rotation.x - dy, -1.4, 1.4)

func play_clip(name: String, blend := ANIM_BLEND, rate := 1.0) -> void:
    if anim == null:
        return
    if anim.has_animation(name):
        if current_clip != name:
            anim.play(name, blend)
            current_clip = name
        anim.speed_scale = rate

# ---------------------------------------------------------------- helpers

func stick() -> Vector2:
    # camera-relative stick: x = right, y = forward, length 0..1
    var raw := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
    return Vector2(raw.x, -raw.y)

func stick_world_dir(s: Vector2) -> Vector3:
    var d := cam_yaw.global_transform.basis * Vector3(s.x, 0.0, -s.y)
    d.y = 0.0
    return d.normalized() if d.length() > 0.001 else Vector3.ZERO

func heading_of(dir: Vector3) -> float:
    return atan2(dir.x, dir.z)

func turn_toward(target: float, max_step: int, min_step: int, divisor: float) -> void:
    # cLib_addCalcAngleS: step = remaining / divisor, clamped to [min, max] (s16 units)
    var remaining := wrapf(target - facing, -PI, PI)
    var step := absf(remaining) / divisor
    step = clampf(step, min_step * S16_TO_RAD, max_step * S16_TO_RAD)
    if absf(remaining) <= step:
        facing = target
    else:
        facing += signf(remaining) * step
    facing = wrapf(facing, -PI, PI)

func forward() -> Vector3:
    return Vector3(sin(facing), 0.0, cos(facing))

func water_surface() -> float:
    # Height of the water surface above Link's feet, or -1e9 if none. Probes the liquid
    # colliders (layer 2) exported from the game's .dzb, with the stage's flat water
    # level (the open sea) as a fallback.
    var best := water_level
    var space := get_world_3d().direct_space_state
    var from := global_position + Vector3(0, 4000.0, 0)
    var to := global_position - Vector3(0, 20.0, 0)
    var q := PhysicsRayQueryParameters3D.create(from, to, 2)
    q.hit_from_inside = true
    var hit := space.intersect_ray(q)
    if hit:
        best = maxf(best, hit.position.y)
    return best

func in_water() -> bool:
    return global_position.y < water_surface() - SWIM_START_DEPTH

func on_hazard() -> String:
    # standing on lava / poison (layer 4 colliders carry a "liquid" meta)
    for i in get_slide_collision_count():
        var c := get_slide_collision(i).get_collider()
        if c and c.has_meta("liquid") and c.get_meta("liquid") != "water":
            return c.get_meta("liquid")
    return ""

# ---------------------------------------------------------------- states

func _physics_process(_delta: float) -> void:
    # right stick (C-stick) orbits the camera when a pad is mapped
    var cx := Input.get_joy_axis(0, JOY_AXIS_RIGHT_X)
    var cy := Input.get_joy_axis(0, JOY_AXIS_RIGHT_Y)
    if absf(cx) > 0.2 or absf(cy) > 0.2:
        _orbit(cx * 0.06, cy * 0.04)

    if invincible > 0:
        invincible -= 1
        if model:
            model.visible = (invincible / 2) % 2 == 0  # damage flicker
    elif model and not model.visible:
        model.visible = true
    if combo_timer > 0:
        combo_timer -= 1
        if combo_timer == 0 and state != State.ATTACK:
            combo = 0

    match state:
        State.GROUND: _ground()
        State.AIR: _air()
        State.ROLL: _roll()
        State.SWIM: _swim()
        State.LAND: _land()
        State.ATTACK: _attack()
        State.JUMPCUT: _jumpcut()
        State.JUMPCUT_LAND: _jumpcut_land()
        State.DAMAGE: _damage()

    if model:
        model.rotation.y = facing
    if sword_pivot:
        sword_pivot.rotation.y = facing

    if global_position.y < start_pos.y - 50000.0:  # fell out of the world
        global_position = start_pos
        velocity = Vector3.ZERO
        _enter_ground()

func _apply(h: Vector3, vy: float) -> void:
    # h = horizontal velocity in units/frame; Godot wants units/second
    velocity = Vector3(h.x, vy, h.z) * 30.0
    move_and_slide()

func _enter_ground() -> void:
    state = State.GROUND
    gravity = GRAVITY

func _ground() -> void:
    if in_water():
        _enter_swim()
        return
    if on_hazard() != "":  # lava / poison: no hearts yet, so back to the start point
        global_position = start_pos
        velocity = Vector3.ZERO
        speed = 0.0
        return
    var s := stick()
    var dist := minf(s.length(), 1.0)
    var targeting := Input.is_action_pressed("target")

    if targeting:
        _ground_strafe(s, dist)
        return

    # free movement: turn toward the stick, move along the facing
    if dist > 0.05:
        var want := heading_of(stick_world_dir(s))
        var off := absf(wrapf(want - facing, -PI, PI))
        if off > PI * 0.6 and speed > SLIP_RATIO * RUN_SPEED_MAX:
            speed *= 0.5  # slip: sudden reversal scrubs speed (slip.slip_entry then decel)
        turn_toward(want, TURN_MAX_STEP, TURN_MIN_STEP, TURN_DIVISOR)
        var target_speed := RUN_SPEED_MAX * dist
        if speed < target_speed:
            speed = minf(speed + RUN_ACCEL * dist, target_speed)
        else:
            _decel_to(target_speed)
    else:
        _decel_to(0.0)

    if Input.is_action_just_pressed("action_b"):
        _enter_attack(s)
        return
    if Input.is_action_just_pressed("action_a") and speed > 1.0:
        _enter_roll()
        return

    var was_on_floor := is_on_floor()
    _apply(forward() * speed, -1.0)  # small downward push keeps floor contact on slopes
    if is_on_wall():
        speed *= 1.0 - WALL_PUSH_REDUCE * 0.5
    if was_on_floor and not is_on_floor():
        if speed >= AUTOJUMP_MIN_SPEED:
            _enter_air_autojump()
        else:
            _enter_air(forward() * speed, 0.0, GRAVITY)
        return
    if not is_on_floor():
        _enter_air(forward() * speed, 0.0, GRAVITY)
        return

    var ratio := speed / RUN_SPEED_MAX
    if ratio < 0.03:
        play_clip("wait")
    elif ratio < WALK_RATIO + 0.15:
        play_clip("walk", ANIM_BLEND, maxf(ratio / WALK_RATIO, 0.4))
    else:
        play_clip("dash", ANIM_BLEND, maxf(ratio, 0.6))

func _decel_to(target: float) -> void:
    var remaining := speed - target
    if remaining <= 0.0:
        speed = target
        return
    var step := clampf(remaining * DECEL_SCALE, DECEL_MIN_STEP, DECEL_MAX_STEP)
    speed = maxf(speed - step, target)

func _ground_strafe(s: Vector2, dist: float) -> void:
    # Z-target: face the camera direction, strafe with atnMove constants
    var cam_fwd := -cam_yaw.global_transform.basis.z
    cam_fwd.y = 0.0
    facing = heading_of(cam_fwd.normalized())
    var want := Vector2(s.x * STRAFE_SPEED_MAX, s.y * (STRAFE_BACK_MAX if s.y < 0.0 else STRAFE_SPEED_MAX))
    var accel := STRAFE_BACK_ACCEL if s.y < 0.0 else STRAFE_ACCEL
    strafe = strafe.move_toward(want, accel)
    speed = strafe.length()

    if Input.is_action_just_pressed("action_b"):
        _enter_attack(s)
        return
    if Input.is_action_just_pressed("action_a"):
        if s.y > 0.5:  # Z-target + A + forward = jump attack
            _enter_jumpcut(JATTACK)
            return
        if s.y < -0.5:
            _enter_air(-forward() * BACKFLIP_SPEED, BACKFLIP_SPEED_Y, BACKFLIP_GRAVITY)
            return
        if absf(s.x) > 0.5:
            var side := cam_yaw.global_transform.basis.x * signf(s.x)
            side.y = 0.0
            var a := SIDEHOP_ANGLE * S16_TO_RAD
            _enter_air(side.normalized() * SIDEHOP_SPEED * cos(a), SIDEHOP_SPEED * sin(a), SIDEHOP_GRAVITY)
            return

    var right := cam_yaw.global_transform.basis.x
    right.y = 0.0
    var h := right.normalized() * strafe.x + forward() * strafe.y
    _apply(h, -1.0)
    if not is_on_floor():
        _enter_air(h, 0.0, GRAVITY)
        return
    if speed < 0.5:
        play_clip("wait")
    else:
        play_clip("walk", ANIM_BLEND, clampf(speed / STRAFE_SPEED_MAX, 0.5, 1.2))

func _enter_air(h: Vector3, vy: float, g: float) -> void:
    state = State.AIR
    air_vel = h
    velocity.y = vy * 30.0
    gravity = g
    fall_start_y = global_position.y
    play_clip("mjmp", 0.1)

func _enter_air_autojump() -> void:
    # running off a ledge: v = clamp(speed, 9, 17) * 1.6 along the launch angle
    var v := clampf(speed, AUTOJUMP_MIN_SPEED, RUN_SPEED_MAX) * AUTOJUMP_SCALE
    var a := AUTOJUMP_ANGLE * S16_TO_RAD
    _enter_air(forward() * v * cos(a), v * sin(a), GRAVITY)

func _air() -> void:
    if in_water():
        _enter_swim()
        return
    if Input.is_action_just_pressed("action_b"):  # midair jump attack
        _enter_jumpcut(JATTACK_AIR)
        return
    fall_start_y = maxf(fall_start_y, global_position.y)
    var vy := velocity.y / 30.0 + gravity
    vy = maxf(vy, MAX_FALL_SPEED)
    # air control: horizontal speed chases the stick at 0.4 units/frame^2
    var s := stick()
    if s.length() > 0.1:
        var want := stick_world_dir(s) * RUN_SPEED_MAX * minf(s.length(), 1.0)
        air_vel = air_vel.move_toward(want, AIR_ACCEL)
        if not Input.is_action_pressed("target"):
            turn_toward(heading_of(air_vel) if air_vel.length() > 0.5 else facing, TURN_MAX_STEP, TURN_MIN_STEP, TURN_DIVISOR)
    _apply(air_vel, vy)
    if is_on_floor():
        var drop := fall_start_y - global_position.y
        speed = air_vel.length()
        if drop >= FALL_DAMAGE_2:
            land_frames = 40
            state = State.LAND
            play_clip("jmped", 0.05)
            if drop >= FALL_DAMAGE_2 * 2.0:  # no HP yet: a truly huge fall respawns
                global_position = start_pos
        elif drop >= FALL_DAMAGE_1:
            land_frames = 30
            state = State.LAND
            play_clip("jmped", 0.05)
        elif drop >= FALL_HARD_LANDING:
            land_frames = 12
            state = State.LAND
            play_clip("jmped", 0.05)
        else:
            _enter_ground()
            play_clip("jmped", 0.05)

func _land() -> void:
    land_frames -= 1
    _decel_to(0.0)
    _apply(forward() * speed, -1.0)
    if land_frames <= 0:
        _enter_ground()

func _enter_roll() -> void:
    state = State.ROLL
    roll_frame = 0
    speed = maxf(ROLL_SPEED_MULT * speed + ROLL_SPEED_ADD, ROLL_SPEED_MIN)
    speed = minf(speed, ROLL_SPEED_MULT * RUN_SPEED_MAX + ROLL_SPEED_ADD)
    play_clip("mrolll", 0.05, 1.1)

func _roll() -> void:
    roll_frame += 1
    var s := stick()
    if s.length() > 0.3:  # the roll steers a little toward the stick
        turn_toward(heading_of(stick_world_dir(s)), TURN_MAX_STEP / 3, TURN_MIN_STEP, TURN_DIVISOR)
    _apply(forward() * speed, -1.0)
    if is_on_wall() and speed >= ROLL_CRASH_MIN_SPEED and roll_frame >= 6 and roll_frame <= 15:
        # crashed into a wall: bounce back and up
        _enter_air(-forward() * speed * ROLL_CRASH_REBOUND, ROLL_CRASH_REBOUND_Y, GRAVITY)
        speed = 0.0
        return
    if not is_on_floor():
        _enter_air(forward() * speed, 0.0, GRAVITY)
        return
    if roll_frame >= ROLL_CANCEL_FRAME and Input.is_action_just_pressed("action_a"):
        _enter_roll()  # chained roll
        return
    if roll_frame >= ROLL_FRAMES:
        speed = minf(speed, RUN_SPEED_MAX)
        _enter_ground()

# ---------------------------------------------------------------- sword

func _sword_active(on: bool) -> void:
    if sword_shape:
        sword_shape.disabled = not on
    if not on:
        hit_targets.clear()

func _cut_dir(s: Vector2) -> String:
    # stick direction relative to Link's facing: forward / right / left / none
    if s.length() < 0.3:
        return "none"
    var want := heading_of(stick_world_dir(s))
    var off := wrapf(want - facing, -PI, PI)
    if absf(off) < PI / 4.0:
        return "forward"
    return "right" if off < 0.0 else "left"

func _enter_attack(s: Vector2) -> void:
    # changeCutProc: swings 1-3 by stick direction, the 4th is a finisher (EA/EB)
    combo += 1
    var d := _cut_dir(s)
    var clip := ""
    if combo >= 4:
        clip = "cutea" if d in ["right", "forward"] else "cuteb"
    elif d == "forward":
        clip = "cutf"
    elif d == "right":
        clip = "cutr"
    elif d == "none" and Input.is_action_pressed("target"):
        clip = "cuta"
    else:
        clip = "cutl"
    if d != "none" and not Input.is_action_pressed("target"):
        facing = heading_of(stick_world_dir(s))
    cut = CUTS[clip]
    cut_frame = cut["start"]
    cut_entry_speed = absf(speed)
    state = State.ATTACK
    hit_targets.clear()
    play_clip(clip, 2.5 / 30.0, cut["rate"])
    if anim and anim.has_animation(clip):
        anim.seek(cut["start"] / 30.0, true)

func _attack() -> void:
    var prev := cut_frame
    cut_frame += cut["rate"]
    if prev < cut["lunge_f"] and cut_frame >= cut["lunge_f"]:
        speed = cut_entry_speed * CUT_LUNGE_CARRY + cut["lunge"]
    else:
        var dec: Array = cut["dec"]
        var step := clampf(speed * dec[0], dec[1], dec[2])
        speed = maxf(speed - step, 0.0)
    var hit: Array = cut["hit"]
    var active: bool = cut_frame >= hit[0] and cut_frame < hit[1]
    _sword_active(active)
    if active:
        _sword_sweep()
    _apply(forward() * speed, -1.0)
    combo_timer = COMBO_WINDOW_FRAMES
    if combo >= 4 and cut_frame >= cut["end"]:
        combo = 0
    if cut_frame > cut["cancel"] or cut_frame >= cut["end"]:
        var s := stick()
        if Input.is_action_just_pressed("action_b") and combo < 4:
            _sword_active(false)
            _enter_attack(s)
            return
        if Input.is_action_just_pressed("action_a") and s.length() > 0.3:
            _sword_active(false)
            combo = 0
            _enter_roll()
            return
        if cut_frame >= cut["end"]:
            _sword_active(false)
            if combo >= 4:
                combo = 0
            _enter_ground()
            return
    if not is_on_floor():
        _sword_active(false)
        _enter_air(forward() * speed, 0.0, GRAVITY)

func _sword_sweep() -> void:
    if sword_area == null:
        return
    for body in sword_area.get_overlapping_bodies():
        if body == self or hit_targets.has(body):
            continue
        hit_targets[body] = true
        if body.has_method("take_hit"):
            body.take_hit(1, global_position)
    for area in sword_area.get_overlapping_areas():
        if hit_targets.has(area):
            continue
        hit_targets[area] = true
        if area.has_method("take_hit"):
            area.take_hit(1, global_position)

func _enter_jumpcut(p: Dictionary) -> void:
    jattack = p
    state = State.JUMPCUT
    cut_frame = p["start"]
    air_vel = forward() * p["speed"]
    velocity.y = p["speed_y"] * 30.0
    gravity = p["gravity"]
    fall_start_y = global_position.y
    hit_targets.clear()
    play_clip("jattack", 1.0 / 30.0, p["rate"])
    if anim and anim.has_animation("jattack"):
        anim.seek(p["start"] / 30.0, true)

func _jumpcut() -> void:
    cut_frame += jattack["rate"]
    var vy := velocity.y / 30.0 + gravity
    var hit: Array = jattack["hit"]
    var active: bool = cut_frame >= hit[0] and cut_frame < hit[1]
    _sword_active(active)
    if active:
        _sword_sweep()
    _apply(air_vel, vy)
    if is_on_floor() and cut_frame > 4.0:
        _sword_active(false)
        state = State.JUMPCUT_LAND
        cut_frame = JATTACK_LAND["start"]
        speed = 0.0
        play_clip("jattackland", 2.0 / 30.0, JATTACK_LAND["rate"])

func _jumpcut_land() -> void:
    cut_frame += JATTACK_LAND["rate"]
    _apply(Vector3.ZERO, -1.0)
    if cut_frame > JATTACK_LAND["cancel"] and (stick().length() > 0.3 or Input.is_action_just_pressed("action_a") or Input.is_action_just_pressed("action_b")):
        _enter_ground()
        return
    if cut_frame >= JATTACK_LAND["end"]:
        _enter_ground()

# ---------------------------------------------------------------- damage

func take_damage(quarter_hearts: int, source_pos: Vector3, large := false) -> void:
    # called by enemies / hazards; uses the damage / laDamage tables
    if invincible > 0 or state == State.DAMAGE:
        return
    hearts = maxi(hearts - quarter_hearts, 0)
    _update_hud()
    invincible = DAMAGE_INVINCIBLE_FRAMES
    var dv := global_position - source_pos
    dv.y = 0.0
    var dist := dv.length()
    damage_dir = dv.normalized() if dist > 0.01 else -forward()
    _sword_active(false)
    combo = 0
    if hearts <= 0:
        _die()
        return
    if large:
        _enter_air(damage_dir * LARGE_DAMAGE_SPEED, LARGE_DAMAGE_SPEED_Y, LARGE_DAMAGE_GRAVITY)
        play_clip("damfb", 0.0)
        return
    state = State.DAMAGE
    speed = DAMAGE_KNOCKBACK_BASE + DAMAGE_KNOCKBACK_PER_VEC * dist
    cut_frame = DAMAGE_ANIM["start"]
    # directional flinch: which side the hit came from relative to facing
    var rel := wrapf(heading_of(-damage_dir) - facing, -PI, PI)
    var clip := "damf"
    if absf(rel) > PI * 0.75:
        clip = "damb"
    elif rel > PI * 0.25:
        clip = "daml"
    elif rel < -PI * 0.25:
        clip = "damr"
    play_clip(clip, 0.0, DAMAGE_ANIM["rate"])

func _damage() -> void:
    cut_frame += DAMAGE_ANIM["rate"]
    var step := clampf(speed * DAMAGE_DECEL[0], DAMAGE_DECEL[1], DAMAGE_DECEL[2])
    speed = maxf(speed - step, 0.0)
    _apply(damage_dir * speed, -1.0)
    if cut_frame >= DAMAGE_ANIM["end"]:
        speed = 0.0
        _enter_ground()

func heal(quarter_hearts: int) -> void:
    hearts = mini(hearts + quarter_hearts, hearts_max)
    _update_hud()

func _die() -> void:
    # no game-over screen yet: respawn at the stage entry with full hearts
    global_position = start_pos
    velocity = Vector3.ZERO
    speed = 0.0
    hearts = hearts_max
    invincible = DAMAGE_INVINCIBLE_FRAMES * 2
    _update_hud()
    _enter_ground()

func _update_hud() -> void:
    if hud_hearts == null:
        return
    var s := ""
    var full := hearts / 4
    var part := hearts % 4
    for i in hearts_max / 4:
        if i < full:
            s += "\\u2665 "
        elif i == full and part > 0:
            s += ["", "\\u25d4 ", "\\u25d1 ", "\\u25d5 "][part]
        else:
            s += "\\u2661 "
    hud_hearts.text = s

func _enter_swim() -> void:
    state = State.SWIM
    swim_speed = 0.0
    velocity.y = clampf(velocity.y, -50.0 * 30.0, 0.0)  # swim.water_entry_yspeed_min
    play_clip("swimwait", 0.2)

func _swim() -> void:
    var surface := water_surface()
    var s := stick()
    var dist := minf(s.length(), 1.0)
    if dist > 0.05:
        turn_toward(heading_of(stick_world_dir(s)), SWIM_TURN_MAX, SWIM_TURN_MIN, SWIM_TURN_DIVISOR)
    var target := SWIM_SPEED_MAX * dist * dist
    var remaining := target - swim_speed
    var step := clampf(absf(remaining) * SWIM_APPROACH_SCALE, SWIM_APPROACH_MIN, SWIM_APPROACH_MAX)
    if absf(remaining) <= step:
        swim_speed = target
    else:
        swim_speed += signf(remaining) * step
    # rise to the surface, then float there
    var vy := velocity.y / 30.0
    var depth := surface - global_position.y
    if depth > 0.0:
        vy = minf(vy + SWIM_RISE_ACCEL, SWIM_RISE_MAX)
        if vy > depth:
            vy = depth
    else:
        vy = 0.0
        global_position.y = surface
    _apply(forward() * swim_speed, vy)
    if is_on_floor() and depth < SWIM_START_DEPTH:
        speed = swim_speed
        _enter_ground()
        return
    if swim_speed > 0.5:
        play_clip("swiming", 0.2, clampf(swim_speed / SWIM_SPEED_MAX, 0.5, 1.3))
    else:
        play_clip("swimwait", 0.2)
"""


def _player_tscn(has_model: bool) -> str:
    model_res = (
        '[ext_resource type="PackedScene" path="res://link.glb" id="2"]\n' if has_model else ""
    )
    model_node = (
        '\n[node name="Model" parent="." instance=ExtResource("2")]\n'
        "transform = Transform3D(-1, 0, 0, 0, 1, 0, 0, 0, -1, 0, 0, 0)\n"
        if has_model
        else ""
    )
    return f"""[gd_scene load_steps={3 + int(has_model)} format=3]

[ext_resource type="Script" path="res://player.gd" id="1"]
{model_res}
[sub_resource type="CapsuleShape3D" id="cap"]
radius = 40.0
height = 160.0

[sub_resource type="CapsuleShape3D" id="sword"]
radius = 20.0
height = 170.0

[node name="Player" type="CharacterBody3D"]
collision_mask = 5
script = ExtResource("1")

[node name="Collision" type="CollisionShape3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 80, 0)
shape = SubResource("cap")
{model_node}
[node name="Lamp" type="OmniLight3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 250, 0)
omni_range = 1500.0
light_energy = 0.7
shadow_enabled = false

[node name="SwordPivot" type="Node3D" parent="."]

[node name="SwordHit" type="Area3D" parent="SwordPivot"]
collision_layer = 0
collision_mask = 8
monitorable = false

[node name="Shape" type="CollisionShape3D" parent="SwordPivot/SwordHit"]
transform = Transform3D(1, 0, 0, 0, 0, -1, 0, 1, 0, 0, 90, 85)
shape = SubResource("sword")

[node name="HUD" type="CanvasLayer" parent="."]
layer = 10

[node name="Hearts" type="Label" parent="HUD"]
offset_left = 24.0
offset_top = 16.0
offset_right = 600.0
offset_bottom = 70.0
theme_override_font_sizes/font_size = 34
theme_override_colors/font_color = Color(1, 0.25, 0.3, 1)
text = ""

[node name="CamYaw" type="Node3D" parent="."]

[node name="SpringArm3D" type="SpringArm3D" parent="CamYaw"]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 160, 0)
spring_length = 450.0
collision_mask = 1

[node name="Camera3D" type="Camera3D" parent="CamYaw/SpringArm3D"]
near = 5.0
far = 1000000.0
"""


# player animation clips kept in link.glb (the model ships 594; these drive movement)
_PLAYER_CLIPS = (
    "wait", "walk", "dash", "mjmp", "jmped", "mrolll", "swimwait", "swiming",
    "cuta", "cutf", "cutr", "cutl", "cutea", "cuteb", "jattack", "jattackland",
    "damf", "damb", "daml", "damr", "dam", "damff", "damfb", "talka",
)  # fmt: skip

_GAME_GD = """extends Node
# gcrip autoload: stage warps + controller mapping. Doors' destinations come from the
# game's own exit tables; spawn positions per stage live in res://stage_data.json.
# Unknown USB pads (e.g. GameCube-shaped DragonRise 0079:0006 pads) get a mapping from
# the calibration screen (F1, or Start on the pad), saved in user://gcpad.cfg.

const PAD_CFG := "user://gcpad.cfg"

# Pads we have measured (GUID -> SDL mapping). DragonRise 0079:0006 is the chip in most
# GameCube-shaped USB pads; this one reports the C-stick X on axes 2 AND 3, Y on axis 4.
const PRESET_PADS := {
    "0300457e790000000600000000000000":
        "0300457e790000000600000000000000,DragonRise GameCube USB,a:b2,b:b3,x:b1,y:b0,start:b9,rightshoulder:b6,lefttrigger:b4,righttrigger:b5,leftx:a0,lefty:a1,rightx:a2,righty:a4,dpup:b11,dpdown:b12,dpleft:b13,dpright:b14,platform:Windows,",
}

var stage_data: Dictionary = {}
var pending: Dictionary = {}
var last_warp_ms := -100000
var banner: Label = null
var calib: Node = null

func _ready() -> void:
    var f := FileAccess.open("res://stage_data.json", FileAccess.READ)
    if f:
        var parsed = JSON.parse_string(f.get_as_text())
        if parsed is Dictionary:
            stage_data = parsed
    _apply_saved_pad_mappings()
    Input.joy_connection_changed.connect(func(_id, _c): _apply_saved_pad_mappings())

func _apply_saved_pad_mappings() -> void:
    var cfg := ConfigFile.new()
    cfg.load(PAD_CFG)
    var unknown := []
    for id in Input.get_connected_joypads():
        var guid := Input.get_joy_guid(id)
        if cfg.has_section_key("mappings", guid):
            Input.add_joy_mapping(cfg.get_value("mappings", guid), true)
        elif PRESET_PADS.has(guid):
            Input.add_joy_mapping(PRESET_PADS[guid], true)
        elif not Input.is_joy_known(id):
            unknown.append(Input.get_joy_name(id))
    if unknown.size() > 0:
        _show_banner("Controller '%s' is not mapped - press F1 (or Start) to calibrate" % unknown[0])
    else:
        _show_banner("")

func _show_banner(text: String) -> void:
    if banner == null:
        var layer := CanvasLayer.new()
        layer.layer = 50
        add_child(layer)
        banner = Label.new()
        banner.position = Vector2(16, 12)
        banner.add_theme_font_size_override("font_size", 20)
        banner.add_theme_color_override("font_color", Color(1, 0.92, 0.5))
        layer.add_child(banner)
    banner.text = text
    banner.visible = text != ""

func _unhandled_input(event: InputEvent) -> void:
    if calib != null:
        return
    var start_pressed: bool = event is InputEventJoypadButton and event.pressed and not Input.is_joy_known(event.device) and banner != null and banner.visible
    if event.is_action_pressed("calibrate") or start_pressed:
        open_calibration()

func open_calibration() -> void:
    if calib != null:
        return
    calib = load("res://calib.tscn").instantiate()
    calib.done.connect(_on_calibrated)
    add_child(calib)
    get_tree().paused = true

func _on_calibrated(guid: String, mapping: String) -> void:
    get_tree().paused = false
    calib.queue_free()
    calib = null
    if mapping != "":
        var cfg := ConfigFile.new()
        cfg.load(PAD_CFG)
        cfg.set_value("mappings", guid, mapping)
        cfg.save(PAD_CFG)
        Input.add_joy_mapping(mapping, true)
        _show_banner("")

func warp(dest_stage: String, dest_room: int, dest_spawn: int) -> void:
    if Time.get_ticks_msec() - last_warp_ms < 1500:
        return  # just arrived; don't bounce straight back through the door
    var path := "res://scenes/%s.tscn" % dest_stage
    if not ResourceLoader.exists(path):
        print("gcrip: stage not exported: ", dest_stage,
              "  (gcrip godot <ripdir> ", dest_stage, ")")
        return
    last_warp_ms = Time.get_ticks_msec()
    pending = {"stage": dest_stage, "room": dest_room, "spawn": dest_spawn}
    get_tree().change_scene_to_file.call_deferred(path)
    _place_player.call_deferred()

func _place_player() -> void:
    for i in 60:
        await get_tree().process_frame
        var cs := get_tree().current_scene
        if cs and cs.name == String(pending.get("stage", "")):
            break
    if pending.is_empty():
        return
    var player := get_tree().current_scene.get_node_or_null("Player")
    var info: Dictionary = stage_data.get(pending["stage"], {})
    var best = null
    for sp in info.get("spawns", []):
        if int(sp["id"]) == int(pending["spawn"]) and int(sp["room"]) == int(pending["room"]):
            best = sp
            break
    if best == null:
        for sp in info.get("spawns", []):
            if int(sp["room"]) == int(pending["room"]):
                best = sp
                break
    if player and best != null:
        player.global_position = Vector3(
            best["pos"][0], best["pos"][1] + 30.0, best["pos"][2])
        player.velocity = Vector3.ZERO
        player.start_pos = player.global_position
    pending = {}
"""

_CALIB_GD = """extends CanvasLayer\n# gcrip controller calibration: press each GameCube input in turn; writes an SDL\n# mapping for this pad's GUID so Godot's standard button/axis ids work afterwards.\n# Polls Input directly instead of listening to events: raw buttons 0/1 of an unknown pad\n# double as ui_accept/ui_cancel and their events never reach us.\n\nsignal done(guid: String, mapping: String)\n\nconst STEPS := [\n    ["A", "a"], ["B", "b"], ["X", "x"], ["Y", "y"],\n    ["Z", "rightshoulder"], ["L (press fully)", "lefttrigger"], ["R (press fully)", "righttrigger"],\n    ["Start", "start"],\n    ["push the LEFT stick RIGHT", "leftx"], ["push the LEFT stick UP", "lefty"],\n    ["push the C-stick RIGHT", "rightx"], ["push the C-stick UP", "righty"],\n    ["D-pad UP", "dpup"], ["D-pad DOWN", "dpdown"], ["D-pad LEFT", "dpleft"], ["D-pad RIGHT", "dpright"],\n]\nconst MAX_BUTTONS := 32\nconst MAX_AXES := 10\n\nvar step := 0\nvar device := -1\nvar parts: Array[String] = []\nvar used_buttons := {}\nvar used_axes := {}\nvar cooldown := 0.0\nvar was_down := {}\nvar last_seen := ""\n@onready var label: Label = $Panel/Label\n\nfunc _ready() -> void:\n    layer = 60\n    process_mode = Node.PROCESS_MODE_ALWAYS\n    var pads := Input.get_connected_joypads()\n    if pads.is_empty():\n        label.text = "No controller detected.\n\nPlug one in, then press F1 again.  (Esc closes)"\n        return\n    device = pads[0]\n    # settle: remember what is held right now so a resting trigger is not taken as a press\n    for b in MAX_BUTTONS:\n        was_down[b] = Input.is_joy_button_pressed(device, b)\n    _prompt()\n\nfunc _prompt() -> void:\n    if step >= STEPS.size():\n        _finish()\n        return\n    label.text = "Controller calibration  (%d/%d)   %s\n\nPress  %s\n\n%s\n\nEsc: cancel     Backspace: skip this one" % [\n        step + 1, STEPS.size(), Input.get_joy_name(device), STEPS[step][0], last_seen]\n\nfunc _input(event: InputEvent) -> void:\n    if event is InputEventKey and event.pressed:\n        if event.keycode == KEY_ESCAPE:\n            done.emit("", "")\n        elif event.keycode == KEY_BACKSPACE:\n            step += 1\n            _prompt()\n        get_viewport().set_input_as_handled()\n    elif event is InputEventJoypadButton or event is InputEventJoypadMotion:\n        get_viewport().set_input_as_handled()  # keep the game from reacting while we map\n\nfunc _process(delta: float) -> void:\n    cooldown = maxf(cooldown - delta, 0.0)\n    if device < 0 or step >= STEPS.size():\n        return\n    var sdl: String = STEPS[step][1]\n    var is_axis_step: bool = sdl.ends_with("x") or sdl.ends_with("y")\n    var is_trigger: bool = sdl.ends_with("trigger")\n    # buttons: rising edge\n    for b in MAX_BUTTONS:\n        var down := Input.is_joy_button_pressed(device, b)\n        var rose: bool = down and not was_down.get(b, false)\n        was_down[b] = down\n        if rose and cooldown <= 0.0 and not is_axis_step and not used_buttons.has(b):\n            used_buttons[b] = true\n            last_seen = "got raw button %d" % b\n            parts.append("%s:b%d" % [sdl, b])\n            _advance()\n            return\n    if cooldown > 0.0:\n        return\n    # axes: first one pushed past 0.6\n    for a in MAX_AXES:\n        var v := Input.get_joy_axis(device, a)\n        if absf(v) < 0.6 or used_axes.has(a):\n            continue\n        if is_axis_step:\n            used_axes[a] = true\n            # SDL axes are +right / +down; we asked for RIGHT and UP, so UP arriving positive\n            # (or RIGHT arriving negative) means the axis is inverted ('~' flips it)\n            var inverted: bool = (sdl.ends_with("y") and v > 0.0) or (sdl.ends_with("x") and v < 0.0)\n            last_seen = "got raw axis %d (%+.2f)" % [a, v]\n            parts.append("%s:a%d%s" % [sdl, a, "~" if inverted else ""])\n            _advance()\n            return\n        elif is_trigger:\n            used_axes[a] = true\n            last_seen = "got raw axis %d" % a\n            parts.append("%s:a%d" % [sdl, a])\n            _advance()\n            return\n\nfunc _advance() -> void:\n    cooldown = 0.6\n    step += 1\n    _prompt()\n\nfunc _finish() -> void:\n    if device < 0 or parts.is_empty():\n        done.emit("", "")\n        return\n    var guid := Input.get_joy_guid(device)\n    var name := Input.get_joy_name(device).replace(",", " ")\n    var mapping := "%s,%s,%s,platform:Windows," % [guid, name, ",".join(parts)]\n    label.text = "Saved mapping for %s\n\n%s" % [name, mapping]\n    await get_tree().create_timer(1.5).timeout\n    done.emit(guid, mapping)\n"""

_CALIB_TSCN = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://calib.gd" id="1"]

[node name="Calib" type="CanvasLayer"]
script = ExtResource("1")

[node name="Panel" type="Panel" parent="."]
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
grow_horizontal = 2
grow_vertical = 2

[node name="Label" type="Label" parent="Panel"]
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
horizontal_alignment = 1
vertical_alignment = 1
theme_override_font_sizes/font_size = 28
"""

_STAGE_GD = """extends Node3D
# gcrip stage root: puts the game's liquid collision (from the .dzb) on its own physics
# layers so Link can probe for water and hazards without colliding with them.
#   layer 1 = solid ground   layer 2 = water surfaces   layer 4 = lava / poison

func _ready() -> void:
    var col := get_node_or_null("Collision")
    if col == null:
        return
    for body in col.find_children("*", "StaticBody3D", true, false):
        var n: String = body.name
        if n.begins_with("liquid_water"):
            body.collision_layer = 2
            body.collision_mask = 0
            body.set_meta("liquid", "water")
        elif n.begins_with("liquid_lava") or n.begins_with("liquid_poison"):
            body.collision_layer = 4
            body.collision_mask = 0
            body.set_meta("liquid", "lava" if n.begins_with("liquid_lava") else "poison")
"""

_WARP_GD = """extends Area3D
# gcrip: walking into this (a door) loads the destination stage.

@export var dest_stage := ""
@export var dest_room := 0
@export var dest_spawn := 0

func _ready() -> void:
    body_entered.connect(_on_body_entered)

func _on_body_entered(body: Node3D) -> void:
    if body is CharacterBody3D:
        Game.warp(dest_stage, dest_room, dest_spawn)
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


def _stage_tscn(
    name: str,
    spawn: tuple[float, float, float],
    *,
    has_col: bool = False,
    exits: list[dict] | None = None,
    water_level: float = -1.0e9,
) -> str:
    x, y, z = spawn
    exits = exits or []
    col_res = (
        f'[ext_resource type="PackedScene" path="res://stages/{name}_col.glb" id="3"]\n'
        if has_col
        else ""
    )
    col_node = (
        '\n[node name="Collision" parent="." instance=ExtResource("3")]\n' if has_col else ""
    )
    warp_res = '[ext_resource type="Script" path="res://warp.gd" id="4"]\n' if exits else ""
    stage_res = '[ext_resource type="Script" path="res://stage.gd" id="5"]\n'
    warp_shape = (
        '\n[sub_resource type="BoxShape3D" id="warpbox"]\nsize = Vector3(220, 320, 220)\n'
        if exits
        else ""
    )
    warp_nodes = []
    for i, e in enumerate(exits):
        ex, ey, ez = e["pos"]
        nm = f"Warp{i}_{e['dest_stage']}"
        warp_nodes.append(
            f'\n[node name="{nm}" type="Area3D" parent="."]\n'
            f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
            f"{ex:.1f}, {ey + 120:.1f}, {ez:.1f})\n"
            f'script = ExtResource("4")\n'
            f'dest_stage = "{e["dest_stage"]}"\n'
            f"dest_room = {e['room']}\n"
            f"dest_spawn = {e['spawn']}\n"
            f'\n[node name="Shape" type="CollisionShape3D" parent="{nm}"]\n'
            f'shape = SubResource("warpbox")\n'
        )
    return f"""[gd_scene load_steps={7 + int(has_col) + (2 if exits else 0)} format=3]

[ext_resource type="PackedScene" path="res://stages/{name}.glb" id="1"]
[ext_resource type="PackedScene" path="res://player.tscn" id="2"]
{col_res}{warp_res}{stage_res}

{warp_shape}
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
script = ExtResource("5")

[node name="Level" parent="." instance=ExtResource("1")]
{col_node}
[node name="Sun" type="DirectionalLight3D" parent="."]
transform = Transform3D({_sun_basis()}, 0, 10000, 0)
light_energy = 1.3
shadow_enabled = true

[node name="Env" type="WorldEnvironment" parent="."]
environment = SubResource("env")

[node name="Player" parent="." instance=ExtResource("2")]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {x:.1f}, {y + 30:.1f}, {z:.1f})
water_level = {water_level:.1f}
{"".join(warp_nodes)}"""


def _project_godot(title: str, main_scene: str) -> str:
    k = _KEYS
    return f"""; generated by gcrip godot - open this folder with Godot 4
config_version=5

[application]

config/name={json.dumps(title)}
run/main_scene="res://scenes/{main_scene}.tscn"
config/features=PackedStringArray("4.2")

[autoload]

Game="*res://game.gd"

[input]

move_forward={_action(k["W"], k["UP"], _joy_axis(AXIS_LY, -1.0), deadzone=0.15)}
move_back={_action(k["S"], k["DOWN"], _joy_axis(AXIS_LY, 1.0), deadzone=0.15)}
move_left={_action(k["A"], k["LEFT"], _joy_axis(AXIS_LX, -1.0), deadzone=0.15)}
move_right={_action(k["D"], k["RIGHT"], _joy_axis(AXIS_LX, 1.0), deadzone=0.15)}
action_a={_action(k["SPACE"], _joy_button(JOY_A))}
action_b={_action(k["CTRL"], _joy_button(JOY_B))}
target={_action(k["SHIFT"], _joy_button(JOY_RSHOULDER), _joy_axis(AXIS_RT, 1.0))}
pause={_action(k["ESC"], _joy_button(JOY_START))}
calibrate={_action(k["F1"])}

[physics]

common/physics_ticks_per_second=30

[rendering]

renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""


def _godot_glb(stage_gltf: Path, out_glb: Path, *, suffix_rooms: bool = True) -> int:
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
        if suffix_rooms and i in room_children and "mesh" in node:
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


def _godot_col_glb(col_gltf: Path, out_glb: Path) -> int:
    """Pack the stage's real .dzb collision for Godot: solid surfaces become
    -colonly nodes (collision only, nothing rendered); water/lava/poison meshes are
    left un-referenced for now (they will become swim/damage Area3Ds later)."""
    doc = json.loads(col_gltf.read_text(encoding="utf-8"))
    n_solid = 0
    for node in doc.get("nodes", []):
        surface = (node.get("extras") or {}).get("gcrip_surface")
        if surface == "solid" and "mesh" in node:
            node["name"] = node.get("name", "col").replace("/", "_") + "-colonly"
            n_solid += 1
        elif surface and "mesh" in node:
            # liquid surfaces become colliders too; stage.gd moves them to the water /
            # hazard physics layers at runtime (Godot's import suffixes can't set layers)
            node["name"] = f"liquid_{surface}_" + node.get("name", "col").replace("/", "_") + "-colonly"
    tmp = col_gltf.with_suffix(".godot.gltf")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    try:
        out_glb.parent.mkdir(parents=True, exist_ok=True)
        out_glb.write_bytes(glbmod.pack(tmp))
    finally:
        tmp.unlink(missing_ok=True)
    return n_solid


def _trim_animations(doc: dict, blob: bytes, keep: tuple[str, ...]) -> tuple[dict, bytes]:
    """Keep only the named animations, then garbage-collect accessors/bufferViews so
    the dropped clips' keyframe data leaves the buffer (Link ships 14 MB of clips)."""
    doc = json.loads(json.dumps(doc))  # deep copy
    doc["animations"] = [a for a in doc.get("animations", []) if a.get("name") in keep]
    for node in doc.get("nodes", []):
        # hidden expression-variant clones: Godot ignores KHR_node_visibility and
        # would render every eye/mouth texture at once - un-mesh them instead
        vis = node.get("extensions", {}).get("KHR_node_visibility", {})
        if vis.get("visible") is False:
            node.pop("mesh", None)
            node.pop("skin", None)
            node.pop("extensions", None)

    used: set[int] = set()
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            used.update(prim.get("attributes", {}).values())
            if "indices" in prim:
                used.add(prim["indices"])
    for skin in doc.get("skins", []):
        if "inverseBindMatrices" in skin:
            used.add(skin["inverseBindMatrices"])
    for anim in doc["animations"]:
        for smp in anim.get("samplers", []):
            used.add(smp["input"])
            used.add(smp["output"])

    _CSIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
    _NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
    new_bin = bytearray()
    new_views: list[dict] = []
    new_accs: list[dict] = []
    acc_map: dict[int, int] = {}
    for old in sorted(used):
        acc = dict(doc["accessors"][old])
        bv = doc["bufferViews"][acc["bufferView"]]
        off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        length = acc["count"] * _CSIZE[acc["componentType"]] * _NCOMP[acc["type"]]
        while len(new_bin) % 4:
            new_bin.append(0)
        new_views.append({"buffer": 0, "byteOffset": len(new_bin), "byteLength": length})
        new_bin += blob[off : off + length]
        acc["bufferView"] = len(new_views) - 1
        acc.pop("byteOffset", None)
        acc_map[old] = len(new_accs)
        new_accs.append(acc)

    doc["accessors"] = new_accs
    doc["bufferViews"] = new_views
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            for k in prim.get("attributes", {}):
                prim["attributes"][k] = acc_map[prim["attributes"][k]]
            if "indices" in prim:
                prim["indices"] = acc_map[prim["indices"]]
    for skin in doc.get("skins", []):
        if "inverseBindMatrices" in skin:
            skin["inverseBindMatrices"] = acc_map[skin["inverseBindMatrices"]]
    for anim in doc["animations"]:
        for smp in anim.get("samplers", []):
            smp["input"] = acc_map[smp["input"]]
            smp["output"] = acc_map[smp["output"]]
    return doc, bytes(new_bin)


def _player_model_glb(rip_dir: Path, out_glb: Path) -> bool:
    """Rigged Link with his movement clips as a small self-contained glb."""
    results = rip_dir / "rip_results.json"
    if not results.exists():
        return False
    models = json.loads(results.read_text(encoding="utf-8"))["models"]
    rel = next(
        (m["out_rel"] for m in models
         if (m.get("out_rel") or "").endswith("Link.arc/archive/bdl/cl.gltf")),
        None,
    )  # fmt: skip
    if rel is None:
        return False
    src = rip_dir / rel
    doc = json.loads(src.read_text(encoding="utf-8"))
    blob = (src.parent / doc["buffers"][0]["uri"]).read_bytes()
    trimmed, new_bin = _trim_animations(doc, blob, _PLAYER_CLIPS)
    tmp_bin = src.parent / "_gcrip_player.bin"
    tmp_gltf = src.parent / "_gcrip_player.gltf"
    trimmed["buffers"] = [{"uri": tmp_bin.name, "byteLength": len(new_bin)}]
    try:
        tmp_bin.write_bytes(new_bin)
        tmp_gltf.write_text(json.dumps(trimmed), encoding="utf-8")
        out_glb.write_bytes(glbmod.pack(tmp_gltf))
    finally:
        tmp_gltf.unlink(missing_ok=True)
        tmp_bin.unlink(missing_ok=True)
    return True


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
    stage_data: dict[str, dict] = {}
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
        col_gltf = d / f"{gltf_path.stem}_col.gltf"
        has_col = col_gltf.exists()
        if has_col:  # the game's own collision mesh; visual geometry stays render-only
            n_col = _godot_col_glb(col_gltf, out_dir / "stages" / f"{name}_col.glb")
            _godot_glb(gltf_path, out_dir / "stages" / f"{name}.glb", suffix_rooms=False)
            kind = "dzb colliders"
        else:  # fallback: collide with the visible room geometry
            n_col = _godot_glb(gltf_path, out_dir / "stages" / f"{name}.glb")
            kind = "visual colliders"
        exits = rep.get("exits") or []
        # the Great Sea's water is the y=0 plane (islands are authored around it); proper
        # per-stage water volumes come with the dzb liquid surfaces later
        water = 0.0 if name.lower().startswith("sea") else -1.0e9
        (out_dir / "scenes" / f"{name}.tscn").write_text(
            _stage_tscn(name, spawn, has_col=has_col, exits=exits, water_level=water),
            encoding="utf-8",
        )
        stage_data[name] = {"spawns": spawns}
        done.append(name)
        if not quiet:
            size = (out_dir / "stages" / f"{name}.glb").stat().st_size >> 20
            print(f"  {name:14} {size:4d} MB glb, {n_col} {kind}, "
                  f"spawn {tuple(round(v) for v in spawn)}")  # fmt: skip

    has_model = _player_model_glb(rip_dir, out_dir / "link.glb")
    (out_dir / "player.gd").write_text(_PLAYER_GD, encoding="utf-8")
    (out_dir / "player.tscn").write_text(_player_tscn(has_model), encoding="utf-8")
    (out_dir / "game.gd").write_text(_GAME_GD, encoding="utf-8")
    (out_dir / "warp.gd").write_text(_WARP_GD, encoding="utf-8")
    (out_dir / "calib.gd").write_text(_CALIB_GD, encoding="utf-8")
    (out_dir / "calib.tscn").write_text(_CALIB_TSCN, encoding="utf-8")
    (out_dir / "stage.gd").write_text(_STAGE_GD, encoding="utf-8")
    sd_path = out_dir / "stage_data.json"
    if sd_path.exists():  # partial re-exports must not clobber other stages' spawn data
        with contextlib.suppress(OSError, ValueError):
            merged = json.loads(sd_path.read_text(encoding="utf-8"))
            merged.update(stage_data)
            stage_data = merged
    sd_path.write_text(json.dumps(stage_data), encoding="utf-8")
    main = next((n for n in ("sea_r44", "M_NewD2", "sea") if n in done), done[0])
    (out_dir / "project.godot").write_text(_project_godot(title, main), encoding="utf-8")
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
