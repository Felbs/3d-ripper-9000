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
    "W": 87, "A": 65, "S": 83, "D": 68, "E": 69, "Q": 81, "SPACE": 32, "SHIFT": 4194325,
    "CTRL": 4194326, "ESC": 4194305, "F1": 4194332,
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
# --- Deku Leaf glide (fan table) ---
const GLIDE_DEPLOY_SPEED_Y := 15.0      # fan.fan_deploy_speed_y
const GLIDE_GRAVITY := -0.5             # fan.fan_glide_gravity (once falling)
const GLIDE_MAX_FALL := -2.0            # fan.fan_glide_max_fall_speed
const GLIDE_FORWARD_SPEED := 12.0       # fan.fan_glide_forward_speed (x stick x cos)
const GLIDE_MAGIC_INTERVAL := 40        # fan.fan_glide_magic_drain_interval
const GLIDE_CANCEL_LOCKOUT := 20        # fan.fan_glide_cancel_lockout
const GLIDE_LAND_RATE := 0.6            # fan.fan_land_anm_rate
const MAGIC_MAX := 16                   # small magic meter
# --- Iron Boots ---
const HEAVY_SPEED_SCALE := 0.5          # move.heavy_speed_scale

# --- ledges (wallCatch / hang tables) ---
const LEDGE_MIN := 27.09               # hard-coded lower bound
const LEDGE_SMALL_JUMP_MAX := 75.0     # wallCatch.ledge_height_small_jump_max
const LEDGE_WALL_CATCH_MAX := 110.0    # wallCatch.ledge_height_wall_catch_max
const LEDGE_VJUMP_CATCH_MAX := 130.0   # wallCatch.ledge_height_vjump_catch_max
const LEDGE_CATCH_MAX := 170.0         # wallCatch.ledge_height_catch_max
const WALL_HOLD_FRAMES := 7            # wallCatch.wall_catch_stick_hold_frames
const HANG_HEIGHT := 140.0             # feet below the ledge while hanging (Link is 125 tall + reach)
const CLIMB_FRAMES := 32               # VJMPCL: 24 frames at rate 0.75
const CLIMB_CANCEL := 23.0 / 0.75      # wallCatch.hang_climb_cancel_frame
const CATCH_FRAMES := 6                # VJMPCHB: 5 frames at 0.8
const VJUMP_FRAMES := 13               # wallCatch.vertical_jump_anm_end_frame

const S16_TO_RAD := PI / 32768.0

enum State { GROUND, AIR, ROLL, SWIM, LAND, ATTACK, JUMPCUT, JUMPCUT_LAND, DAMAGE, GLIDE, CARRY, GRAB, VJUMP, HANG, CLIMB }

@export var water_level := -1.0e9   # stage sets this (sea stages: 0)

@onready var cam_rig: Node3D = $CamRig
@onready var camera: Camera3D = $CamRig/Camera3D
@onready var model: Node3D = get_node_or_null("Model")

# --- camera (d_camera.cpp followCamera, style FN01 "Field"; see memRip camera-spec.md) ---
const CAM_ATTN_HEIGHT := 92.5          # Link attention point above the feet
const CAM_OFF := Vector3(0.0, 10.0, 1.0)  # style offset (side, height, fwd) rotated by Link yaw
const CAM_R_MIN := 280.0
const CAM_R_MAX := 480.0
const CAM_R_CUSH := 0.66
const CAM_PITCH_DEG := 10.0
const CAM_H_RATE := 0.7                # center follows at 0.7 when Link faces the camera, 0.1 running away
const CAM_V_RATE := 0.25
const CAM_YAW_GAIN := 0.2
const CAM_EYE_SMOOTH := 0.75
const CAM_FOV := 60.0
const CAM_WALL_MARGIN := 10.5
const CAM_MIN_DIST := 40.0
var cam_center := Vector3.ZERO
var cam_eye := Vector3.ZERO
var cam_pitch_tgt := deg_to_rad(CAM_PITCH_DEG)
var cam_pitch_rate := 0.01
var cam_r_cush := 1.0
var cam_recenter_gain := 0.05
var cam_was_recenter := false
var cam_manual := 0                    # frames of C-stick / mouse control left
var cam_manual_yaw := 0.0
var cam_manual_pitch := 0.0
# --- Z-target lock-on (lockonCamera, style LL01) ---
const LOCK_ACQUIRE_DIST := 1000.0
const LOCK_RELEASE_DIST := 1400.0      # inferred (the table's release distance is per target type)
const LOCK_LON_MIN := 75.0             # deg, camera offset from the Link->target line, far
const LOCK_LON_MAX := 20.0             # near
const LOCK_LAT_MIN := 20.0             # pitch far
const LOCK_LAT_MAX := -5.0             # pitch near
const LOCK_R_LO := 420.0
const LOCK_R_HI := 480.0
const LOCK_FOV_MIN := 48.0
const LOCK_FOV_MAX := 62.0
const LOCK_YAW_RATE := 0.04
var lock_target: Node3D = null
var lock_frames := 0
var lock_base_y := 0.0
var lock_cush := 0.28
var lock_shift_r := 0.0
var lock_shift_yaw := 0.0
var cam_fov := 60.0
@onready var hud_reticle: Label = get_node_or_null("HUD/Reticle")
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
# items
var magic := MAGIC_MAX
var heavy := false                       # Iron Boots on
var glide_frames := 0
var glide_magic_timer := 0
@onready var hud_magic: Label = get_node_or_null("HUD/Magic")
@onready var hud_items: Label = get_node_or_null("HUD/Items")
@onready var hud_rupees: Label = get_node_or_null("HUD/Rupees")
@onready var hud_prompt: Label = get_node_or_null("HUD/Prompt")
var rupees := 0
var held: Node3D = null          # carried pot / pig / pebble
var prompt_target: Node3D = null
var grab_frames := 0
# ledges
var wall_hold := 0
var ledge_top := Vector3.ZERO
var ledge_dir := Vector3.FORWARD   # horizontal direction into the wall
var climb_frame := 0
var climb_from := Vector3.ZERO
var hang_frames := 0
var vjump_kind := 0                 # 8 = catch at apex, 9 = hang start at apex
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
    cam_center = global_position + Vector3(0, CAM_ATTN_HEIGHT, 0)
    cam_eye = cam_center + _sph(380.0, deg_to_rad(CAM_PITCH_DEG), facing + PI)
    camera.global_position = cam_eye
    camera.look_at(cam_center, Vector3.UP)

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
        _orbit(event.relative.x * 0.003, event.relative.y * 0.003)
    if event.is_action_pressed("ui_cancel"):
        if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
            Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
        else:
            Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _orbit(dx: float, dy: float) -> void:
    # manual camera (C-stick / mouse): the decomp's manualCamera is a stub, so this is ours -
    # orbit the eye around the center and hold off the auto-yaw for a moment
    cam_manual_yaw -= dx
    cam_manual_pitch = clampf(cam_manual_pitch - dy, -1.0, 1.0)
    cam_manual = 45

# -- camera math (ported from d_cam_param.cpp / d_camera.cpp)

static func _rb(x: float, w: float) -> float:
    var sgn := 1.0
    if x < 0.0:
        sgn = -1.0
        x = -x
    var a := 2.0 * x
    var b := 2.0 * w
    var c := a * w - a - b
    var d := -c - 1.0
    var disc := c * c - 4.0 * d * x
    var num := -c - (sqrt(disc) if disc > 0.0 else 0.0)
    var den := d * 2.0
    if absf(den) <= 1e-7:
        return 0.0
    var t := num / den
    var t2 := t * t
    var u := 1.0 - t
    var q := t2 + u * u + w * 2.0 * u * t
    return sgn * (t2 / q) if q > 1e-7 else 0.0

static func _sph(r: float, pitch: float, yaw: float) -> Vector3:
    var c := cos(pitch)
    return Vector3(r * c * sin(yaw), r * sin(pitch), r * c * cos(yaw))

static func _to_sph(v: Vector3) -> Vector3:  # (R, pitch, yaw)
    var h := Vector2(v.x, v.z).length()
    return Vector3(v.length(), atan2(v.y, h), atan2(v.x, v.z))

func _target_attn() -> Vector3:
    if lock_target == null:
        return Vector3.ZERO
    return lock_target.global_position + Vector3(0, 60.0, 0)

func _update_lock() -> void:
    # hold Z/R: lock onto the closest enemy / talkable thing within 1000 units in the camera's view
    var want: bool = Input.is_action_pressed("target")
    if not want:
        lock_target = null
        return
    if lock_target != null:
        if not is_instance_valid(lock_target) or lock_target.global_position.distance_to(global_position) > LOCK_RELEASE_DIST:
            lock_target = null
        else:
            return
    var best: Node3D = null
    var best_d := LOCK_ACQUIRE_DIST
    var cy := cam_yaw_angle()
    var cam_fwd := Vector3(sin(cy), 0.0, cos(cy))
    for grp in ["enemy", "interact"]:
        for n in get_tree().get_nodes_in_group(grp):
            if not is_instance_valid(n) or n == held or not (n is Node3D):
                continue
            var to_n: Vector3 = n.global_position - global_position
            to_n.y = 0.0
            var d := to_n.length()
            if d > best_d or d < 1.0:
                continue
            if cam_fwd.dot(to_n / d) < 0.3:
                continue
            best = n
            best_d = d
    if best != null:
        lock_target = best
        lock_frames = 0
        lock_base_y = cam_center.y
        lock_cush = 0.28
        lock_shift_r = 0.0
        lock_shift_yaw = 0.0

func _lockon_tick() -> void:
    var attn := global_position + Vector3(0, CAM_ATTN_HEIGHT, 0)
    var tattn := _target_attn()
    lock_frames += 1
    var to_t := tattn - attn
    var ts := _to_sph(to_t)                         # (dist, pitch_t, yaw_t)
    var t := clampf(ts.x / LOCK_RELEASE_DIST, 0.0, 1.0)
    var d := _to_sph(cam_eye - cam_center)
    # center: between Link and the target, height eased with a ground/air cushion
    lock_cush += ((0.28 if is_on_floor() else 1.0) - lock_cush) * 0.2
    var h_tgt := attn.y + lerpf(-22.5, 5.0, t)
    lock_base_y += lock_cush * (h_tgt - lock_base_y)
    var a := minf(absf(wrapf(d.z + PI - ts.z, -PI, PI)), absf(ts.y * 1.3))
    var r_goal := (ts.x - ts.x * 0.1) * absf(cos(a) * -0.5 + 0.5) + ts.x * 0.05
    lock_shift_r += 0.2 * (r_goal - lock_shift_r)
    lock_shift_yaw += 0.4 * wrapf(ts.z - lock_shift_yaw, -PI, PI)
    cam_center = Vector3(attn.x, lock_base_y, attn.z) + _sph(lock_shift_r, 0.0, lock_shift_yaw)
    # desired yaw: behind Link, offset sideways from the Link->target line (75 deg far .. 20 near)
    var lon := deg_to_rad(lerpf(LOCK_LON_MIN, LOCK_LON_MAX, t))
    var charged: bool = lock_frames >= 60
    if not charged:
        lon *= lock_frames / 60.0
    var side := signf(wrapf(d.z + PI - ts.z, -PI, PI))
    if side == 0.0:
        side = 1.0
    var yaw_des := ts.z + side * lon + PI
    var err := wrapf(yaw_des - d.z, -PI, PI)
    var rate := 0.15 if not charged else (LOCK_YAW_RATE if absf(err) >= lon else 0.0)
    var yaw := d.z + err * rate
    var pitch := d.y + (deg_to_rad(lerpf(LOCK_LAT_MIN, LOCK_LAT_MAX, t)) - d.y) * 0.33
    pitch = clampf(pitch, deg_to_rad(-60.0), deg_to_rad(80.0))
    var R := d.x + (clampf(d.x, LOCK_R_LO, LOCK_R_HI) - d.x) * 0.05
    cam_fov += (lerpf(LOCK_FOV_MIN, LOCK_FOV_MAX, t) - cam_fov) * 0.33
    cam_eye = cam_center + _sph(R, pitch, yaw)
    _camera_output(attn)

func _camera_output(attn: Vector3) -> void:
    # bumpCheck: keep the eye out of walls, never closer than 40 to Link
    var out_center := cam_center
    out_center.y = maxf(out_center.y, global_position.y + 32.0)
    var out_eye := cam_eye
    var space := get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(out_center, cam_eye, 1)
    var hit := space.intersect_ray(q)
    if hit:
        var back: Vector3 = (out_center - cam_eye).normalized() * CAM_WALL_MARGIN
        out_eye = hit.position + back
    if out_eye.distance_to(attn) < CAM_MIN_DIST:
        out_eye = attn + (out_eye - attn).normalized() * CAM_MIN_DIST
    camera.global_position = out_eye
    if out_eye.distance_to(out_center) > 1.0:
        camera.look_at(out_center, Vector3.UP)
    camera.fov = cam_fov
    if hud_reticle:
        if lock_target != null and is_instance_valid(lock_target):
            var p := _target_attn()
            hud_reticle.visible = not camera.is_position_behind(p)
            hud_reticle.position = camera.unproject_position(p) - hud_reticle.size / 2.0
        else:
            hud_reticle.visible = false

func _camera_tick() -> void:
    _update_lock()
    if lock_target != null:
        _lockon_tick()
        return
    cam_fov += (CAM_FOV - cam_fov) * 0.05
    var recenter: bool = Input.is_action_pressed("target")
    var attn := global_position + Vector3(0, CAM_ATTN_HEIGHT, 0)
    # center target: attention point + style offset rotated by Link's yaw
    var off := Vector3(CAM_OFF.x, CAM_OFF.y, CAM_OFF.z).rotated(Vector3.UP, facing)
    var c_tgt := attn + off
    var d := _to_sph(cam_eye - cam_center)
    var facing_cam: bool = absf(wrapf(facing - d.z, -PI, PI)) < PI / 2.0
    var h_rate := CAM_H_RATE if facing_cam else 0.1
    if recenter and h_rate > 0.25:
        h_rate = 0.25
    var dc := c_tgt - cam_center
    cam_center += Vector3(dc.x * h_rate, dc.y * CAM_V_RATE, dc.z * h_rate)
    d = _to_sph(cam_eye - cam_center)

    # yaw gain: ~0 when running straight, up to 0.02/frame when strafing; Z with no target swings behind
    var raw := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
    var sx := raw.x
    var mag := raw.length()
    var g := 0.0
    if recenter:
        g = 0.05 if not cam_was_recenter else cam_recenter_gain + (1.0 - cam_recenter_gain) * 0.2
        cam_recenter_gain = g
    else:
        if -raw.y >= 0.0:
            g = 1.0 - (cos(_rb(sx, 1.0) * PI) * 0.5 + 0.5)
        else:
            g = 1.0 - (cos(_rb(sx, 0.18) * PI) * 0.25 + 0.75)
        g *= mag * 0.1 * CAM_YAW_GAIN
    cam_was_recenter = recenter
    if cam_manual > 0:
        cam_manual -= 1
        g = 0.0
    var yaw_tgt := facing + PI
    var yaw := d.z + wrapf(yaw_tgt - d.z, -PI, PI) * g * cos(d.y) + cam_manual_yaw
    cam_manual_yaw = 0.0

    # pitch: eases toward the style pitch with a rate that ramps up while grounded
    var pitch_style := deg_to_rad(CAM_PITCH_DEG)
    if recenter:
        cam_pitch_tgt += g * (pitch_style - cam_pitch_tgt)
        cam_pitch_rate = 0.7
    elif is_on_floor():
        cam_pitch_tgt += 0.05 * (pitch_style + cam_manual_pitch * 0.9 - cam_pitch_tgt)
        cam_pitch_rate += (0.9 - cam_pitch_rate) * 0.01
    else:
        cam_pitch_tgt = d.y
        cam_pitch_rate = 0.3
    cam_pitch_tgt = clampf(cam_pitch_tgt, deg_to_rad(-60.0), deg_to_rad(60.0))
    var pitch := d.y + (cam_pitch_tgt - d.y) * cam_pitch_rate
    pitch = minf(pitch, deg_to_rad(80.0))

    # radius leash 280..480 with cushion
    var r := d.x
    if r < CAM_R_MIN:
        cam_r_cush += (CAM_R_CUSH - cam_r_cush) * 0.01
        r = CAM_R_MIN
    elif r > CAM_R_MAX:
        cam_r_cush += (CAM_R_CUSH - cam_r_cush) * 0.01
        r = CAM_R_MAX
    else:
        cam_r_cush = 1.0
    var R := d.x + cam_r_cush * (r - d.x)

    var eye_tgt := cam_center + _sph(R, pitch, yaw)
    cam_eye += (eye_tgt - cam_eye) * CAM_EYE_SMOOTH
    _camera_output(attn)

func cam_yaw_angle() -> float:
    var f := cam_center - cam_eye
    return atan2(f.x, f.z)

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
    # (Iron Boots scale the stick itself, like the game: move.heavy_speed_scale)
    var raw := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
    var s := Vector2(raw.x, -raw.y)
    return s * HEAVY_SPEED_SCALE if heavy else s

func stick_world_dir(s: Vector2) -> Vector3:
    # camera-relative: forward = the direction the camera looks (flattened)
    var cy := cam_yaw_angle()
    var fwd := Vector3(sin(cy), 0.0, cos(cy))
    var right := fwd.cross(Vector3.UP)   # camera +X (Godot's look_at: right = forward x up)
    var d := right * s.x + fwd * s.y
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
    if heavy:
        return false  # Iron Boots: Link walks along the bottom instead of swimming
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

    if Game.dialog_open:  # text box up: Link stands still
        _apply(Vector3.ZERO, -1.0)
        play_clip("wait")
        return
    if Input.is_action_just_pressed("action_y") and state in [State.GROUND, State.SWIM]:
        heavy = not heavy  # Iron Boots toggle (procBootsEquip; 19-frame anim skipped)
        _update_hud()
    _update_prompt()

    match state:
        State.CARRY: _carry()
        State.GRAB: _grab()
        State.VJUMP: _vjump()
        State.HANG: _hang()
        State.CLIMB: _climb()
        State.GROUND: _ground()
        State.AIR: _air()
        State.ROLL: _roll()
        State.SWIM: _swim()
        State.LAND: _land()
        State.ATTACK: _attack()
        State.JUMPCUT: _jumpcut()
        State.JUMPCUT_LAND: _jumpcut_land()
        State.DAMAGE: _damage()
        State.GLIDE: _glide()

    if model:
        model.rotation.y = facing
    if sword_pivot:
        sword_pivot.rotation.y = facing
    _camera_tick()

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
    if Input.is_action_just_pressed("action_a"):
        if prompt_target != null:
            prompt_target.interact(self)
            return
        if speed > 1.0:
            _enter_roll()
            return

    var was_on_floor := is_on_floor()
    _apply(forward() * speed, -1.0)  # small downward push keeps floor contact on slopes
    if is_on_wall():
        speed *= 1.0 - WALL_PUSH_REDUCE * 0.5
        # pushing into a wall: after 7 frames the front-wall type decides hop / catch / jump
        var n := get_wall_normal()
        n.y = 0.0
        if dist > 0.3 and n.length() > 0.1 and forward().dot(-n.normalized()) > 0.7:
            wall_hold += 1
            if wall_hold >= WALL_HOLD_FRAMES and _try_ledge(-n.normalized()):
                return
        else:
            wall_hold = 0
    else:
        wall_hold = 0
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
    # Z-target: face the target (or the camera direction), strafe with atnMove constants
    if lock_target != null and is_instance_valid(lock_target):
        var to_t := lock_target.global_position - global_position
        to_t.y = 0.0
        if to_t.length() > 1.0:
            turn_toward(heading_of(to_t.normalized()), TURN_MAX_STEP, TURN_MIN_STEP, 2.0)
    else:
        facing = cam_yaw_angle()
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
            var side := stick_world_dir(Vector2(signf(s.x), 0.0))
            var a := SIDEHOP_ANGLE * S16_TO_RAD
            _enter_air(side * SIDEHOP_SPEED * cos(a), SIDEHOP_SPEED * sin(a), SIDEHOP_GRAVITY)
            return

    var right := stick_world_dir(Vector2(1.0, 0.0))
    var h := right * strafe.x + forward() * strafe.y
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
    if Input.is_action_just_pressed("action_x") and magic > 0 and not heavy:
        _enter_glide()
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
    # falling past a ledge with the stick pushed toward it: catch it (procHangStart)
    if vy < 0.0 and is_on_wall() and s.length() > 0.3:
        var n := get_wall_normal()
        n.y = 0.0
        if n.length() > 0.1 and stick_world_dir(s).dot(-n.normalized()) > 0.6:
            var h := _ledge_height(-n.normalized())
            if h > LEDGE_SMALL_JUMP_MAX and h < LEDGE_CATCH_MAX:
                ledge_dir = -n.normalized()
                _enter_hang(true)
                return
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

# ---------------------------------------------------------------- ledges

func _ledge_height(into_wall: Vector3) -> float:
    # setFrontWallType: no wall at 170 above the feet -> probe down for the ledge top
    var space := get_world_3d().direct_space_state
    var feet := global_position
    var high := feet + Vector3(0, LEDGE_CATCH_MAX, 0)
    var q := PhysicsRayQueryParameters3D.create(high, high + into_wall * 70.0, 1)
    if space.intersect_ray(q):
        return -1.0  # wall continues above reach
    var over := high + into_wall * 55.0
    var q2 := PhysicsRayQueryParameters3D.create(over, Vector3(over.x, feet.y - 5.0, over.z), 1)
    var hit := space.intersect_ray(q2)
    if not hit:
        return -1.0
    ledge_top = hit.position
    return hit.position.y - feet.y

func _try_ledge(into_wall: Vector3) -> bool:
    var h := _ledge_height(into_wall)
    if h <= LEDGE_MIN or h >= LEDGE_CATCH_MAX:
        return false
    wall_hold = 0
    ledge_dir = into_wall
    facing = heading_of(into_wall)
    if h < LEDGE_SMALL_JUMP_MAX:
        # type 6: small jump onto the ledge (mstepover); launch just high enough
        var vy := sqrt(2.0 * absf(GRAVITY) * (h + 12.0))
        _enter_air(into_wall * 5.0, vy, GRAVITY)
        play_clip("mstepover", 0.05)
        return true
    if h < LEDGE_WALL_CATCH_MAX:
        _enter_hang(false)   # type 7: direct wall catch then climb
        hang_frames = -CATCH_FRAMES
        play_clip("vjmpchb", 2.5 / 30.0, 0.8)
        return true
    # types 8/9: vertical jump, then catch (8) or hang (9) at the apex
    vjump_kind = 8 if h < LEDGE_VJUMP_CATCH_MAX else 9
    state = State.VJUMP
    climb_frame = 0
    velocity.y = sqrt(2.0 * absf(GRAVITY) * (h - HANG_HEIGHT + 160.0)) * 30.0
    play_clip("vjmp", 1.0 / 30.0, 1.0)
    return true

func _vjump() -> void:
    climb_frame += 1
    var vy := velocity.y / 30.0 + GRAVITY
    _apply(ledge_dir * 1.0, vy)
    var hands := global_position.y + HANG_HEIGHT
    if vy <= 0.0 or hands >= ledge_top.y - 2.0 or climb_frame > 40:
        if absf(hands - ledge_top.y) < 60.0:
            _enter_hang(vjump_kind == 9)
            if vjump_kind == 8:
                hang_frames = -CATCH_FRAMES
                play_clip("vjmpchb", 2.5 / 30.0, 0.8)
        else:
            _enter_air(Vector3.ZERO, vy, GRAVITY)

func _enter_hang(wait: bool) -> void:
    state = State.HANG
    velocity = Vector3.ZERO
    speed = 0.0
    hang_frames = 0
    # hands on the ledge, body 8.5 units off the wall
    global_position = Vector3(ledge_top.x, ledge_top.y - HANG_HEIGHT, ledge_top.z) - ledge_dir * 48.5
    facing = heading_of(ledge_dir)
    play_clip("vjmpcha", 2.0 / 30.0, 0.8)
    if not wait:
        pass  # caller decides (wall catch climbs right away)

func _hang() -> void:
    hang_frames += 1
    velocity = Vector3.ZERO
    if hang_frames == 0:          # wall catch finished -> climb at once
        _enter_climb(2.0)
        return
    if hang_frames < 0:
        return
    var s := stick()
    var into := 0.0
    if s.length() > 0.3:
        into = stick_world_dir(s).dot(ledge_dir)
    if hang_frames > 6 and into > 0.5:
        _enter_climb(0.0)
        return
    if Input.is_action_just_pressed("action_a") or (s.length() > 0.3 and into < -0.5):
        # let go (procFall with the 6-frame JMPEDS blend)
        global_position -= ledge_dir * 10.0
        _enter_air(-ledge_dir * 2.0, 0.0, GRAVITY)
        play_clip("jmpeds", 6.0 / 30.0)
        return
    if s.length() > 0.3 and absf(into) < 0.5:
        # shimmy along the ledge at the animation-driven rate (0.7..1.4 x stick)
        var side := stick_world_dir(s)
        var along := side - ledge_dir * side.dot(ledge_dir)
        var rate := lerpf(0.7, 1.4, minf(s.length(), 1.0))
        var step := along.normalized() * 2.2 * rate
        var probe := global_position + step + ledge_dir * 60.0 + Vector3(0, HANG_HEIGHT + 5.0, 0)
        var space := get_world_3d().direct_space_state
        var q := PhysicsRayQueryParameters3D.create(probe, Vector3(probe.x, probe.y - 30.0, probe.z), 1)
        if space.intersect_ray(q):
            global_position += step
            ledge_top += step
            play_clip("hangmover" if along.dot(Vector3(ledge_dir.z, 0.0, -ledge_dir.x)) > 0.0 else "hangmovel", 1.0 / 30.0, rate)
        return
    play_clip("vjmpcha", 2.0 / 30.0, 0.0)

func _enter_climb(start_frame: float) -> void:
    state = State.CLIMB
    climb_frame = int(start_frame / 0.75)
    climb_from = global_position
    play_clip("vjmpcl", 5.0 / 30.0, 0.75)
    if anim and anim.has_animation("vjmpcl"):
        anim.seek(start_frame / 30.0, true)

func _climb() -> void:
    climb_frame += 1
    # root motion approximation: rise first, then move forward onto the ledge over the clip
    var t := clampf(float(climb_frame) / CLIMB_FRAMES, 0.0, 1.0)
    var up := smoothstep(0.0, 0.6, t)
    var fwd := smoothstep(0.45, 1.0, t)
    var target := Vector3(ledge_top.x, ledge_top.y + 2.0, ledge_top.z) + ledge_dir * 45.0
    var pos := climb_from
    pos.y = lerpf(climb_from.y, target.y, up)
    var flat := Vector3(lerpf(climb_from.x, target.x, fwd), pos.y, lerpf(climb_from.z, target.z, fwd))
    global_position = flat
    velocity = Vector3.ZERO
    if climb_frame >= CLIMB_FRAMES or (climb_frame >= CLIMB_CANCEL and stick().length() > 0.5):
        global_position = target
        speed = 0.0
        _enter_ground()

# ---------------------------------------------------------------- interaction / carrying

func _update_prompt() -> void:
    prompt_target = null
    var best := ""
    if state in [State.GROUND, State.CARRY]:
        for n in get_tree().get_nodes_in_group("interact"):
            if not is_instance_valid(n) or n == held:
                continue
            var to_n: Vector3 = n.global_position - global_position
            to_n.y = 0.0
            if to_n.length() > 220.0:
                continue
            if to_n.length() > 30.0 and forward().dot(to_n.normalized()) < 0.2:
                continue  # must roughly face it
            var p: String = n.interact_prompt(self)
            if p != "" and state == State.GROUND:
                prompt_target = n
                best = p
                break
    if state == State.CARRY:
        best = "Throw"
    if hud_prompt:
        hud_prompt.text = ("A: " + best) if best != "" else ""

func carry(node: Node3D) -> void:
    # lift: d_a_player_grab - Link stops, grabup anim, then carries at walk speed
    held = node
    node.picked_up(self)
    state = State.GRAB
    grab_frames = 0
    speed = 0.0
    play_clip("grabup", 0.1)

func carry_point() -> Vector3:
    return global_position + Vector3(0, 175.0, 0) + forward() * 10.0

func _grab() -> void:
    grab_frames += 1
    _apply(Vector3.ZERO, -1.0)
    if grab_frames >= 12:
        state = State.CARRY
        play_clip("grabwait")

func _carry() -> void:
    if held == null or not is_instance_valid(held):
        held = null
        _enter_ground()
        return
    var s := stick()
    var dist := minf(s.length(), 1.0)
    if dist > 0.05:
        turn_toward(heading_of(stick_world_dir(s)), TURN_MAX_STEP, TURN_MIN_STEP, TURN_DIVISOR)
        var target_speed := RUN_SPEED_MAX * dist * (0.8 if held.get("kind") == "ootubo1" else 1.0)
        speed = minf(speed + RUN_ACCEL * dist, target_speed) if speed < target_speed else target_speed
        play_clip("walkbarrel" if held.get("kind") == "ootubo1" else "walk", ANIM_BLEND, maxf(dist, 0.5))
    else:
        _decel_to(0.0)
        play_clip("grabwait")
    _apply(forward() * speed, -1.0)
    if Input.is_action_just_pressed("action_a"):
        var h := held
        held = null
        h.thrown(forward(), speed)
        play_clip("grabthrow", 0.05)
        state = State.LAND
        land_frames = 10
        return
    if not is_on_floor():
        _enter_air(forward() * speed, 0.0, GRAVITY)
        if held:
            var h2 := held
            held = null
            h2.thrown(forward(), speed)

func add_rupees(n: int) -> void:
    rupees = mini(rupees + n, 5000)
    _update_hud()

# ---------------------------------------------------------------- Deku Leaf

func _enter_glide() -> void:
    # procFanGlide_init: pop up 15, then glide with its own gravity / terminal speed
    state = State.GLIDE
    glide_frames = 0
    glide_magic_timer = GLIDE_MAGIC_INTERVAL
    velocity.y = GLIDE_DEPLOY_SPEED_Y * 30.0
    gravity = GLIDE_GRAVITY
    speed = GLIDE_FORWARD_SPEED
    fall_start_y = global_position.y
    play_clip("mjmp", 0.0, 0.5)  # no USEFANB clip exported yet; slow jump pose stands in

func _glide() -> void:
    glide_frames += 1
    if in_water():
        _enter_swim()
        return
    var s := stick()
    var dist := minf(s.length(), 1.0)
    if dist > 0.05:
        turn_toward(heading_of(stick_world_dir(s)), TURN_MAX_STEP, TURN_MIN_STEP, TURN_DIVISOR)
    # forward speed chases 12 * stick * cos(stick angle - facing): addCalc(0.5, 0.1+0.4*stick, 0.01)
    var want := 0.0
    if dist > 0.05:
        var off := wrapf(heading_of(stick_world_dir(s)) - facing, -PI, PI)
        want = GLIDE_FORWARD_SPEED * dist * cos(off)
    var rem := want - speed
    var step := clampf(absf(rem) * 0.5, 0.01, 0.1 + 0.4 * dist)
    speed = want if absf(rem) <= step else speed + signf(rem) * step
    var vy := velocity.y / 30.0
    if vy < -GLIDE_GRAVITY:
        vy = maxf(vy + GLIDE_GRAVITY, GLIDE_MAX_FALL)
    else:
        vy += GRAVITY  # still rising from the deploy pop: normal gravity until it stops
    glide_magic_timer -= 1
    if glide_magic_timer <= 0:
        glide_magic_timer = GLIDE_MAGIC_INTERVAL
        magic = maxi(magic - 1, 0)
        _update_hud()
    _apply(forward() * speed, vy)
    var cancel: bool = glide_frames > GLIDE_CANCEL_LOCKOUT and (Input.is_action_just_pressed("action_a") or Input.is_action_just_pressed("action_b") or Input.is_action_just_pressed("action_x"))
    if is_on_floor():
        land_frames = 8
        state = State.LAND
        play_clip("jmped", 5.0 / 30.0, GLIDE_LAND_RATE)
        return
    if cancel or magic <= 0:
        _enter_air(forward() * speed, vy, GRAVITY)

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
    if hud_magic:
        hud_magic.text = "MP " + "\\u2588".repeat(magic) + "\\u2591".repeat(MAGIC_MAX - magic)
    if hud_rupees:
        hud_rupees.text = "\\u25c6 %d" % rupees
    if hud_items:
        hud_items.text = "B sword   A roll/jump   R/Z target   X Deku Leaf   Y Iron Boots%s" % (" [ON]" if heavy else "")

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

[node name="Magic" type="Label" parent="HUD"]
offset_left = 24.0
offset_top = 62.0
offset_right = 600.0
offset_bottom = 96.0
theme_override_font_sizes/font_size = 20
theme_override_colors/font_color = Color(0.35, 0.9, 0.45, 1)
text = ""

[node name="Rupees" type="Label" parent="HUD"]
offset_left = 24.0
offset_top = 96.0
offset_right = 300.0
offset_bottom = 130.0
theme_override_font_sizes/font_size = 24
theme_override_colors/font_color = Color(0.4, 0.95, 0.5, 1)
text = ""

[node name="Prompt" type="Label" parent="HUD"]
anchors_preset = 7
anchor_left = 0.5
anchor_top = 1.0
anchor_right = 0.5
anchor_bottom = 1.0
offset_left = -200.0
offset_top = -110.0
offset_right = 200.0
offset_bottom = -70.0
grow_horizontal = 2
grow_vertical = 0
horizontal_alignment = 1
theme_override_font_sizes/font_size = 26
theme_override_colors/font_color = Color(0.95, 0.95, 0.7, 1)
text = ""

[node name="Reticle" type="Label" parent="HUD"]
visible = false
offset_right = 48.0
offset_bottom = 48.0
horizontal_alignment = 1
vertical_alignment = 1
theme_override_font_sizes/font_size = 40
theme_override_colors/font_color = Color(1, 0.85, 0.2, 1)
text = "◎"

[node name="Items" type="Label" parent="HUD"]
anchors_preset = 3
anchor_left = 1.0
anchor_top = 1.0
anchor_right = 1.0
anchor_bottom = 1.0
offset_left = -760.0
offset_top = -40.0
offset_right = -16.0
offset_bottom = -10.0
grow_horizontal = 0
grow_vertical = 0
horizontal_alignment = 2
theme_override_font_sizes/font_size = 16
theme_override_colors/font_color = Color(0.85, 0.85, 0.85, 0.85)
text = ""

[node name="CamRig" type="Node3D" parent="."]
top_level = true

[node name="Camera3D" type="Camera3D" parent="CamRig"]
near = 5.0
far = 1000000.0
fov = 60.0
"""


# player animation clips kept in link.glb (the model ships 594; these drive movement)
_PLAYER_CLIPS = (
    "wait", "walk", "dash", "mjmp", "jmped", "mrolll", "swimwait", "swiming",
    "cuta", "cutf", "cutr", "cutl", "cutea", "cuteb", "jattack", "jattackland",
    "damf", "damb", "daml", "damr", "dam", "damff", "damfb", "talka",
    "grabup", "grabwait", "grabthrow", "walkbarrel",
    "vjmp", "vjmpcha", "vjmpchb", "vjmpcl", "mstepover", "hangmovel", "hangmover", "jmpeds",
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
var messages: Dictionary = {}   # BMG message id -> text (gcrip msg)
var dialog: Node = null
var dialog_open := false

func _ready() -> void:
    var f := FileAccess.open("res://stage_data.json", FileAccess.READ)
    if f:
        var parsed = JSON.parse_string(f.get_as_text())
        if parsed is Dictionary:
            stage_data = parsed
    var m := FileAccess.open("res://messages.json", FileAccess.READ)
    if m:
        var parsed_m = JSON.parse_string(m.get_as_text())
        if parsed_m is Array:
            for e in parsed_m:
                messages[int(e["id"])] = str(e["text"])
    _apply_saved_pad_mappings()
    Input.joy_connection_changed.connect(func(_id, _c): _apply_saved_pad_mappings())

# ---- world helpers used by actors

func player() -> Node3D:
    var list := get_tree().get_nodes_in_group("player")
    return list[0] if list.size() > 0 else null

func ground_height(pos: Vector3) -> float:
    var scene: Node3D = get_tree().current_scene as Node3D
    if scene == null:
        return pos.y
    var space: PhysicsDirectSpaceState3D = scene.get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(pos + Vector3(0, 200, 0), pos - Vector3(0, 5000, 0), 1)
    var hit: Dictionary = space.intersect_ray(q)
    return hit.position.y if hit else pos.y - 5000.0

func line_of_sight(a: Vector3, b: Vector3) -> bool:
    var scene: Node3D = get_tree().current_scene as Node3D
    if scene == null:
        return true
    var space: PhysicsDirectSpaceState3D = scene.get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(a, b, 1)
    return not space.intersect_ray(q)

func spawn_drop(params: int, pos: Vector3) -> void:
    # pots/grass: item no in params bits 0-5 (0x3F none, 0x20+ = drop table -> mostly green rupees)
    var item_no := params & 0x3F
    if item_no == 0x3F:
        return
    var id := item_no
    if item_no >= 0x20:
        var r := randf()
        id = 1 if r < 0.7 else (0 if r < 0.9 else 2)
    spawn_item(id, pos + Vector3(0, 20, 0))

func spawn_item(item_id: int, pos: Vector3) -> void:
    var scene := get_tree().current_scene
    if scene == null:
        return
    var s: Script = load("res://actors/item.gd")
    var it: Area3D = s.new()
    scene.add_child(it)
    it.global_position = pos
    it.setup(item_id, null, false)
    it.vy = 23.0  # pop up like a pot drop (POP_VY)

func burst(pos: Vector3, color: Color) -> void:
    var scene := get_tree().current_scene
    if scene == null:
        return
    var p := GPUParticles3D.new()
    p.one_shot = true
    p.emitting = true
    p.amount = 24
    p.lifetime = 0.6
    p.explosiveness = 1.0
    var mat := ParticleProcessMaterial.new()
    mat.direction = Vector3(0, 1, 0)
    mat.spread = 80.0
    mat.initial_velocity_min = 150.0
    mat.initial_velocity_max = 400.0
    mat.gravity = Vector3(0, -900, 0)
    mat.scale_min = 6.0
    mat.scale_max = 14.0
    mat.color = color
    p.process_material = mat
    var mesh := BoxMesh.new()
    mesh.size = Vector3(1, 1, 1)
    p.draw_pass_1 = mesh
    scene.add_child(p)
    p.global_position = pos
    get_tree().create_timer(1.5).timeout.connect(p.queue_free)

# ---- dialogue

func npc_messages(actor: String) -> Array:
    # first lines of a few known conversations; the full graphs live in the decomp
    match actor:
        "NpcSo":
            return [1303, 1304] if messages.has(1303) else []
    return []

func _ensure_dialog() -> void:
    if dialog == null:
        dialog = load("res://dialog.tscn").instantiate()
        add_child(dialog)
        dialog.closed.connect(func(): dialog_open = false)

func show_text(text: String) -> void:
    _ensure_dialog()
    dialog_open = true
    dialog.show_pages(_paginate(text))

func show_message(id: int) -> void:
    show_text(messages.get(id, "(message %d not found)" % id))

func show_messages(ids: Array) -> void:
    var pages: Array = []
    for id in ids:
        pages.append_array(_paginate(messages.get(int(id), "(message %d)" % int(id))))
    _ensure_dialog()
    dialog_open = true
    dialog.show_pages(pages)

func _paginate(text: String) -> Array:
    var t := text.replace("{name}", "Link")
    var re := RegEx.new()
    re.compile("\\\\{[^}]*\\\\}")
    t = re.sub(t, "", true)
    var lines := t.split("\\n")
    var pages: Array = []
    var cur: Array = []
    for ln in lines:
        cur.append(ln)
        if cur.size() >= 3:
            pages.append("\\n".join(cur))
            cur = []
    if cur.size() > 0 and "".join(cur).strip_edges() != "":
        pages.append("\\n".join(cur))
    return pages if pages.size() > 0 else [t]

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

# ----------------------------------------------------------------------------- actors
# Behaviours for placed actors. Constants come from the decomp specs in memRip
# (knowledge/gamecube/actors/*.md); units are game units per 30 fps frame.

_ACTOR_BASE_GD = """extends CharacterBody3D
# gcrip: base for small carriable / throwable props (pots d_a_tsubo, pebbles d_a_stone).
# Modes from the decomp: WAIT, CARRY, DROP (thrown), SINK. The prop keeps its own
# integrator: gravity per frame, breaks on ground/wall contact while thrown, on
# sword hits, on falls > 200 units, and sinks silently in water.
class_name GcripCarriable

const KINDS := {
    # name: gravity, throw fwd, throw up, radius, height, break on fall, item drop
    "kotubo":  {"g": -6.0, "fwd": 36.0, "up": 27.0, "r": 30.0, "h": 60.0,  "hp": 1},
    "ootubo1": {"g": -6.5, "fwd": 43.0, "up": 22.0, "r": 50.0, "h": 100.0, "hp": 1},
    "koisi1":  {"g": -6.0, "fwd": 36.0, "up": 27.0, "r": 30.0, "h": 35.0,  "hp": 99},
    "Ktaru":   {"g": -6.0, "fwd": 36.0, "up": 27.0, "r": 35.0, "h": 70.0,  "hp": 1},
}
const MAX_FALL := -100.0
const BREAK_FALL_HEIGHT := 200.0
const WAIT_FRICTION := 0.5
const SPIN_PITCH := 0x7D0 * PI / 32768.0   # 11.25 deg/frame tumble while thrown

enum Mode { WAIT, CARRY, DROP, SINK }
var mode: int = Mode.WAIT
var kind := "kotubo"
var k: Dictionary = KINDS["kotubo"]
var params := 0
var mesh: Node3D = null
var speed := 0.0
var dir := Vector3.FORWARD
var carrier: Node3D = null
var fall_start_y := 0.0
var home := Vector3.ZERO
var hp := 1
var tumble := 0.0

func setup(actor: String, p: int, mesh_node: Node3D) -> void:
    kind = actor
    k = KINDS.get(actor, KINDS["kotubo"])
    params = p
    hp = int(k["hp"])
    mesh = mesh_node
    home = global_position
    collision_layer = 8          # hittable by the sword
    collision_mask = 1           # world
    var shape := CollisionShape3D.new()
    var cyl := CylinderShape3D.new()
    cyl.radius = float(k["r"])
    cyl.height = float(k["h"])
    shape.shape = cyl
    shape.position.y = float(k["h"]) / 2.0
    add_child(shape)
    add_to_group("interact")

# --- Link-side interaction API ---
func interact_prompt(link: Node3D) -> String:
    if mode != Mode.WAIT:
        return ""
    var d := link.global_position.distance_to(global_position)
    return "Grab" if d < (100.0 if kind == "ootubo1" else 80.0) else ""

func interact(link: Node3D) -> void:
    if mode == Mode.WAIT:
        link.call("carry", self)

func picked_up(by: Node3D) -> void:
    mode = Mode.CARRY
    carrier = by
    velocity = Vector3.ZERO
    collision_layer = 0
    collision_mask = 0

func thrown(direction: Vector3, _link_speed: float) -> void:
    # the pot overrides Link's throw with its own velocity (d_a_tsubo)
    mode = Mode.DROP
    carrier = null
    dir = direction.normalized()
    speed = float(k["fwd"])
    velocity.y = float(k["up"]) * 30.0
    fall_start_y = global_position.y
    collision_mask = 1
    tumble = 0.0

func take_hit(_damage: int, _from: Vector3) -> void:
    if mode == Mode.CARRY:
        return
    hp -= 1
    if hp <= 0:
        _break()

func _physics_process(_delta: float) -> void:
    match mode:
        Mode.CARRY:
            if carrier:
                global_position = carrier.call("carry_point")
        Mode.WAIT:
            if speed > 0.1:
                speed = maxf(speed - WAIT_FRICTION, 0.0)
            var vy: float = velocity.y / 30.0 + float(k["g"])
            velocity = Vector3(dir.x * speed, maxf(vy, MAX_FALL), dir.z * speed) * 30.0
            move_and_slide()
            if is_on_floor():
                velocity.y = 0.0
        Mode.DROP:
            var vy: float = velocity.y / 30.0 + float(k["g"])
            vy = maxf(vy, MAX_FALL)
            fall_start_y = maxf(fall_start_y, global_position.y)
            velocity = Vector3(dir.x * speed, vy, dir.z * speed) * 30.0
            tumble += SPIN_PITCH
            if mesh:
                mesh.rotation.x = tumble
            var col := move_and_collide(velocity / 30.0)
            if col:
                var hit := col.get_collider()
                if hit and hit.has_method("take_hit") and hit != self:
                    hit.take_hit(2, global_position)
                if kind == "koisi1" and fall_start_y - global_position.y < BREAK_FALL_HEIGHT and col.get_normal().y > 0.7:
                    # pebbles survive a gentle landing
                    mode = Mode.WAIT
                    speed *= 0.3
                    velocity.y = 0.0
                    if mesh:
                        mesh.rotation.x = 0.0
                else:
                    _break()
        Mode.SINK:
            global_position.y -= 2.0
            if global_position.y < home.y - 300.0:
                queue_free()

func _break() -> void:
    mode = Mode.SINK
    if mesh:
        mesh.visible = false
    collision_layer = 0
    collision_mask = 0
    Game.spawn_drop(params, global_position)
    Game.burst(global_position, Color(0.75, 0.6, 0.45))
    queue_free()
"""

_ACTOR_ITEM_GD = """extends Area3D
# gcrip: collectible (d_a_item): rupees, hearts. Placed items (type 1/3) only spin;
# dropped items fall with gravity -7 and bounce (reflect 0.62), then wait 240 frames
# and blink for 60 before vanishing.

const VALUES := {1: 1, 2: 5, 3: 10, 4: 20, 5: 50, 6: 100, 15: 200}
const COLORS := {1: Color(0.2, 0.9, 0.3), 2: Color(0.3, 0.5, 1.0), 3: Color(1.0, 0.9, 0.2),
    4: Color(1.0, 0.25, 0.25), 5: Color(0.7, 0.3, 0.9), 6: Color(1.0, 0.6, 0.2), 15: Color(0.85, 0.85, 0.95)}
const GRAVITY := -7.0
const REFLECT := 0.62
const SPIN := 799 * PI / 32768.0     # 799 s16/frame
const WAIT_TIME := 240
const DISAPPEAR_TIME := 60

var item_id := 1
var placed := true
var vy := 0.0
var life := 0
var mesh: Node3D = null

func setup(p: int, mesh_node: Node3D, is_placed: bool) -> void:
    item_id = p & 0xFF
    placed = is_placed
    mesh = mesh_node
    if mesh == null:
        mesh = _make_mesh()
        add_child(mesh)
    var shape := CollisionShape3D.new()
    var cyl := CylinderShape3D.new()
    var heart := item_id == 0
    cyl.radius = 30.0 if heart else 35.0
    cyl.height = 40.0 if heart else 55.0
    shape.shape = cyl
    shape.position.y = cyl.height / 2.0
    add_child(shape)
    collision_layer = 16
    collision_mask = 0
    monitoring = false

func _make_mesh() -> Node3D:
    var mi := MeshInstance3D.new()
    var heart := item_id == 0
    if heart:
        var sm := SphereMesh.new()
        sm.radius = 14.0
        sm.height = 28.0
        mi.mesh = sm
    else:
        var pm := PrismMesh.new()
        pm.size = Vector3(22.0, 40.0, 12.0)
        mi.mesh = pm
    var mat := StandardMaterial3D.new()
    mat.albedo_color = Color(1, 0.2, 0.3) if heart else COLORS.get(item_id, Color.GREEN)
    mat.emission_enabled = true
    mat.emission = mat.albedo_color
    mat.emission_energy_multiplier = 0.6
    mi.material_override = mat
    mi.position.y = 28.0
    return mi

func _physics_process(_delta: float) -> void:
    if mesh:
        mesh.rotation.y += SPIN
    if not placed:
        vy = maxf(vy + GRAVITY, -100.0)
        global_position.y += vy
        var floor_y := Game.ground_height(global_position)
        if global_position.y <= floor_y:
            global_position.y = floor_y
            if vy < -3.0:
                vy = -vy * REFLECT
            else:
                vy = 0.0
        life += 1
        if life > WAIT_TIME and mesh:
            mesh.visible = (life / 3) % 2 == 0
        if life > WAIT_TIME + DISAPPEAR_TIME:
            queue_free()
            return
    var link := Game.player()
    if link and link.global_position.distance_to(global_position) < 60.0:
        _collect(link)

func _collect(link: Node) -> void:
    if item_id == 0:
        link.call("heal", 4)
    elif VALUES.has(item_id):
        link.call("add_rupees", VALUES[item_id])
    queue_free()
"""

_ACTOR_SIGN_GD = """extends StaticBody3D
# gcrip: signpost (d_a_kanban): read with A from the front (150 units, facing it);
# a sword cut knocks it over (the original splits it into pieces and it regrows).

var message_id := 0
var mesh: Node3D = null
var down := 0
var facing := 0.0

func setup(p: int, mesh_node: Node3D, rot_y_deg: float) -> void:
    message_id = p & 0xFFFF
    mesh = mesh_node
    facing = deg_to_rad(rot_y_deg)
    collision_layer = 1 | 8
    var shape := CollisionShape3D.new()
    var cyl := CylinderShape3D.new()
    cyl.radius = 50.0
    cyl.height = 105.0
    shape.shape = cyl
    shape.position.y = 52.0
    add_child(shape)
    add_to_group("interact")

func interact_prompt(link: Node3D) -> String:
    if down > 0:
        return ""
    var to_link := link.global_position - global_position
    to_link.y = 0.0
    if to_link.length() > 150.0:
        return ""
    return "Read"

func interact(_link: Node3D) -> void:
    Game.show_message(message_id)

func take_hit(_damage: int, from: Vector3) -> void:
    if down > 0:
        return
    down = 30 * 20
    var away := global_position - from
    away.y = 0.0
    if mesh:
        var t := mesh.create_tween()
        t.tween_property(mesh, "rotation", Vector3(PI / 2.0 * signf(-away.z + 0.001), mesh.rotation.y, 0.0), 0.3)

func _physics_process(_delta: float) -> void:
    if down > 0:
        down -= 1
        if down == 0 and mesh:
            mesh.rotation.x = 0.0
            mesh.rotation.z = 0.0
"""

_ACTOR_CHEST_GD = """extends StaticBody3D
# gcrip: treasure chest (d_a_tbox). Open from the front within 100 units and 45 deg;
# item id lives in rot.z >> 8; item-get text is message 101 + item id.

var item_id := 0
var opened := false
var mesh: Node3D = null
var facing := 0.0

func setup(rot_z: int, mesh_node: Node3D, rot_y_deg: float) -> void:
    item_id = (rot_z >> 8) & 0xFF
    mesh = mesh_node
    facing = deg_to_rad(rot_y_deg)
    collision_layer = 1
    var shape := CollisionShape3D.new()
    var box := BoxShape3D.new()
    box.size = Vector3(110.0, 90.0, 80.0)
    shape.shape = box
    shape.position.y = 45.0
    shape.rotation.y = facing
    add_child(shape)
    add_to_group("interact")

func interact_prompt(link: Node3D) -> String:
    if opened:
        return ""
    var to_link := link.global_position - global_position
    to_link.y = 0.0
    if to_link.length() > 100.0:
        return ""
    var front := Vector3(sin(facing), 0.0, cos(facing))
    if front.dot(to_link.normalized()) < cos(PI / 4.0):
        return ""
    return "Open"

func interact(link: Node3D) -> void:
    opened = true
    if mesh:
        var t := mesh.create_tween()
        t.tween_property(mesh, "scale", mesh.scale * Vector3(1.05, 1.2, 1.05), 0.25)
        t.tween_property(mesh, "scale", mesh.scale, 0.25)
    Game.burst(global_position + Vector3(0, 60, 0), Color(1.0, 0.95, 0.6))
    if item_id in [1, 2, 3, 4, 5, 6, 15]:
        link.call("add_rupees", {1: 1, 2: 5, 3: 10, 4: 20, 5: 50, 6: 100, 15: 200}[item_id])
    elif item_id == 0:
        link.call("heal", 4)
    Game.show_message(101 + item_id)
"""

_ACTOR_PIG_GD = """extends CharacterBody3D
# gcrip: pig (d_a_kb): wanders around its spawn (radius 300), flees when Link comes
# within 200 units until 400 away; can be picked up and thrown like a pot.
# Constants: walk 3 u/f (accel 2), run 12, gravity -3, terminal -20, idle/walk 50+rnd(50).

const WALK := 3.0
const RUN := 12.0
const ACCEL := 2.0
const GRAVITY := -3.0
const TERMINAL := -20.0
const FLEE_DIST := 200.0
const FLEE_STOP := 400.0
const WANDER_R := 300.0
const TURN_WALK := 0x800 * PI / 32768.0
const TURN_RUN := 0x2000 * PI / 32768.0

enum Sub { WAIT, WALK, FLEE, CARRY, THROWN }
var sub: int = Sub.WAIT
var timer := 0
var home := Vector3.ZERO
var target := Vector3.ZERO
var facing := 0.0
var speed := 0.0
var mesh: Node3D = null
var carrier: Node3D = null
var anim: AnimationPlayer = null

func setup(_p: int, mesh_node: Node3D, rot_y_deg: float) -> void:
    mesh = mesh_node
    home = global_position
    facing = deg_to_rad(rot_y_deg)
    collision_layer = 1 | 8
    collision_mask = 1
    var shape := CollisionShape3D.new()
    var cyl := CylinderShape3D.new()
    cyl.radius = 25.0
    cyl.height = 35.0
    shape.shape = cyl
    shape.position.y = 17.5
    add_child(shape)
    add_to_group("interact")
    timer = 50 + randi() % 50

func interact_prompt(link: Node3D) -> String:
    if sub in [Sub.CARRY, Sub.THROWN]:
        return ""
    return "Grab" if link.global_position.distance_to(global_position) < 90.0 else ""

func interact(link: Node3D) -> void:
    link.call("carry", self)

func picked_up(by: Node3D) -> void:
    sub = Sub.CARRY
    carrier = by
    collision_layer = 0
    collision_mask = 0

func thrown(direction: Vector3, _s: float) -> void:
    sub = Sub.THROWN
    carrier = null
    facing = atan2(direction.x, direction.z)
    speed = 20.0
    velocity.y = 20.0 * 30.0
    collision_mask = 1
    collision_layer = 1 | 8

func take_hit(_d: int, from: Vector3) -> void:
    var away := global_position - from
    away.y = 0.0
    if away.length() > 0.1:
        facing = atan2(away.x, away.z)
    sub = Sub.FLEE
    timer = 60

func _turn_to(t: float, step: float) -> void:
    var rem := wrapf(t - facing, -PI, PI)
    facing += clampf(rem, -step, step)

func _physics_process(_delta: float) -> void:
    if sub == Sub.CARRY:
        if carrier:
            global_position = carrier.call("carry_point")
        return
    var link := Game.player()
    var to_link := Vector3.ZERO
    if link:
        to_link = link.global_position - global_position
        to_link.y = 0.0
    match sub:
        Sub.WAIT:
            speed = maxf(speed - ACCEL, 0.0)
            timer -= 1
            if timer <= 0:
                sub = Sub.WALK
                timer = 50 + randi() % 50
                var a := randf() * TAU
                target = home + Vector3(cos(a), 0.0, sin(a)) * randf() * WANDER_R
            if link and to_link.length() < FLEE_DIST:
                sub = Sub.FLEE
        Sub.WALK:
            var to_t := target - global_position
            to_t.y = 0.0
            _turn_to(atan2(to_t.x, to_t.z), TURN_WALK)
            speed = minf(speed + ACCEL, WALK)
            timer -= 1
            if timer <= 0 or to_t.length() < 30.0:
                sub = Sub.WAIT
                timer = 50 + randi() % 50
            if link and to_link.length() < FLEE_DIST:
                sub = Sub.FLEE
        Sub.FLEE:
            if link:
                _turn_to(atan2(-to_link.x, -to_link.z), TURN_RUN)
            speed = minf(speed + ACCEL, RUN)
            timer -= 1
            if (link and to_link.length() > FLEE_STOP) or timer <= 0:
                sub = Sub.WAIT
                timer = 30
        Sub.THROWN:
            pass
    var vy := velocity.y / 30.0 + GRAVITY
    vy = maxf(vy, TERMINAL)
    velocity = Vector3(sin(facing) * speed, vy, cos(facing) * speed) * 30.0
    move_and_slide()
    if is_on_floor():
        velocity.y = 0.0
        if sub == Sub.THROWN:
            sub = Sub.FLEE
            timer = 60
            speed = RUN
    if is_on_wall() and sub == Sub.WALK:
        sub = Sub.WAIT
        timer = 20
    if mesh:
        mesh.rotation.y = facing
    if anim == null and mesh:
        anim = mesh.find_child("AnimationPlayer", true, false)
"""

_ACTOR_GULL_GD = """extends Node3D
# gcrip: seagull (d_a_kamome, free type): wanders in the air around its spawn point,
# banking into turns; glide speed ~10 u/f, rise +5 u/f when below its cruise height.

const SPEED := 10.0
const TURN := 0x300 * PI / 32768.0
const CRUISE := 350.0

var home := Vector3.ZERO
var target := Vector3.ZERO
var yaw := 0.0
var bank := 0.0
var mesh: Node3D = null
var timer := 0

func setup(_p: int, mesh_node: Node3D, rot_y_deg: float) -> void:
    mesh = mesh_node
    home = global_position
    yaw = deg_to_rad(rot_y_deg)
    _pick()

func _pick() -> void:
    var a := randf() * TAU
    target = home + Vector3(cos(a) * randf_range(200.0, 700.0), CRUISE + randf_range(-80.0, 120.0), sin(a) * randf_range(200.0, 700.0))
    timer = 90 + randi() % 120

func _physics_process(_delta: float) -> void:
    timer -= 1
    var to_t := target - global_position
    var flat := Vector3(to_t.x, 0.0, to_t.z)
    if timer <= 0 or flat.length() < 60.0:
        _pick()
    var want := atan2(flat.x, flat.z)
    var rem := wrapf(want - yaw, -PI, PI)
    var step := clampf(rem, -TURN, TURN)
    yaw += step
    bank = lerpf(bank, -step * 25.0, 0.15)
    var vy := clampf(to_t.y * 0.05, -4.0, 5.0)
    global_position += Vector3(sin(yaw) * SPEED, vy, cos(yaw) * SPEED)
    if mesh:
        mesh.rotation = Vector3(0.0, yaw, bank)
"""

_ACTOR_NPC_GD = """extends Node3D
# gcrip: talkable NPC. The Fishman (NpcSo) bobs at the water surface and circles
# near its spawn; others stand still. Talk with A from 150 units: plays the message
# ids configured per actor (conversation graphs live in the decomp's next_msgStatus).

var messages: Array = []
var mesh: Node3D = null
var home := Vector3.ZERO
var t := 0.0
var swimmer := false
var facing := 0.0

func setup(actor: String, _p: int, mesh_node: Node3D, rot_y_deg: float) -> void:
    mesh = mesh_node
    home = global_position
    facing = deg_to_rad(rot_y_deg)
    swimmer = actor == "NpcSo"
    messages = Game.npc_messages(actor)
    var body := StaticBody3D.new()
    body.collision_layer = 1
    var shape := CollisionShape3D.new()
    var cyl := CylinderShape3D.new()
    cyl.radius = 40.0
    cyl.height = 120.0
    shape.shape = cyl
    shape.position.y = 60.0
    body.add_child(shape)
    add_child(body)
    add_to_group("interact")

func interact_prompt(link: Node3D) -> String:
    return "Talk" if link.global_position.distance_to(global_position) < 150.0 else ""

func interact(link: Node3D) -> void:
    var to_link := link.global_position - global_position
    facing = atan2(to_link.x, to_link.z)
    if messages.is_empty():
        Game.show_text("...")
    else:
        Game.show_messages(messages)

func _physics_process(_delta: float) -> void:
    t += 1.0
    if swimmer:
        var a := t * 0.01
        global_position = home + Vector3(cos(a) * 120.0, sin(t * 0.08) * 6.0, sin(a) * 120.0)
        facing = a + PI / 2.0
    if mesh:
        mesh.rotation.y = facing
"""

_ACTOR_BOKOBLIN_GD = """extends CharacterBody3D
# gcrip: Bokoblin (d_a_bk): stands/patrols, notices Link within sight range, runs in,
# swings its stick when close, flinches on hits, dies after hp hits.
# Per-frame constants from the spec (speed x 0.25): walk 3, run 11.25, gravity 3, terminal 50,
# jump 16-19. Attack reach ~100 units, notice ~1000 with line of sight.

const WALK := 3.0
const RUN := 11.25
const GRAVITY := -3.0
const TERMINAL := -50.0
const NOTICE := 1000.0
const ATTACK_RANGE := 110.0
const TURN := 0x600 * PI / 32768.0
const HP := 3
const DAMAGE_TO_LINK := 2   # quarter hearts (stick)

enum Act { STAND, FIGHT_RUN, FIGHT, ATTACK, DAMAGE, DEAD }
var act: int = Act.STAND
var hp := HP
var facing := 0.0
var speed := 0.0
var timer := 0
var mesh: Node3D = null
var anim: AnimationPlayer = null
var home := Vector3.ZERO
var hit_done := false

func setup(_p: int, mesh_node: Node3D, rot_y_deg: float) -> void:
    mesh = mesh_node
    home = global_position
    facing = deg_to_rad(rot_y_deg)
    collision_layer = 1 | 8
    collision_mask = 1
    var shape := CollisionShape3D.new()
    var cyl := CylinderShape3D.new()
    cyl.radius = 40.0
    cyl.height = 100.0
    shape.shape = cyl
    shape.position.y = 50.0
    add_child(shape)
    add_to_group("enemy")

func take_hit(damage: int, from: Vector3) -> void:
    if act == Act.DEAD:
        return
    hp -= damage
    var away := global_position - from
    away.y = 0.0
    facing = atan2(-away.x, -away.z)
    if hp <= 0:
        act = Act.DEAD
        timer = 40
        Game.burst(global_position + Vector3(0, 50, 0), Color(0.5, 0.2, 0.6))
        return
    act = Act.DAMAGE
    timer = 12
    speed = -8.0

func _turn_to(t: float) -> void:
    var rem := wrapf(t - facing, -PI, PI)
    facing += clampf(rem, -TURN, TURN)

func _physics_process(_delta: float) -> void:
    var link := Game.player()
    var to_link := Vector3.ZERO
    var dist := 1.0e9
    if link:
        to_link = link.global_position - global_position
        to_link.y = 0.0
        dist = to_link.length()
    match act:
        Act.STAND:
            speed = 0.0
            if link and dist < NOTICE and Game.line_of_sight(global_position + Vector3(0, 80, 0), link.global_position + Vector3(0, 80, 0)):
                act = Act.FIGHT_RUN
        Act.FIGHT_RUN:
            _turn_to(atan2(to_link.x, to_link.z))
            speed = RUN
            if dist < ATTACK_RANGE:
                act = Act.ATTACK
                timer = 30
                hit_done = false
                speed = 0.0
            elif dist > NOTICE * 1.5:
                act = Act.STAND
        Act.ATTACK:
            timer -= 1
            if timer == 14 and not hit_done and link and dist < ATTACK_RANGE + 20.0:
                hit_done = true
                link.call("take_damage", DAMAGE_TO_LINK, global_position)
            if timer <= 0:
                act = Act.FIGHT_RUN
        Act.DAMAGE:
            timer -= 1
            speed = minf(speed + 1.0, 0.0)
            if timer <= 0:
                act = Act.FIGHT_RUN
        Act.DEAD:
            timer -= 1
            if mesh:
                mesh.scale = mesh.scale * 0.92
            if timer <= 0:
                queue_free()
            return
    var vy := velocity.y / 30.0 + GRAVITY
    vy = maxf(vy, TERMINAL)
    velocity = Vector3(sin(facing) * speed, vy, cos(facing) * speed) * 30.0
    move_and_slide()
    if is_on_floor():
        velocity.y = 0.0
    if mesh:
        mesh.rotation.y = facing
"""

_DIALOG_GD = """extends CanvasLayer
# gcrip text box: shows BMG messages (tags already decoded by gcrip msg);
# {name} -> the player's name, other tags stripped for now. A advances pages.

signal closed

var pages: Array = []
var page := 0
@onready var label: Label = $Panel/Label

func _ready() -> void:
    layer = 40
    process_mode = Node.PROCESS_MODE_ALWAYS
    visible = false

func show_pages(p: Array) -> void:
    pages = p
    page = 0
    visible = true
    _render()

func _render() -> void:
    if page >= pages.size():
        visible = false
        closed.emit()
        return
    label.text = str(pages[page])

func _unhandled_input(event: InputEvent) -> void:
    if not visible:
        return
    if event.is_action_pressed("action_a") or event.is_action_pressed("action_b"):
        page += 1
        _render()
        get_viewport().set_input_as_handled()
"""

_DIALOG_TSCN = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://dialog.gd" id="1"]

[node name="Dialog" type="CanvasLayer"]
script = ExtResource("1")

[node name="Panel" type="Panel" parent="."]
anchors_preset = 7
anchor_left = 0.5
anchor_top = 1.0
anchor_right = 0.5
anchor_bottom = 1.0
offset_left = -460.0
offset_top = -190.0
offset_right = 460.0
offset_bottom = -40.0
grow_horizontal = 2
grow_vertical = 0

[node name="Label" type="Label" parent="Panel"]
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
offset_left = 24.0
offset_top = 14.0
offset_right = -24.0
offset_bottom = -14.0
theme_override_font_sizes/font_size = 26
autowrap_mode = 3
"""

_STAGE_GD = """extends Node3D
# gcrip stage root: puts the game's liquid collision (from the .dzb) on its own physics
# layers so Link can probe for water and hazards without colliding with them, and
# wraps the baked actor meshes into behaviour nodes (pots, items, signs, chests, pigs,
# gulls, NPCs, enemies) using the placement records in stage_data.json.
#   layer 1 = solid ground   layer 2 = water   layer 4 = lava/poison   layer 8 = hittable
#   layer 16 = items

const SCRIPTS := {
    "kotubo": "res://actors/carriable.gd", "ootubo1": "res://actors/carriable.gd",
    "koisi1": "res://actors/carriable.gd", "Ktaru": "res://actors/carriable.gd",
    "item": "res://actors/item.gd", "Kanban": "res://actors/sign.gd",
    "Pig": "res://actors/pig.gd", "Kamome": "res://actors/gull.gd",
    "NpcSo": "res://actors/npc.gd", "Bk": "res://actors/bokoblin.gd",
}
const CHEST_PREFIXES := ["takara", "tkr", "Tkr"]

func _ready() -> void:
    _tag_liquids()
    _wrap_actors()

func _wrap_actors() -> void:
    var level := get_node_or_null("Level")
    var info: Dictionary = Game.stage_data.get(name, {})
    if level == null:
        return
    var n := 0
    for rec in info.get("actors", []):
        var actor: String = rec["actor"]
        var script_path := ""
        if SCRIPTS.has(actor):
            script_path = SCRIPTS[actor]
        else:
            for pre in CHEST_PREFIXES:
                if actor.begins_with(pre):
                    script_path = "res://actors/chest.gd"
        if script_path == "":
            continue
        # the glTF importer sanitises "." in node names to "_"
        var node_name: String = str(rec["node"]).replace(".", "_").replace(":", "_")
        var mesh := level.find_child(node_name, true, false)
        if mesh == null or not (mesh is Node3D):
            continue
        var xf: Transform3D = mesh.global_transform
        var s: Script = load(script_path)
        var node: Node3D = s.new()
        node.name = "A_" + node_name
        add_child(node)
        node.global_transform = Transform3D(Basis(), xf.origin)
        var parent := mesh.get_parent()
        parent.remove_child(mesh)
        node.add_child(mesh)
        mesh.global_transform = xf
        var params: int = int(rec["params"])
        var rot_y: float = float(rec.get("rot_y_deg", 0.0))
        var rot: Array = rec.get("rot", [0, 0, 0])
        if script_path.ends_with("carriable.gd"):
            node.setup(actor, params, mesh)
        elif script_path.ends_with("item.gd"):
            node.setup(params, mesh, true)
        elif script_path.ends_with("sign.gd"):
            node.setup(params, mesh, rot_y)
        elif script_path.ends_with("chest.gd"):
            node.setup(int(rot[2]), mesh, rot_y)
        elif script_path.ends_with("npc.gd"):
            node.setup(actor, params, mesh, rot_y)
        else:
            node.setup(params, mesh, rot_y)
        n += 1
    print("gcrip: ", n, " actors wrapped in ", name)

func _tag_liquids() -> void:
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
action_x={_action(k["E"], _joy_button(JOY_X))}
action_y={_action(k["Q"], _joy_button(JOY_Y))}
target={_action(k["SHIFT"], _joy_button(JOY_RSHOULDER), _joy_axis(AXIS_RT, 1.0))}
pause={_action(k["ESC"], _joy_button(JOY_START))}
calibrate={_action(k["F1"])}

[physics]

common/physics_ticks_per_second=30
common/physics_interpolation=true

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
        stage_data[name] = {"spawns": spawns, "actors": rep.get("actors") or []}
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
    (out_dir / "dialog.gd").write_text(_DIALOG_GD, encoding="utf-8")
    (out_dir / "dialog.tscn").write_text(_DIALOG_TSCN, encoding="utf-8")
    (out_dir / "actors").mkdir(exist_ok=True)
    for fname, src_text in {
        "carriable.gd": _ACTOR_BASE_GD,
        "item.gd": _ACTOR_ITEM_GD,
        "sign.gd": _ACTOR_SIGN_GD,
        "chest.gd": _ACTOR_CHEST_GD,
        "pig.gd": _ACTOR_PIG_GD,
        "gull.gd": _ACTOR_GULL_GD,
        "npc.gd": _ACTOR_NPC_GD,
        "bokoblin.gd": _ACTOR_BOKOBLIN_GD,
    }.items():
        (out_dir / "actors" / fname).write_text(src_text, encoding="utf-8")
    msgs = rip_dir / "text" / "messages.json"
    if msgs.exists():  # gcrip msg output -> in-game text box
        shutil.copyfile(msgs, out_dir / "messages.json")
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
