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
import re
import shutil
import time
from pathlib import Path

from gcrip.export import glb as glbmod

# Godot physical keycodes
_KEYS = {
    "W": 87, "A": 65, "S": 83, "D": 68, "E": 69, "Q": 81, "SPACE": 32, "SHIFT": 4194325,
    "CTRL": 4194326, "ESC": 4194305, "F1": 4194332, "TAB": 4194306, "R": 82, "F": 70,
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
JOY_DPAD_UP, JOY_DPAD_DOWN, JOY_DPAD_LEFT, JOY_DPAD_RIGHT = 11, 12, 13, 14
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
# --- ladders / vine walls (dzb wall code 4-5 / 1; setFrontWallType, procLadder*, procClimb*) ---
const LADDER_OFFSET := 25.0            # Link stands 25 units off the ladder face
const LADDER_RUNG := 37.5              # one rung per ladderltor/rtol cycle (procLadderMove)
const LADDER_RATE_MIN := 0.5           # anim rate at the stick's edge of the dead zone
const LADDER_RATE_MAX := 1.2           # anim rate with the stick fully pushed
const CLIMBWALL_OFFSET := 20.5         # procClimb: held 20.5 units off the vine wall
const CLIMBWALL_SPEED := 1.5           # units/frame at rate 1 (animation-driven in the game)
const CLIMBWALL_SIDE_SPEED := 1.2
const CLIMB_OVER_FRAMES := 24          # ladderupedl / wallholdup climb-over

const S16_TO_RAD := PI / 32768.0

enum State { GROUND, AIR, ROLL, SWIM, LAND, ATTACK, JUMPCUT, JUMPCUT_LAND, DAMAGE, GLIDE, CARRY, GRAB, VJUMP, HANG, CLIMB, LADDER, CLIMBWALL, AIM, ITEM_WAIT, HOOKPULL, SHIP }
var ship: Node3D = null           # the King of Red Lions while riding

# --- X-button items (bow / boomerang / bombs / hookshot specs: projectile-items.md) ---
const X_ITEMS := ["leaf", "bow", "boomerang", "bomb", "hookshot"]
const ITEM_NAMES := {"leaf": "Deku Leaf", "bow": "Bow", "boomerang": "Boomerang", "bomb": "Bombs", "hookshot": "Hookshot"}
const BOW_HOLD_FRAMES := 10            # string can be released after 10 frames (m355E)
const AIM_PITCH_CLAMP := 0x2000 * PI / 32768.0   # Z-target pitch limit
const ARROW_MAX_LIVE := 5
const BOMB_MAX_LIVE := 3
const HOOK_ROOT_OFFSET := Vector3(22.0, 110.0, 0.0)   # left hand + (22,0,0), roughly
var x_item := "leaf"
var arrows := 30
var bombs := 30
var aim_frames := 0
var aim_yaw := 0.0
var aim_pitch := 0.0              # positive = down
var projectile: Node3D = null     # live boomerang / hookshot
var live_arrows: Array = []
var live_bombs: Array = []

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
var wall_hit_pos := Vector3.ZERO      # last tagged-wall probe (ladder / vine / no-hang)
var wall_hit_n := Vector3.ZERO
var ladder_n := Vector3.ZERO          # ladder / vine wall normal (points toward Link)
var climb_over := 0                   # frames left in the climb-over at the top
var climb_over_to := Vector3.ZERO
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
    # restore the persistent state (hearts/rupees/magic/boots survive stage warps)
    hearts = int(Game.save["hearts"])
    hearts_max = int(Game.save["hearts_max"])
    magic = int(Game.save["magic"])
    rupees = int(Game.save["rupees"])
    heavy = bool(Game.save["heavy"])
    x_item = str(Game.save.get("x_item", "leaf"))
    arrows = int(Game.save.get("arrows", 30))
    bombs = int(Game.save.get("bombs", 30))
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
    if water_level > -1.0e8:
        best = Game.sea_height(global_position.x, global_position.z)   # the Great Sea's waves
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

    if Game.selftest:
        _selftest_tick()
    if Game.dialog_open:  # text box up: Link stands still
        _apply(Vector3.ZERO, -1.0)
        play_clip("wait")
        return
    if Input.is_action_just_pressed("action_y") and state in [State.GROUND, State.SWIM]:
        heavy = not heavy  # Iron Boots toggle (procBootsEquip; 19-frame anim skipped)
        _update_hud()
    if Input.is_action_just_pressed("item_next") or Input.is_action_just_pressed("item_prev"):
        var i := X_ITEMS.find(x_item)
        i = (i + (1 if Input.is_action_just_pressed("item_next") else -1) + X_ITEMS.size()) % X_ITEMS.size()
        x_item = X_ITEMS[i]
        _update_hud()
    _update_prompt()

    match state:
        State.CARRY: _carry()
        State.GRAB: _grab()
        State.VJUMP: _vjump()
        State.HANG: _hang()
        State.CLIMB: _climb()
        State.LADDER: _ladder()
        State.CLIMBWALL: _climbwall()
        State.AIM: _aim()
        State.ITEM_WAIT: _item_wait()
        State.HOOKPULL: _hookpull()
        State.SHIP: _ship()
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
    if Input.is_action_just_pressed("action_x") and x_item != "leaf" and _use_item():
        return
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
            var into := -n.normalized()
            var tag := _front_wall(into)
            if tag == "ladder" and _enter_ladder(false):
                return
            if tag == "climb" and _enter_climbwall():
                return
            wall_hold += 1
            # wall code 2 (roofs, hole_kabe): no hang / catch / climb at all
            if tag != "nohang" and wall_hold >= WALL_HOLD_FRAMES and _try_ledge(into):
                return
        else:
            wall_hold = 0
    else:
        wall_hold = 0
    if was_on_floor and not is_on_floor():
        if speed < AUTOJUMP_MIN_SPEED and _try_ladder_down():
            return
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
        if n.length() > 0.1 and stick_world_dir(s).dot(-n.normalized()) > 0.6 and _front_wall(-n.normalized()) != "nohang":
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

# ---------------------------------------------------------------- the boat (d_a_player_ship.inc)

func board(boat: Node3D) -> void:
    ship = boat
    boat.set_rider(self)
    state = State.SHIP
    speed = 0.0
    velocity = Vector3.ZERO
    held = null
    play_clip("wait", 0.2)

func _ship() -> void:
    if ship == null or not is_instance_valid(ship):
        ship = null
        _enter_air(Vector3.ZERO, 0.0, GRAVITY)
        return
    global_position = ship.seat_point()
    facing = ship.yaw
    velocity = Vector3.ZERO
    ship.braking = Input.is_action_pressed("action_a") and ship.speed_f >= 3.0
    if hud_prompt:
        var p := "X: %s" % ("Lower sail" if ship.sail_on else "Raise sail")
        if ship.speed_f < 3.0:
            p += "   A: Get off"
        elif ship.mode == ship.Mode.PADDLE:
            p += "   A: Stop"
        hud_prompt.text = p
    if Input.is_action_just_pressed("action_x"):
        ship.toggle_sail()
    if Input.is_action_just_pressed("action_a") and ship.speed_f < 3.0:
        # get off over the port side: dash 8, hop 8 / 8 with gravity -2.5
        var boat := ship
        ship = null
        boat.clear_rider()
        facing = boat.yaw - PI / 2.0
        global_position = boat.ledge_point(true)
        _enter_air(forward() * 8.0, 8.0, -2.5)
        play_clip("mjmp", 0.1)
        return
    play_clip("wait")

# ---------------------------------------------------------------- X items

var _st_frame := 0
const _ST_SCRIPT := {
    # frame: [action, pressed]  -- bow, boomerang, bombs, hookshot in turn
    10: ["item_next", true], 11: ["item_next", false],
    20: ["action_x", true], 40: ["action_x", false],
    70: ["item_next", true], 71: ["item_next", false],
    80: ["action_x", true], 95: ["action_x", false],
    200: ["item_next", true], 201: ["item_next", false],
    210: ["action_x", true], 211: ["action_x", false],
    235: ["action_a", true], 236: ["action_a", false],
    420: ["item_next", true], 421: ["item_next", false],
    430: ["action_x", true], 445: ["action_x", false],
    # sailing: teleport aboard, raise the sail, hold the stick forward, then stop and get off
    470: ["board", true],
    480: ["action_x", true], 481: ["action_x", false],
    490: ["move_forward", true], 700: ["move_forward", false],
    720: ["action_x", true], 721: ["action_x", false],
    760: ["action_a", true], 860: ["action_a", false],
    900: ["action_a", true], 901: ["action_a", false],
}

func _selftest_tick() -> void:
    _st_frame += 1
    if _st_frame >= 960:
        print("selftest done")
        get_tree().quit()
        return
    if _ST_SCRIPT.has(_st_frame):
        var a: Array = _ST_SCRIPT[_st_frame]
        if a[0] == "board":
            var boat := get_tree().current_scene.get_node_or_null("KingOfRedLions")
            if boat:
                board(boat)
        elif a[1]:
            Input.action_press(a[0])
        else:
            Input.action_release(a[0])
    if _st_frame % 30 == 0:
        var boat_info := ""
        if ship and is_instance_valid(ship):
            boat_info = " ship mode=%d sail=%s speed=%.1f yaw=%.0f tiller=%.0f y=%.1f pitch=%.0f" % [
                ship.mode, str(ship.sail_on), ship.speed_f, rad_to_deg(ship.yaw), ship.tiller,
                ship.global_position.y, ship.pitch]
        print("selftest f%d state=%s item=%s arrows=%d bombs=%d projectile=%s live_arrows=%d live_bombs=%d pos=%s%s" % [
            _st_frame, State.keys()[state], x_item, arrows, bombs,
            str(projectile != null and is_instance_valid(projectile)),
            live_arrows.filter(func(x): return x != null and is_instance_valid(x)).size(),
            live_bombs.filter(func(x): return x != null and is_instance_valid(x)).size(),
            str(global_position.round()), boat_info])

func _use_item() -> bool:
    match x_item:
        "bow", "boomerang", "hookshot":
            if x_item == "bow" and arrows <= 0:
                return false
            if projectile != null and is_instance_valid(projectile):
                if x_item == "boomerang" and projectile.has_method("cancel"):
                    projectile.cancel()   # pressing again recalls it
                return false
            _enter_aim()
            return true
        "bomb":
            if bombs <= 0:
                return false
            live_bombs = live_bombs.filter(func(b): return b != null and is_instance_valid(b))
            if live_bombs.size() >= BOMB_MAX_LIVE:
                return false
            var b := CharacterBody3D.new()
            b.set_script(load("res://items/bomb.gd"))
            get_tree().current_scene.add_child(b)
            b.global_position = carry_point()
            live_bombs.append(b)
            bombs -= 1
            carry(b)
            _update_hud()
            return true
    return false

func _enter_aim() -> void:
    state = State.AIM
    aim_frames = 0
    speed = 0.0
    velocity = Vector3.ZERO
    match x_item:
        "bow": play_clip("bowwait", 4.0 / 30.0)
        "boomerang": play_clip("boomwait", 4.0 / 30.0)
        "hookshot": play_clip("hookshotwait", 4.0 / 30.0)

func _aim_dir() -> Vector3:
    # Z-target: at the target's eyes (pitch clamped 22.5 deg); else where the camera looks
    if lock_target and is_instance_valid(lock_target):
        var to := _target_attn() - hook_root()
        var yaw := atan2(to.x, to.z)
        var pitch := clampf(atan2(-to.y, Vector2(to.x, to.z).length()), -AIM_PITCH_CLAMP, AIM_PITCH_CLAMP)
        aim_yaw = yaw
        aim_pitch = pitch
    else:
        var f := -camera.global_transform.basis.z
        aim_yaw = atan2(f.x, f.z)
        aim_pitch = clampf(atan2(-f.y, Vector2(f.x, f.z).length()), deg_to_rad(-70.0), deg_to_rad(60.0))
    return Vector3(sin(aim_yaw) * cos(aim_pitch), -sin(aim_pitch), cos(aim_yaw) * cos(aim_pitch))

func _aim() -> void:
    aim_frames += 1
    var d := _aim_dir()
    facing = aim_yaw
    _apply(Vector3.ZERO, -1.0)
    if Input.is_action_just_pressed("action_b") or Input.is_action_just_pressed("action_a"):
        _enter_ground()   # cancelItemUpperReadyAnime
        return
    if Input.is_action_pressed("action_x"):
        return
    # released
    match x_item:
        "bow":
            if aim_frames < BOW_HOLD_FRAMES:
                _enter_ground()
                return
            _shoot_arrow(d)
            play_clip("arrowshoot", 2.0 / 30.0, 0.9)
            state = State.ITEM_WAIT
            aim_frames = 0
        "boomerang":
            _throw_boomerang()
            play_clip("boomthrow", 2.0 / 30.0)
            state = State.ITEM_WAIT
            aim_frames = 0
        "hookshot":
            _shoot_hook(d)
            state = State.HOOKPULL   # frozen until the hook comes back or pulls us
            aim_frames = 0

func _item_wait() -> void:
    # the short release / throw animation, then back to normal play
    aim_frames += 1
    _apply(Vector3.ZERO, -1.0)
    if aim_frames >= 10:
        _enter_ground()

func hook_root() -> Vector3:
    return global_position + Basis(Vector3.UP, facing) * HOOK_ROOT_OFFSET

func _shoot_arrow(d: Vector3) -> void:
    live_arrows = live_arrows.filter(func(a): return a != null and is_instance_valid(a))
    if live_arrows.size() >= ARROW_MAX_LIVE:
        var oldest: Node = live_arrows.pop_front()
        if oldest:
            oldest.queue_free()
    var a := Node3D.new()
    a.set_script(load("res://items/arrow.gd"))
    get_tree().current_scene.add_child(a)
    a.launch(hook_root() + d * 30.0, d, self)
    live_arrows.append(a)
    arrows -= 1
    _update_hud()

func add_arrows(n: int) -> void:
    arrows = mini(arrows + n, 99)
    _update_hud()

func _throw_boomerang() -> void:
    var b := Node3D.new()
    b.set_script(load("res://items/boomerang.gd"))
    get_tree().current_scene.add_child(b)
    var locks: Array = []
    if lock_target and is_instance_valid(lock_target):
        locks.append(lock_target)
    b.launch(hook_root(), aim_yaw, aim_pitch, self, locks)
    projectile = b

func catch_boomerang() -> void:
    projectile = null
    if state in [State.GROUND, State.AIR]:
        play_clip("boomcatch", 2.0 / 30.0)

func _shoot_hook(d: Vector3) -> void:
    var h := Node3D.new()
    h.set_script(load("res://items/hookshot.gd"))
    get_tree().current_scene.add_child(h)
    h.launch(self, hook_root(), d)
    projectile = h

func _hookpull() -> void:
    # either waiting in the aim pose (hook flying / returning) or being pulled by it
    if projectile == null or not is_instance_valid(projectile):
        projectile = null
        _enter_air(Vector3.ZERO, 0.0, GRAVITY)
        return
    facing = aim_yaw
    velocity = Vector3.ZERO

func hook_pull(step: Vector3) -> void:
    play_clip("hookshotjmp", 2.0 / 30.0)
    var old := global_position
    global_position += step
    # don't tunnel through walls on the way
    var space := get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(old + Vector3(0, 60.0, 0), global_position + Vector3(0, 60.0, 0), 1)
    if space.intersect_ray(q):
        global_position = old

func hook_done(landed: bool, hook_pos: Vector3, d: Vector3) -> void:
    projectile = null
    if state != State.HOOKPULL:
        return
    if landed:
        var back := Vector3(d.x, 0.0, d.z).normalized()
        global_position = hook_pos - back * 35.0 - Vector3(0, 60.0, 0)
    _enter_air(Vector3.ZERO, 0.0, GRAVITY)

# ---------------------------------------------------------------- ladders / vines

func _front_wall(into: Vector3) -> String:
    # wall code of the tagged collider (layer 32) 25 + radius ahead of Link's waist, "" if none
    var space := get_world_3d().direct_space_state
    var from := global_position + Vector3(0, 60.0, 0)
    var q := PhysicsRayQueryParameters3D.create(from, from + into * 70.0, 32)
    var hit := space.intersect_ray(q)
    wall_hit_n = Vector3.ZERO
    if not hit:
        return ""
    var c = hit.collider
    if c == null or not c.has_meta("wall"):
        return ""
    wall_hit_pos = hit.position
    wall_hit_n = hit.normal
    return str(c.get_meta("wall"))

func _try_ladder_down() -> bool:
    # walking off an edge with a ladder (wall code 4/5) just below it: climb down (ANM_LADDER_DW_ST)
    var s := stick()
    if s.length() < 0.3:
        return false
    var d := stick_world_dir(s)
    var space := get_world_3d().direct_space_state
    var over := global_position + d * 40.0 + Vector3(0, 10.0, 0)
    var q := PhysicsRayQueryParameters3D.create(over, over - Vector3(0, 60.0, 0), 1)
    if space.intersect_ray(q):
        return false  # floor continues
    var probe := global_position + d * 60.0 - Vector3(0, 50.0, 0)
    var q2 := PhysicsRayQueryParameters3D.create(probe, probe - d * 70.0, 32)
    var hit := space.intersect_ray(q2)
    if not hit:
        return false
    var c = hit.collider
    if c == null or not c.has_meta("wall"):
        return false
    var tag := str(c.get_meta("wall"))
    if tag != "ladder" and tag != "ladder_top":
        return false
    wall_hit_pos = hit.position
    wall_hit_n = hit.normal
    return _enter_ladder(true)

func _enter_ladder(descend: bool) -> bool:
    var n := wall_hit_n
    n.y = 0.0
    if n.length() < 0.5:
        return false
    n = n.normalized()
    state = State.LADDER
    velocity = Vector3.ZERO
    speed = 0.0
    wall_hold = 0
    climb_over = 0
    ladder_n = n
    facing = heading_of(-n)
    var p := wall_hit_pos + n * LADDER_OFFSET
    global_position = Vector3(p.x, global_position.y, p.z)
    play_clip("ladderdwst" if descend else "ladderupst", 3.0 / 30.0, 1.0)
    return true

func _enter_climbwall() -> bool:
    var n := wall_hit_n
    n.y = 0.0
    if n.length() < 0.5:
        return false
    n = n.normalized()
    state = State.CLIMBWALL
    velocity = Vector3.ZERO
    speed = 0.0
    wall_hold = 0
    climb_over = 0
    ladder_n = n
    facing = heading_of(-n)
    var p := wall_hit_pos + n * CLIMBWALL_OFFSET
    global_position = Vector3(p.x, global_position.y, p.z)
    play_clip("wall", 3.0 / 30.0, 0.0)
    return true

func _climb_over_tick() -> void:
    # root motion of ladderupedl / wallholdup approximated: ease up and over onto the floor
    climb_over -= 1
    var step := (climb_over_to - global_position) / float(climb_over + 1)
    global_position += step
    if climb_over <= 0:
        global_position = climb_over_to
        _enter_ground()

func _try_climb_over(clip: String) -> bool:
    # is there a floor in front above the top of the wall? then climb over it
    var space := get_world_3d().direct_space_state
    var over := global_position + Vector3(0, 150.0, 0) - ladder_n * 60.0
    var q := PhysicsRayQueryParameters3D.create(over, over - Vector3(0, 170.0, 0), 1)
    var hit := space.intersect_ray(q)
    if not hit:
        return false
    climb_over_to = hit.position + Vector3(0, 1.0, 0)
    climb_over = CLIMB_OVER_FRAMES
    play_clip(clip, 2.0 / 30.0, 1.0)
    return true

func _let_go() -> void:
    global_position += ladder_n * 10.0
    _enter_air(ladder_n * 2.0, 0.0, GRAVITY)
    play_clip("jmpeds", 6.0 / 30.0)

func _wall_tag_at(pos: Vector3, reach: float) -> String:
    var space := get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(pos, pos - ladder_n * reach, 32)
    var hit := space.intersect_ray(q)
    if not hit:
        return ""
    var c = hit.collider
    if c == null or not c.has_meta("wall"):
        return ""
    return str(c.get_meta("wall"))

func _floor_within(dy: float) -> bool:
    var space := get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(global_position + Vector3(0, 10.0, 0), global_position - Vector3(0, dy + 2.0, 0), 1)
    var hit := space.intersect_ray(q)
    return not hit.is_empty()

func _ladder() -> void:
    velocity = Vector3.ZERO
    if climb_over > 0:
        _climb_over_tick()
        return
    if Input.is_action_just_pressed("action_a"):
        _let_go()
        return
    var s := stick()
    var up := 0.0
    if s.length() > 0.2:
        up = stick_world_dir(s).dot(-ladder_n)
    if absf(up) < 0.3:
        play_clip("ladderltor", 3.0 / 30.0, 0.0)
        return
    var rate := lerpf(LADDER_RATE_MIN, LADDER_RATE_MAX, minf(s.length(), 1.0))
    var cycle := 20.0
    if anim and anim.has_animation("ladderltor"):
        cycle = maxf(anim.get_animation("ladderltor").length * 30.0, 1.0)
    var dy := LADDER_RUNG / cycle * rate
    if up > 0.0:
        # the ladder has to continue above Link's head; otherwise climb over the top
        if _wall_tag_at(global_position + Vector3(0, dy + 120.0, 0), 60.0) == "":
            if _try_climb_over("ladderupedl"):
                return
        global_position.y += dy
        play_clip("ladderltor", 2.0 / 30.0, rate)
    else:
        if _floor_within(dy):
            _enter_ground()
            return
        global_position.y -= dy
        play_clip("ladderrtol", 2.0 / 30.0, rate)

func _climbwall() -> void:
    velocity = Vector3.ZERO
    if climb_over > 0:
        _climb_over_tick()
        return
    if Input.is_action_just_pressed("action_a"):
        _let_go()
        return
    var s := stick()
    if s.length() < 0.2:
        play_clip("wall", 3.0 / 30.0, 0.0)
        return
    var d := stick_world_dir(s)
    var up := d.dot(-ladder_n)
    var right := (-ladder_n).cross(Vector3.UP)
    var side := d.dot(right)
    var rate := lerpf(0.8, 1.0, minf(s.length(), 1.0))
    var move := Vector3(0, up * CLIMBWALL_SPEED * rate, 0) + right * side * CLIMBWALL_SIDE_SPEED * rate
    # procClimb continue check: still a code-1 wall 80 units ahead of the new spot, 30 up
    var still: bool = _wall_tag_at(global_position + move + Vector3(0, 90.0, 0), 80.0) == "climb"
    if not still:
        if up > 0.3 and _try_climb_over("wallholdup"):
            return
        if up < -0.3:
            if _floor_within(absf(move.y)):
                _enter_ground()
            else:
                _let_go()
            return
        play_clip("wall", 3.0 / 30.0, 0.0)
        return
    if up < -0.3 and _floor_within(absf(move.y)):
        _enter_ground()
        return
    global_position += move
    if absf(up) >= absf(side):
        play_clip("wallpl" if up > 0.0 else "walldw", 2.0 / 30.0, rate)
    else:
        play_clip("wallwr" if side > 0.0 else "wallwl", 2.0 / 30.0, rate)

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
    Game.save["hearts"] = hearts
    Game.save["hearts_max"] = hearts_max
    Game.save["magic"] = magic
    Game.save["rupees"] = rupees
    Game.save["heavy"] = heavy
    Game.save["x_item"] = x_item
    Game.save["arrows"] = arrows
    Game.save["bombs"] = bombs
    if hud_items:
        var ammo := ""
        if x_item == "bow":
            ammo = " (%d)" % arrows
        elif x_item == "bomb":
            ammo = " (%d)" % bombs
        hud_items.text = "X: %s%s   Y: Iron Boots%s   Tab/D-pad: next item" % [
            ITEM_NAMES.get(x_item, x_item), ammo, " [on]" if heavy else ""]
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
floor_snap_length = 30.0
floor_max_angle = 0.873
safe_margin = 1.0
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
    "bowwait", "arrowshoot", "boomwait", "boomthrow", "boomcatch", "hookshotwait", "hookshotjmp",
    "ladderupst", "ladderltor", "ladderrtol", "ladderupedl", "ladderdwst",
    "wall", "wallpl", "walldw", "wallwl", "wallwr", "wallholdup",
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
var actor_models: Dictionary = {}  # model rel path -> {glb, clips} (animated actors)
var npc_dialogue: Dictionary = {}  # actor name -> {first: [ids], alternatives: {...}}
var dialog: Node = null
var dialog_open := false
var stage_names: Dictionary = {}
var menu: Node = null
var bgm: Dictionary = {}           # data/ww_bgm.json: stages / sea_rooms -> song
var bgm_player: AudioStreamPlayer = null
var bgm_song := ""
var selftest: bool = "--selftest" in OS.get_cmdline_user_args()   # scripted input run
# persistent player state (survives stage warps; the Player node is rebuilt per stage)
var save := {"hearts": 12, "hearts_max": 12, "magic": 16, "rupees": 0, "heavy": false}

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
    var am := FileAccess.open("res://actor_models.json", FileAccess.READ)
    if am:
        var parsed_a = JSON.parse_string(am.get_as_text())
        if parsed_a is Dictionary:
            actor_models = parsed_a
    var nd := FileAccess.open("res://npc_dialogue.json", FileAccess.READ)
    if nd:
        var parsed_n = JSON.parse_string(nd.get_as_text())
        if parsed_n is Dictionary:
            npc_dialogue = parsed_n
    var sn := FileAccess.open("res://stage_names.json", FileAccess.READ)
    if sn:
        var parsed_s = JSON.parse_string(sn.get_as_text())
        if parsed_s is Dictionary:
            stage_names = parsed_s
    var bg := FileAccess.open("res://bgm.json", FileAccess.READ)
    if bg:
        var parsed_b = JSON.parse_string(bg.get_as_text())
        if parsed_b is Dictionary:
            bgm = parsed_b
    bgm_player = AudioStreamPlayer.new()
    bgm_player.bus = "Master"
    bgm_player.volume_db = -6.0
    add_child(bgm_player)

# ---- the Great Sea (d_a_sea.cpp wi_prm_ocean) and the wind (d_kankyo_wether.cpp)

const SEA_WAVES := [
    # amplitude, wavelength, phase (s16), dir x, dir z, period (frames)
    [2.5, 13600.0, 0.0, 0.98, 0.20, 200.0],
    [2.5, 11200.0, 4000.0, 0.20, 0.98, 190.0],
    [2.5, 8800.0, 8000.0, -0.98, 0.20, 210.0],
    [2.5, 6400.0, 12000.0, 0.20, -0.98, 180.0],
]
var sea_scale := 10.0          # room wave_max (0..10); 10 on the open sea, 0 in harbours
var sea_wave_max: Dictionary = {}   # "room" -> wave_max of the current stage (from MULT)
var wind_yaw := 0.0            # Wind's Requiem yaw: 0 = east (new file), 45 deg steps
var wind_power := 0.9

func sea_wave_scale(x: float, z: float) -> float:
    if sea_wave_max.is_empty():
        return 10.0
    var room := str(sea_room_at(Vector3(x, 0.0, z)))
    if sea_wave_max.has(room):
        return float(sea_wave_max[room])
    if sea_wave_max.size() == 1:
        return float(sea_wave_max.values()[0])
    return 10.0

func sea_height(x: float, z: float) -> float:
    var t := float(Engine.get_physics_frames())
    var y := 1.0
    var scale := sea_wave_scale(x, z)
    for w in SEA_WAVES:
        var k: float = 6.28 / w[1]
        var phase: float = 2.0 * PI * (fmod(t, w[5]) / w[5] - 0.5)
        y += w[0] * scale * cos(k * (w[3] * x + w[4] * z) - phase + w[2] * 2.0 * PI / 65536.0)
    return y

func wind_vec() -> Vector3:
    return Vector3(cos(wind_yaw), 0.0, sin(wind_yaw))

func cycle_wind() -> void:
    # stand-in for the Wind's Requiem: 45-degree steps, east first (a new file's wind)
    wind_yaw = wrapf(wind_yaw + PI / 4.0, 0.0, 2.0 * PI)
    var dirs := ["east", "south-east", "south", "south-west", "west", "north-west", "north", "north-east"]
    show_text("The wind now blows %s." % dirs[int(round(wind_yaw / (PI / 4.0))) % 8])

# ---- music (JAIZelBasic::setScene: m_scene_info per stage, m_isle_info per sea room)

func sea_room_at(pos: Vector3) -> int:
    # the Great Sea is a 7 x 7 grid of 100000-unit rooms, room 1 in the north-west
    var col := clampi(int(floor((pos.x + 350000.0) / 100000.0)), 0, 6)
    var row := clampi(int(floor((pos.z + 350000.0) / 100000.0)), 0, 6)
    return 1 + col + row * 7

func song_for(stage: String, room: int) -> String:
    var info: Dictionary = {}
    if stage == "sea" or stage.begins_with("sea_r"):
        var rooms: Dictionary = bgm.get("sea_rooms", {})
        info = rooms.get(str(room), {})
    else:
        var stages: Dictionary = bgm.get("stages", {})
        info = stages.get(stage, {})
    var song = info.get("song")
    return str(song) if song != null else ""

func play_bgm(stage: String, room: int) -> void:
    var song := song_for(stage, room)
    if song == bgm_song:
        return
    bgm_song = song
    if bgm_player == null:
        return
    bgm_player.stop()
    if song == "":
        return
    var path := "res://audio/music/%s.wav" % song.get_basename()
    if not ResourceLoader.exists(path):
        print("gcrip: song not exported: ", song, "  (gcrip music <ripdir> ", song.get_basename(), ")")
        return
    var stream := load(path)
    if stream is AudioStreamWAV:
        var w: AudioStreamWAV = stream
        w.loop_mode = AudioStreamWAV.LOOP_FORWARD
        w.loop_begin = 0
        w.loop_end = int(w.get_length() * w.mix_rate)
    bgm_player.stream = stream
    bgm_player.play()
    print("gcrip: bgm ", song)

# ---- stage select menu

func open_menu() -> void:
    if menu != null or calib != null:
        return
    menu = load("res://menu.tscn").instantiate()
    add_child(menu)
    get_tree().paused = true
    Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func close_menu() -> void:
    if menu == null:
        return
    menu.queue_free()
    menu = null
    get_tree().paused = false
    Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func go_to_stage(stage: String) -> void:
    var info: Dictionary = stage_data.get(stage, {})
    var spawns: Array = info.get("spawns", [])
    var room := 0
    var spawn := 0
    if spawns.size() > 0:
        room = int(spawns[0].get("room", 0))
        spawn = int(spawns[0].get("id", 0))
    last_warp_ms = -100000
    warp(stage, room, spawn)
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
    # first conversation per NPC from the decomp sweep (data/ww_npc_dialogue.json)
    # "first" is a list of talk sessions (successive talks; the NPC remembers it was talked to)
    var info: Dictionary = npc_dialogue.get(actor, {})
    var sessions: Array = info.get("first", [])
    if sessions.is_empty():
        return []
    var talks: Dictionary = save.get("talks", {})
    var n: int = int(talks.get(actor, 0))
    var session = sessions[mini(n, sessions.size() - 1)]
    var ids: Array = session if session is Array else [session]
    talks[actor] = n + 1
    save["talks"] = talks
    var out: Array = []
    for id in ids:
        if messages.has(int(id)):
            out.append(int(id))
    return out

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
    elif event.is_action_pressed("pause") and menu == null and not dialog_open:
        open_menu()
    elif event.is_action_pressed("wind_next") and menu == null and not dialog_open:
        cycle_wind()
        get_viewport().set_input_as_handled()

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
    # opened chests stay open (the game keeps a per-stage tbox bit in the save file)
    var key := "tbox:%s:%s" % [get_tree().current_scene.name, name]
    if Game.save.get("flags", {}).has(key):
        opened = true
    set_meta("save_key", key)
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
    if not Game.save.has("flags"):
        Game.save["flags"] = {}
    Game.save["flags"][get_meta("save_key")] = true
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
var pig_clips := {}

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
        if anim:
            for n in anim.get_animation_list():
                var l := n.to_lower()
                for key in ["wait", "walk", "run", "naku", "jita"]:
                    if key in l and not pig_clips.has(key):
                        pig_clips[key] = n
            for key in ["wait", "walk", "run"]:
                if pig_clips.has(key):
                    anim.get_animation(pig_clips[key]).loop_mode = Animation.LOOP_LINEAR
    if anim:
        var key := "wait"
        if sub == Sub.FLEE or sub == Sub.THROWN:
            key = "run"
        elif sub == Sub.WALK:
            key = "walk"
        elif sub == Sub.CARRY:
            key = "jita" if pig_clips.has("jita") else "wait"
        if pig_clips.has(key) and anim.current_animation != pig_clips[key]:
            anim.play(pig_clips[key], 0.17)
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
    var anim: AnimationPlayer = mesh.find_child("AnimationPlayer", true, false) if mesh else null
    if anim:
        var glide := ""
        for n in anim.get_animation_list():
            if "wait1" in n.to_lower() or glide == "":
                glide = n
        if glide != "":
            anim.get_animation(glide).loop_mode = Animation.LOOP_LINEAR
            anim.play(glide)

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
var home_facing := 0.0
var anim: AnimationPlayer = null
var wait_clip := ""
var talk_clip := ""
var talking := false

func setup(actor: String, _p: int, mesh_node: Node3D, rot_y_deg: float) -> void:
    mesh = mesh_node
    home = global_position
    facing = deg_to_rad(rot_y_deg)
    home_facing = facing
    swimmer = actor == "NpcSo"
    messages = Game.npc_messages(actor)
    anim = mesh.find_child("AnimationPlayer", true, false) if mesh else null
    if anim:
        var names := anim.get_animation_list()
        for n in names:
            var l := n.to_lower()
            if wait_clip == "" and "wait" in l:
                wait_clip = n
            if talk_clip == "" and "talk" in l:
                talk_clip = n
        if wait_clip == "" and names.size() > 0:
            wait_clip = names[0]
        if wait_clip != "":
            anim.get_animation(wait_clip).loop_mode = Animation.LOOP_LINEAR
            anim.play(wait_clip)
        if talk_clip != "":
            anim.get_animation(talk_clip).loop_mode = Animation.LOOP_LINEAR
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
    talking = true
    if anim and talk_clip != "":
        anim.play(talk_clip, 0.2)
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
    else:
        # look toward Link when he is close (the game turns the head; we turn the body slowly)
        var link := Game.player()
        var want := home_facing
        if link:
            var to_link := link.global_position - global_position
            to_link.y = 0.0
            if to_link.length() < 300.0:
                want = atan2(to_link.x, to_link.z)
        var rem := wrapf(want - facing, -PI, PI)
        facing += clampf(rem, -0.05, 0.05)
    if talking and not Game.dialog_open:
        talking = false
        if anim and wait_clip != "":
            anim.play(wait_clip, 0.3)
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

var clips := {}

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
    anim = mesh.find_child("AnimationPlayer", true, false) if mesh else null
    if anim:
        for n in anim.get_animation_list():
            var l := n.to_lower()
            for key in ["wait", "walk", "run", "attack", "damage", "dead", "otisou", "hakken"]:
                if key in l and not clips.has(key):
                    clips[key] = n
        for key in ["wait", "walk", "run"]:
            if clips.has(key):
                anim.get_animation(clips[key]).loop_mode = Animation.LOOP_LINEAR
        _play("wait")

func _play(key: String, blend := 0.2) -> void:
    if anim and clips.has(key) and anim.current_animation != clips[key]:
        anim.play(clips[key], blend)

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
        _play("dead" if clips.has("dead") else "otisou", 0.1)
        Game.burst(global_position + Vector3(0, 50, 0), Color(0.5, 0.2, 0.6))
        return
    act = Act.DAMAGE
    timer = 12
    speed = -8.0
    _play("damage", 0.05)

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
            _play("wait")
            if link and dist < NOTICE and Game.line_of_sight(global_position + Vector3(0, 80, 0), link.global_position + Vector3(0, 80, 0)):
                act = Act.FIGHT_RUN
                _play("hakken" if clips.has("hakken") else "run", 0.1)
        Act.FIGHT_RUN:
            _turn_to(atan2(to_link.x, to_link.z))
            speed = RUN
            _play("run")
            if dist < ATTACK_RANGE:
                act = Act.ATTACK
                timer = 30
                hit_done = false
                speed = 0.0
                _play("attack", 0.1)
                if anim and clips.has("attack"):
                    anim.speed_scale = 1.2
            elif dist > NOTICE * 1.5:
                act = Act.STAND
        Act.ATTACK:
            timer -= 1
            if timer == 1 and anim:
                anim.speed_scale = 1.0
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

_MENU_GD = """extends CanvasLayer
# gcrip stage select (Start / Esc): every exported stage with its place name; A/Enter warps.

@onready var list: ItemList = $Panel/VBox/List
@onready var title: Label = $Panel/VBox/Title
var keys: Array = []

func _ready() -> void:
    layer = 45
    process_mode = Node.PROCESS_MODE_ALWAYS
    var names: Dictionary = Game.stage_names
    keys = Game.stage_data.keys()
    keys.sort_custom(func(a, b): return str(names.get(a, a)).to_lower() < str(names.get(b, b)).to_lower())
    for k in keys:
        var n: String = str(names.get(k, ""))
        list.add_item((n + "   (" + k + ")") if n != "" else k)
    title.text = "Where to?   %d stages   -   Enter / A: go   Esc / Start: back" % keys.size()
    if list.item_count > 0:
        list.select(0)
        list.grab_focus()

func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("pause") or event.is_action_pressed("ui_cancel"):
        Game.close_menu()
        get_viewport().set_input_as_handled()
    elif event.is_action_pressed("action_a") or event.is_action_pressed("ui_accept"):
        var sel := list.get_selected_items()
        if sel.size() > 0:
            Game.close_menu()
            Game.go_to_stage(str(keys[sel[0]]))
        get_viewport().set_input_as_handled()
    elif event.is_action_pressed("move_back") or event.is_action_pressed("ui_down"):
        _move(1)
        get_viewport().set_input_as_handled()
    elif event.is_action_pressed("move_forward") or event.is_action_pressed("ui_up"):
        _move(-1)
        get_viewport().set_input_as_handled()

func _move(d: int) -> void:
    var sel := list.get_selected_items()
    var i: int = (sel[0] if sel.size() > 0 else 0) + d
    i = clampi(i, 0, list.item_count - 1)
    list.select(i)
    list.ensure_current_is_visible()
"""

_MENU_TSCN = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://menu.gd" id="1"]

[node name="Menu" type="CanvasLayer"]
script = ExtResource("1")

[node name="Panel" type="Panel" parent="."]
anchors_preset = 8
anchor_left = 0.5
anchor_top = 0.5
anchor_right = 0.5
anchor_bottom = 0.5
offset_left = -340.0
offset_top = -300.0
offset_right = 340.0
offset_bottom = 300.0
grow_horizontal = 2
grow_vertical = 2

[node name="VBox" type="VBoxContainer" parent="Panel"]
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
offset_left = 16.0
offset_top = 12.0
offset_right = -16.0
offset_bottom = -12.0

[node name="Title" type="Label" parent="Panel/VBox"]
layout_mode = 2
theme_override_font_sizes/font_size = 20

[node name="List" type="ItemList" parent="Panel/VBox"]
layout_mode = 2
size_flags_vertical = 3
theme_override_font_sizes/font_size = 18
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
    # villagers and friends: generic talkable NPC with their own rig + wait/talk clips
    "Aj1": "res://actors/npc.gd", "Ls1": "res://actors/npc.gd", "Ob1": "res://actors/npc.gd",
    "Ko1": "res://actors/npc.gd", "Ko2": "res://actors/npc.gd", "Yw1": "res://actors/npc.gd",
    "Ym1": "res://actors/npc.gd", "Ym2": "res://actors/npc.gd", "Bm1": "res://actors/npc.gd",
    "Ji1": "res://actors/npc.gd", "Ba1": "res://actors/npc.gd", "Kg1": "res://actors/npc.gd",
    "Kg2": "res://actors/npc.gd", "Dk": "res://actors/npc.gd", "Zl1": "res://actors/npc.gd",
    "Ac1": "res://actors/npc.gd", "Cb1": "res://actors/npc.gd", "Hi1": "res://actors/npc.gd",
    "Md1": "res://actors/npc.gd", "De1": "res://actors/npc.gd", "Co1": "res://actors/npc.gd",
    "Zk1": "res://actors/npc.gd", "Tc": "res://actors/npc.gd", "Bs1": "res://actors/npc.gd",
    "Bs2": "res://actors/npc.gd", "Kp1": "res://actors/npc.gd", "Mt": "res://actors/npc.gd",
    "Ds1": "res://actors/npc.gd", "Sa1": "res://actors/npc.gd", "Gk1": "res://actors/npc.gd",
    "Um1": "res://actors/npc.gd", "Uo1": "res://actors/npc.gd", "Uo2": "res://actors/npc.gd",
    "Uo3": "res://actors/npc.gd", "Ub1": "res://actors/npc.gd", "Ub2": "res://actors/npc.gd",
    "Ub3": "res://actors/npc.gd", "Ub4": "res://actors/npc.gd", "Bj1": "res://actors/npc.gd",
    "Jb1": "res://actors/npc.gd", "Mk": "res://actors/npc.gd", "Hr": "res://actors/npc.gd",
    "Aj2": "res://actors/npc.gd", "Bmcon1": "res://actors/npc.gd", "Bms1": "res://actors/npc.gd",
}
const CHEST_PREFIXES := ["takara", "tkr", "Tkr"]

var _bgm_tick := 0

func _ready() -> void:
    _tag_liquids()
    _wrap_actors()
    _spawn_ships()
    _start_bgm.call_deferred()

func _spawn_ships() -> void:
    # one King of Red Lions: the SHIP point of Outset (room 44) when present, else the first
    var info: Dictionary = Game.stage_data.get(name, {})
    var ships: Array = info.get("ships", [])
    if ships.is_empty():
        return
    var pick: Dictionary = ships[0]
    for sp in ships:
        if int(sp.get("room", -1)) == 44 and int(sp.get("id", 0)) == 0:
            pick = sp
            break
    var ship := CharacterBody3D.new()
    ship.set_script(load("res://items/ship.gd"))
    ship.name = "KingOfRedLions"
    add_child(ship)
    ship.global_position = Vector3(pick["pos"][0], pick["pos"][1], pick["pos"][2])
    ship.setup(float(pick.get("rot_y_deg", 0.0)))
    print("gcrip: King of Red Lions moored at ", ship.global_position.round())

func _room_hint() -> int:
    var i := name.rfind("_r")
    if i >= 0 and name.substr(i + 2).is_valid_int():
        return int(name.substr(i + 2))
    if name == "sea":
        var p := get_node_or_null("Player")
        if p:
            return Game.sea_room_at((p as Node3D).global_position)
    return 0

func _start_bgm() -> void:
    var info: Dictionary = Game.stage_data.get(name, {})
    Game.sea_wave_max = info.get("wave_max", {})
    Game.play_bgm(name.split("_r")[0], _room_hint())

func _process(_delta: float) -> void:
    if name != "sea":
        return
    _bgm_tick += 1
    if _bgm_tick % 60 == 0:  # crossing into another island's room changes the theme
        Game.play_bgm("sea", _room_hint())

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
        # animated actors: swap the baked mesh for the rigged model with its clips
        var am: Dictionary = Game.actor_models.get(str(rec.get("model", "")), {})
        if not am.is_empty() and ResourceLoader.exists(str(am["glb"])):
            var scene: PackedScene = load(str(am["glb"]))
            var rig: Node3D = scene.instantiate()
            node.add_child(rig)
            rig.global_transform = xf
            mesh.visible = false
            mesh = rig
            node.set_meta("clips", am.get("clips", []))
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
        elif n.begins_with("wall_"):
            # wall_<tag>_... : ladder / ladder_top / climb / nohang (dzb wall codes 4 / 5 / 1 / 2)
            var tag := n.substr(5)
            for t in ["ladder_top", "ladder", "climb", "nohang", "hookshot"]:
                if tag.begins_with(t):
                    tag = t
                    break
            body.collision_layer = 32
            body.collision_mask = 0
            body.set_meta("wall", tag)
"""

_ARROW_GD = 'extends Node3D\n# gcrip: Hero\'s Bow arrow (d_a_arrow.cpp). 200 units/frame dead straight (gravity only\n# after 25000 units), capsule r5 over 1.25 steps, sticks 50 back from the hit point with a\n# 40-frame wobble, then a 300-frame pickup (+1 arrow) blinking its last 60 frames.\n\nconst SPEED := 200.0\nconst STICK_BACK := 50.0\nconst WOBBLE_FRAMES := 40\nconst WOBBLE_AMP := 0x400 * PI / 32768.0\nconst WOBBLE_FREQ := 0x52FB * PI / 32768.0\nconst PICKUP_LIFE := 300\nconst PICKUP_BLINK := 60\nconst PICKUP_R := 25.0\nconst MAX_RANGE := 25000.0\nconst ATP := 2\n\nenum State { FLYING, STUCK, DONE }\nvar state: int = State.FLYING\nvar vel := Vector3.ZERO\nvar start := Vector3.ZERO\nvar base: Basis = Basis.IDENTITY\nvar wobble := 0\nvar life := 0\nvar player: Node3D = null\nvar model: Node3D = null\n\nfunc launch(pos: Vector3, dir: Vector3, link: Node3D) -> void:\n    player = link\n    start = pos\n    global_position = pos\n    vel = dir.normalized() * SPEED\n    var scene := load("res://items/arrow.glb") if ResourceLoader.exists("res://items/arrow.glb") else null\n    if scene:\n        model = scene.instantiate()\n        add_child(model)\n    _face(vel)\n\nfunc _face(d: Vector3) -> void:\n    if d.length() > 0.001:\n        look_at(global_position - d, Vector3.UP)  # the model points down +Z\n\nfunc _physics_process(_delta: float) -> void:\n    match state:\n        State.FLYING: _fly()\n        State.STUCK: _stuck()\n\nfunc _fly() -> void:\n    var old := global_position\n    var next := old + vel\n    var space := get_world_3d().direct_space_state\n    # actors (hittable layer 8) along the step + a quarter step ahead\n    var qa := PhysicsRayQueryParameters3D.create(old, next + vel * 0.25, 8)\n    qa.collide_with_areas = true\n    var ha := space.intersect_ray(qa)\n    if ha:\n        var c = ha.collider\n        if c and c.has_method("take_hit"):\n            c.take_hit(ATP, old)\n        state = State.DONE\n        queue_free()\n        return\n    var qb := PhysicsRayQueryParameters3D.create(old, next + vel * 0.25, 1)\n    var hb := space.intersect_ray(qb)\n    if hb:\n        global_position = hb.position - vel.normalized() * STICK_BACK\n        _face(vel)\n        base = global_transform.basis\n        state = State.STUCK\n        wobble = WOBBLE_FRAMES\n        life = PICKUP_LIFE\n        return\n    global_position = next\n    if global_position.distance_to(start) > MAX_RANGE:\n        queue_free()\n\nfunc _stuck() -> void:\n    if wobble > 0:\n        wobble -= 1\n        var t := float(wobble)\n        var ang := sin(t * WOBBLE_FREQ) * WOBBLE_AMP * pow(t / WOBBLE_FRAMES, 2.0)\n        global_transform.basis = base.rotated(base.x, ang)\n    life -= 1\n    if life <= 0:\n        queue_free()\n        return\n    if life < PICKUP_BLINK and model:\n        model.visible = (life % 2) == 0\n    if player and is_instance_valid(player):\n        var feet: Vector3 = player.global_position\n        var d := global_position.distance_to(feet + Vector3(0, 50.0, 0))\n        if d < PICKUP_R + 40.0 and player.has_method("add_arrows"):\n            player.add_arrows(1)\n            queue_free()\n'

_BOOMERANG_GD = 'extends Node3D\n# gcrip: Boomerang (d_a_boomerang.cpp). 60 units/frame, steers toward its target with a\n# turn rate that tightens near it (wide arc, snaps at the end), sweeps through up to five\n# locked targets, returns to Link\'s catch point; walls on the way out reverse it.\n\nconst SPEED := 60.0\nconst FLY_MAX := 2500.0\nconst FREE_YAW_OFFSET := 0x3000 * PI / 32768.0\nconst JUST_HIT_OFFSET := 0x3000 * PI / 32768.0\nconst TURN_THIRD := 0x4000 * PI / 32768.0\nconst HIT_R := 30.0\nconst ATP := 1\nconst SPIN := 0x1F00 * PI / 32768.0\nconst CATCH_OFFSET := Vector3(12.5, 47.5, 36.6)\nconst S16 := PI / 32768.0\n\nenum State { OUT, RETURN }\nvar state: int = State.OUT\nvar player: Node3D = null\nvar targets: Array = []\nvar cur := 0\nvar target_pos := Vector3.ZERO\nvar yaw := 0.0\nvar pitch := 0.0   # positive = down (game convention)\nvar free_out := true\nvar third_person := false\nvar just_hit := false\nvar hit_once: Dictionary = {}\nvar model: Node3D = null\nvar spin := 0.0\n\nstatic func fwd(y: float, p: float) -> Vector3:\n    return Vector3(sin(y) * cos(p), -sin(p), cos(y) * cos(p))\n\nfunc launch(pos: Vector3, aim_yaw: float, aim_pitch: float, link: Node3D, locks: Array) -> void:\n    player = link\n    global_position = pos\n    targets = locks.filter(func(t): return t != null and is_instance_valid(t))\n    free_out = targets.is_empty()\n    third_person = not free_out\n    if free_out:\n        target_pos = pos + fwd(aim_yaw, aim_pitch) * FLY_MAX\n        yaw = aim_yaw + FREE_YAW_OFFSET\n        pitch = aim_pitch\n    else:\n        _aim_at_target()\n        var to := target_pos - pos\n        yaw = atan2(to.x, to.z)\n        pitch = atan2(-to.y, Vector2(to.x, to.z).length())\n    var scene := load("res://items/boomerang.glb") if ResourceLoader.exists("res://items/boomerang.glb") else null\n    if scene:\n        model = scene.instantiate()\n        add_child(model)\n\nfunc _aim_at_target() -> void:\n    var t: Node3D = targets[cur]\n    if t and is_instance_valid(t):\n        target_pos = t.global_position + Vector3(0, 60.0, 0)\n\nfunc _catch_pos() -> Vector3:\n    if player == null or not is_instance_valid(player):\n        return global_position\n    var f: float = player.get("facing")\n    var b := Basis(Vector3.UP, f)\n    return player.global_position + b * CATCH_OFFSET\n\nfunc cancel() -> void:\n    if state == State.OUT:\n        state = State.RETURN\n\nfunc _physics_process(_delta: float) -> void:\n    spin -= SPIN\n    if model:\n        model.rotation = Vector3(0, spin, 0x2000 * S16)\n    if state == State.RETURN:\n        target_pos = _catch_pos()\n    elif not free_out and cur < targets.size():\n        _aim_at_target()\n    var to := target_pos - global_position\n    var dist := to.length()\n    var want_yaw := atan2(to.x, to.z)\n    var want_pitch := atan2(-to.y, Vector2(to.x, to.z).length())\n    var max_turn: float\n    if third_person and state == State.OUT:\n        max_turn = TURN_THIRD\n    else:\n        var a := clampf(20.0 - dist * 2.0 / SPEED, 0.0, 18.0)\n        max_turn = (a * 0x100 + 0x400) * S16\n    if just_hit:\n        # after a hit, swing wide of the next target before homing again\n        yaw += JUST_HIT_OFFSET * (1.0 if randf() < 0.5 else -1.0)\n        just_hit = false\n    else:\n        yaw += clampf(wrapf(want_yaw - yaw, -PI, PI), -max_turn, max_turn)\n    pitch = want_pitch\n    var old := global_position\n    var next := old + fwd(yaw, pitch) * SPEED\n    var space := get_world_3d().direct_space_state\n    # things it hits on the way (capsule r30 approximated by a ray through the sweep)\n    var qa := PhysicsRayQueryParameters3D.create(old, next, 8 | 16)\n    qa.collide_with_areas = true\n    var ha := space.intersect_ray(qa)\n    if ha:\n        var c = ha.collider\n        if c and not hit_once.has(c.get_instance_id()):\n            hit_once[c.get_instance_id()] = true\n            if c.has_method("take_hit"):\n                c.take_hit(ATP, old)\n            if state == State.OUT and not free_out and cur < targets.size() and c == targets[cur]:\n                _next_target()\n    if state == State.OUT:\n        var qb := PhysicsRayQueryParameters3D.create(old, next, 1)\n        var hb := space.intersect_ray(qb)\n        if hb:\n            global_position = hb.position\n            yaw += PI\n            state = State.RETURN\n            return\n        if dist < SPEED:\n            if free_out:\n                state = State.RETURN\n            else:\n                _next_target()\n    global_position = next\n    if state == State.RETURN and dist < 2.0 * SPEED:\n        if player and is_instance_valid(player) and player.has_method("catch_boomerang"):\n            player.catch_boomerang()\n        queue_free()\n\nfunc _next_target() -> void:\n    just_hit = true\n    cur += 1\n    if cur >= targets.size():\n        state = State.RETURN\n'

_BOMB_GD = 'extends CharacterBody3D\n# gcrip: Link\'s bomb (d_a_bomb3.inc). Carried with the grab system, thrown 19 / 34 at\n# GRABTHROW frame 2, gravity -2.9, bounces -0.6 (stops below 19.5), wall 0.8, 150-frame\n# fuse, blast r200 Atp 4 (one frame), hurt sphere r30. Explodes when hit by anything.\n\nconst GRAVITY := -2.9\nconst MAX_FALL := -100.0\nconst FUSE := 150\nconst THROW_XZ := 19.0\nconst THROW_Y := 34.0\nconst BOUNCE := -0.6\nconst BOUNCE_MIN_VY := 19.5\nconst BOUNCE_VY_CAP := 13.0\nconst LAND_FRICTION := 0.9\nconst WALL_FRICTION := 0.8\nconst HURT_R := 30.0\nconst EXPLODE_R := 200.0\nconst ATP := 4\n\nenum Mode { WAIT, CARRY, DROP }\nvar mode: int = Mode.WAIT\nvar kind := "bomb"\nvar carrier: Node3D = null\nvar fuse := FUSE\nvar h_vel := Vector3.ZERO\nvar vy := 0.0\nvar model: Node3D = null\nvar lit := true\n\nfunc _ready() -> void:\n    collision_layer = 8\n    collision_mask = 1\n    var shape := CollisionShape3D.new()\n    var sph := SphereShape3D.new()\n    sph.radius = HURT_R\n    shape.shape = sph\n    shape.position.y = HURT_R\n    add_child(shape)\n    add_to_group("interact")\n    var scene := load("res://items/bomb.glb") if ResourceLoader.exists("res://items/bomb.glb") else null\n    if scene:\n        model = scene.instantiate()\n        add_child(model)\n        var anim := model.find_child("AnimationPlayer", true, false)\n        if anim and anim.get_animation_list().size() > 0:\n            anim.play(anim.get_animation_list()[0])\n\n# --- Link-side interaction API (same as the pots) ---\nfunc interact_prompt(link: Node3D) -> String:\n    if mode != Mode.WAIT:\n        return ""\n    return "Grab" if link.global_position.distance_to(global_position) < 80.0 else ""\n\nfunc interact(link: Node3D) -> void:\n    if mode == Mode.WAIT:\n        link.call("carry", self)\n\nfunc picked_up(by: Node3D) -> void:\n    mode = Mode.CARRY\n    carrier = by\n    collision_layer = 0\n    collision_mask = 0\n\nfunc thrown(direction: Vector3, _link_speed: float) -> void:\n    mode = Mode.DROP\n    carrier = null\n    collision_layer = 8\n    collision_mask = 1\n    var d := direction.normalized()\n    h_vel = Vector3(d.x, 0.0, d.z) * THROW_XZ\n    vy = THROW_Y\n\nfunc take_hit(_damage: int, _from: Vector3) -> void:\n    explode()\n\nfunc _physics_process(_delta: float) -> void:\n    if lit:\n        fuse -= 1\n        if model and fuse < 45:\n            model.visible = (fuse / 3) % 2 == 0  # flashing before it blows\n        if fuse <= 0:\n            explode()\n            return\n    match mode:\n        Mode.CARRY:\n            if carrier and is_instance_valid(carrier) and carrier.has_method("carry_point"):\n                global_position = carrier.carry_point()\n        Mode.DROP, Mode.WAIT:\n            vy = maxf(vy + GRAVITY, MAX_FALL)\n            velocity = (h_vel + Vector3(0, vy, 0)) * 30.0\n            move_and_slide()\n            if is_on_wall():\n                var n := get_wall_normal()\n                n.y = 0.0\n                if n.length() > 0.01:\n                    h_vel = h_vel.bounce(n.normalized()) * WALL_FRICTION\n            if is_on_floor():\n                if vy < 0.0:\n                    var b := -BOUNCE * vy\n                    if b < BOUNCE_MIN_VY:\n                        vy = 0.0\n                        h_vel *= 0.5\n                    else:\n                        vy = minf(b, BOUNCE_VY_CAP)\n                        h_vel *= LAND_FRICTION\n                if vy == 0.0:\n                    h_vel = h_vel.move_toward(Vector3.ZERO, 0.5)\n            if Game.has_method("ground_height") and global_position.y < -20000.0:\n                queue_free()\n\nfunc explode() -> void:\n    if mode == Mode.CARRY and carrier and is_instance_valid(carrier):\n        carrier.set("held", null)\n    var centre := global_position + Vector3(0, HURT_R, 0)\n    var space := get_world_3d().direct_space_state\n    var q := PhysicsShapeQueryParameters3D.new()\n    var sph := SphereShape3D.new()\n    sph.radius = EXPLODE_R\n    q.shape = sph\n    q.transform = Transform3D(Basis.IDENTITY, centre)\n    q.collision_mask = 8 | 16\n    q.collide_with_areas = true\n    q.exclude = [get_rid()]\n    for hit in space.intersect_shape(q, 32):\n        var c = hit.collider\n        if c and c != self and c.has_method("take_hit"):\n            c.take_hit(ATP, centre)\n    var link := Game.player()\n    if link and link.global_position.distance_to(centre) < EXPLODE_R + 40.0 and link.has_method("take_damage"):\n        link.take_damage(ATP, centre, true)\n    if Game.has_method("burst"):\n        Game.burst(centre, Color(1.0, 0.8, 0.4))\n    var light := OmniLight3D.new()\n    light.light_color = Color(1.0, 1.0, 0.8)\n    light.light_energy = 6.0\n    light.omni_range = 600.0\n    light.position = centre\n    get_tree().current_scene.add_child(light)\n    get_tree().create_timer(0.15).timeout.connect(light.queue_free)\n    queue_free()\n'

_HOOKSHOT_GD = 'extends Node3D\n# gcrip: Hookshot (d_a_hookshot.cpp). 105 units/frame out over 1500, capsule r5; a\n# hookshot-stick polygon (dzb pass flag 0x10) or an anchor pulls Link in at 63/frame,\n# anything else sends it back at 63/frame. Link is frozen in the aim pose while it\'s out.\n\nconst RANGE := 1500.0\nconst SHOT_SPEED := 105.0\nconst RETRACT_SPEED := 63.0\nconst PULL_SPEED := 63.0\nconst LINK_LEN := 7.0\nconst STOP_LINKS := 9\nconst LAND_BACK := 35.0\nconst ATP := 1\n\nenum State { SHOT, RETURN, PULL }\nvar state: int = State.SHOT\nvar player: Node3D = null\nvar dir := Vector3.FORWARD\nvar root := Vector3.ZERO\nvar chain: MeshInstance3D = null\nvar tip: Node3D = null\n\nfunc launch(link: Node3D, from: Vector3, aim: Vector3) -> void:\n    player = link\n    root = from\n    dir = aim.normalized()\n    global_position = from\n    chain = MeshInstance3D.new()\n    var cyl := CylinderMesh.new()\n    cyl.top_radius = 2.5\n    cyl.bottom_radius = 2.5\n    cyl.height = 1.0\n    chain.mesh = cyl\n    var mat := StandardMaterial3D.new()\n    mat.albedo_color = Color(0.45, 0.45, 0.5)\n    chain.material_override = mat\n    chain.top_level = true\n    add_child(chain)\n    var scene := load("res://items/hookshot.glb") if ResourceLoader.exists("res://items/hookshot.glb") else null\n    if scene:\n        tip = scene.instantiate()\n        add_child(tip)\n        tip.scale = Vector3.ONE * 0.6\n\nfunc _root_now() -> Vector3:\n    if player and is_instance_valid(player) and player.has_method("hook_root"):\n        return player.hook_root()\n    return root\n\nfunc _physics_process(_delta: float) -> void:\n    var r := _root_now()\n    match state:\n        State.SHOT:\n            var old := global_position\n            var next := old + dir * SHOT_SPEED\n            var space := get_world_3d().direct_space_state\n            var q := PhysicsRayQueryParameters3D.create(old, next, 1 | 8 | 32)\n            q.collide_with_areas = true\n            var hit := space.intersect_ray(q)\n            if hit:\n                var c = hit.collider\n                global_position = hit.position\n                var sticks: bool = c != null and ((c.has_meta("wall") and str(c.get_meta("wall")) == "hookshot") or c.is_in_group("hook_anchor"))\n                if sticks:\n                    state = State.PULL\n                else:\n                    if c and c.has_method("take_hit"):\n                        c.take_hit(ATP, old)\n                    state = State.RETURN\n            else:\n                global_position = next\n                if global_position.distance_to(r) >= RANGE:\n                    state = State.RETURN\n        State.RETURN:\n            var to := r - global_position\n            if to.length() <= RETRACT_SPEED:\n                _finish(false)\n                return\n            global_position += to.normalized() * RETRACT_SPEED\n        State.PULL:\n            if player == null or not is_instance_valid(player):\n                queue_free()\n                return\n            var to := global_position - r\n            if to.length() <= PULL_SPEED:\n                _finish(true)\n                return\n            player.hook_pull(to.normalized() * PULL_SPEED)\n    _draw_chain(_root_now())\n\nfunc _draw_chain(r: Vector3) -> void:\n    if chain == null:\n        return\n    var a := r\n    var b := global_position\n    var d := b - a\n    var l := d.length()\n    if l < 1.0:\n        chain.visible = false\n        return\n    chain.visible = true\n    chain.global_position = (a + b) * 0.5\n    chain.look_at(b, Vector3.UP if absf(d.normalized().y) < 0.99 else Vector3.FORWARD)\n    chain.rotate_object_local(Vector3.RIGHT, PI / 2.0)\n    chain.scale = Vector3(1.0, l, 1.0)\n\nfunc _finish(landed: bool) -> void:\n    if player and is_instance_valid(player) and player.has_method("hook_done"):\n        player.hook_done(landed, global_position, dir)\n    queue_free()\n'

_SHIP_GD = 'extends CharacterBody3D\n# gcrip: the King of Red Lions (d_a_ship.cpp). Tiller / yaw, wind-driven sail speed,\n# paddling, buoyancy spring on the wave heightfield, four-probe wave tilt, hull circles.\n# Units per frame at 30 Hz; s16 angles kept as floats where the decomp uses them.\n\nconst S16 := PI / 32768.0\nconst TILLER_MAX := 0x2000\nconst TILLER_SPEED := 700.0\nconst WIND_INC_SPEED := 55.0\nconst PADDLE_SPEED := 10.0\nconst BURST_CAP := 80.0\nconst HULL_R := 250.0\nconst SEAT := Vector3(0.0, 15.0, -35.0)\nconst LEDGE_L := Vector3(57.0, 35.0, -35.0)\nconst LEDGE_R := Vector3(-57.0, 35.0, -35.0)\n\nenum Mode { WAIT, PADDLE, STEER }\nvar mode: int = Mode.WAIT\nvar rider: Node3D = null\nvar yaw := 0.0              # radians, atan2(x, z) convention like Link\'s facing\nvar tiller := 0.0           # s16 units\nvar speed_f := 0.0\nvar burst_target := 1.0e9\nvar sail_on := false\nvar braking := false\nvar vy := 0.0\nvar bob := 0.0\nvar pitch := 0.0            # s16 units (positive = nose down)\nvar roll := 0.0\nvar pitch_vel := 0.0\nvar roll_vel := 0.0\nvar noise_a := 0.0\nvar noise_b := 0.0\nvar heel := 0.0\nvar heel_vel := 0.0\nvar prev_yaw := 0.0\nvar landing := 0\nvar model: Node3D = null\n\nfunc setup(rot_y_deg: float) -> void:\n    yaw = deg_to_rad(rot_y_deg)\n    prev_yaw = yaw\n    collision_layer = 0\n    collision_mask = 1\n    var shape := CollisionShape3D.new()\n    var cyl := CylinderShape3D.new()\n    cyl.radius = HULL_R\n    cyl.height = 150.0\n    shape.shape = cyl\n    shape.position.y = 150.0   # wall circles only: keep the hull clear of the seabed\n    add_child(shape)\n    motion_mode = CharacterBody3D.MOTION_MODE_FLOATING\n    add_to_group("interact")\n    model = Node3D.new()\n    add_child(model)\n    for part in ["ship", "ship_head"]:\n        var path := "res://items/%s.glb" % part\n        if ResourceLoader.exists(path):\n            model.add_child(load(path).instantiate())\n    global_position.y = Game.sea_height(global_position.x, global_position.z)\n    _update_transform()\n\nfunc forward() -> Vector3:\n    return Vector3(sin(yaw), 0.0, cos(yaw))\n\nfunc right() -> Vector3:\n    return forward().cross(Vector3.UP)\n\n# --- Link-side interaction API ---\nfunc interact_prompt(link: Node3D) -> String:\n    if rider != null or mode != Mode.WAIT:\n        return ""\n    return "Ride" if link.global_position.distance_to(global_position) < 420.0 else ""\n\nfunc interact(link: Node3D) -> void:\n    if rider == null and link.has_method("board"):\n        link.board(self)\n\nfunc set_rider(link: Node3D) -> void:\n    rider = link\n    mode = Mode.PADDLE\n    sail_on = false\n\nfunc clear_rider() -> void:\n    rider = null\n    mode = Mode.WAIT\n    sail_on = false\n\nfunc toggle_sail() -> void:\n    if sail_on:\n        sail_on = false\n        mode = Mode.PADDLE\n        return\n    sail_on = true\n    mode = Mode.STEER\n    # raising the sail: instant burst to 2x the wind speed (cap 80), decays to the wind speed\n    var ws := _wind_speed()\n    speed_f = maxf(speed_f, minf(ws * 2.0, BURST_CAP))\n    burst_target = ws\n\nfunc seat_point() -> Vector3:\n    return global_transform * SEAT\n\nfunc ledge_point(left: bool) -> Vector3:\n    return global_transform * (LEDGE_L if left else LEDGE_R)\n\n# --- cLib helpers ---\nstatic func add_calc(v: float, target: float, scale: float, max_step: float, min_step: float) -> float:\n    var step := (target - v) * scale\n    step = clampf(step, -max_step, max_step)\n    if absf(step) < min_step:\n        step = signf(target - v) * minf(min_step, absf(target - v))\n    return v + step\n\nstatic func add_calc_angle(v: float, target: float, scale: float, max_step: float, min_step: float) -> float:\n    var diff := target - v\n    var step := clampf(diff / scale, -max_step, max_step)\n    if absf(step) <= min_step:\n        step = signf(diff) * minf(min_step, absf(diff))\n    return v + step\n\nfunc _wind_speed() -> float:\n    var w: Vector3 = Game.wind_vec()\n    var pow01: float = minf(1.0, Game.wind_power / 0.5)\n    var a := absf(wrapf(atan2(w.x, w.z) - yaw, -PI, PI)) / S16   # 0..0x8000\n    var f: float\n    if a < 0x4000:\n        f = 1.0 - a / 65536.0\n    elif a <= 0x6000:\n        f = 0.75 - (a - 0x4000) * 5.493164e-5\n    else:\n        f = maxf(0.0, 0.3 - (a - 0x6000) * 3.2967e-4)\n    return pow01 * f * WIND_INC_SPEED\n\nfunc _decrement(target: float) -> void:\n    speed_f = add_calc(speed_f, target, 0.05, 0.1, 0.015)\n\nfunc _first_decrement(target: float) -> void:\n    speed_f = add_calc(speed_f, target, 0.1, 5.0, 1.0)\n\nfunc _physics_process(_delta: float) -> void:\n    var stick_fwd := 0.0\n    var stick_right := 0.0\n    if rider and is_instance_valid(rider):\n        var s: Vector2 = rider.stick()   # raw pad: x right, y forward (the ship ignores the camera)\n        if s.length() > 0.1:\n            stick_fwd = clampf(s.y, -1.0, 1.0)\n            stick_right = clampf(s.x, -1.0, 1.0)\n    else:\n        mode = Mode.WAIT\n    # tiller and yaw (setSelfMove / setMoveAngle)\n    var tiller_target := stick_right * TILLER_MAX if mode != Mode.WAIT else 0.0\n    tiller = add_calc_angle(tiller, tiller_target, 4.0, TILLER_SPEED, 0x100)\n    var turn_rate := clampf(4.0 - absf(speed_f) / 55.0 * 3.0, 0.1, 3.6)\n    if landing > 0:\n        landing -= 1\n        turn_rate += (3.6 - turn_rate) * minf(landing, 15) / 15.0\n    prev_yaw = yaw\n    yaw -= turn_rate * (tiller / 64.0) * S16\n    # forward speed\n    match mode:\n        Mode.WAIT:\n            speed_f = add_calc(speed_f, 0.0, 0.1, 1.0, 0.05)\n        Mode.PADDLE:\n            if braking and speed_f >= 3.0:\n                speed_f = add_calc(speed_f, 0.0, 0.1, 1.0, 0.1)\n            else:\n                _decrement(maxf(stick_fwd, 0.0) * PADDLE_SPEED)\n        Mode.STEER:\n            var ws := _wind_speed()\n            if burst_target < speed_f:\n                _first_decrement(burst_target)\n                if speed_f - burst_target < 3.0:\n                    burst_target = 1.0e9\n            elif not sail_on or ws <= 0.0:\n                _decrement(stick_fwd * PADDLE_SPEED)\n            elif speed_f >= ws:\n                _decrement(ws)\n            else:\n                speed_f = add_calc(speed_f, ws, 0.1, 0.5, 0.1)\n    # hull against the islands\n    var before := global_position\n    velocity = forward() * speed_f * 30.0\n    move_and_slide()\n    global_position.y = before.y   # the water, not the collider, owns the height\n    if is_on_wall():\n        var n := get_wall_normal()\n        if n.dot(forward()) < cos(0x5000 * S16):   # normal > 112.5 deg off the heading: head-on\n            _first_decrement(0.0)\n    # follow the water (setYPos): proportional pull + buoyancy spring, bob, clamp\n    var water_y: float = Game.sea_height(global_position.x, global_position.z)\n    var r := minf(1.0, absf(speed_f) / 55.0)\n    var y := global_position.y\n    y += r * (water_y - y) * 0.1\n    vy += (water_y - y) * 0.05\n    vy = clampf(vy, -20.0, 20.0)\n    y += vy\n    bob += (1000.0 + randf() * 1000.0 + 500.0 * r) * S16\n    y += r * 0.25 * sin(bob) + 0.6\n    vy = add_calc(vy, 0.0, 0.05, 1.0, 0.05)\n    y = clampf(y, water_y - 60.0, water_y + 40.0)\n    global_position.y = y\n    # wave tilt (setWaveAngle): four probes, second-order follow\n    var xf := global_transform\n    var front := Game.sea_height((xf * Vector3(0, 0, 180)).x, (xf * Vector3(0, 0, 180)).z)\n    var back := Game.sea_height((xf * Vector3(0, 0, -190)).x, (xf * Vector3(0, 0, -190)).z)\n    var rgt := Game.sea_height((xf * Vector3(-80, 0, 0)).x, (xf * Vector3(-80, 0, 0)).z)\n    var lft := Game.sea_height((xf * Vector3(80, 0, 0)).x, (xf * Vector3(80, 0, 0)).z)\n    var pitch_t := atan2(-(front - back), 370.0) / S16\n    var roll_t := atan2(-(rgt - lft), 160.0) / S16\n    pitch_vel += (pitch_t - pitch) * 0.045\n    pitch += pitch_vel\n    pitch_vel = add_calc_angle(pitch_vel, 0.0, 0x14, 0x1000, 4)\n    roll_vel += (roll_t - roll) * 0.045\n    roll += roll_vel\n    roll_vel = add_calc_angle(roll_vel, 0.0, 0x14, 0x1000, 4)\n    noise_a += (0.5 * r + 1.0) * (800.0 + randf() * 800.0) * S16\n    noise_b += (0.5 * r + 1.0) * (600.0 + randf() * 600.0) * S16\n    var pitch_noise := r * 100.0 * sin(noise_a) + 30.0\n    var roll_noise := r * 115.0 * sin(noise_b) + 35.0\n    # steering heel spring\n    var heel_t := clampf(wrapf(yaw - prev_yaw, -PI, PI) / S16 * 7.0, -0x600, 0x600)\n    heel_vel += 0.05 * (heel_t - heel)\n    heel += heel_vel\n    heel_vel = add_calc_angle(heel_vel, 0.0, 0x14, 0x1000, 4)\n    _update_transform((pitch + pitch_noise) * S16, (roll + roll_noise + heel) * S16)\n    if before.distance_to(global_position) > 1.0e6:\n        global_position = before\n\nfunc _update_transform(p := 0.0, r := 0.0) -> void:\n    rotation = Vector3(p, yaw, r)\n'

_WARP_GD = """extends Area3D
# gcrip: walking into this (a door) loads the destination stage.

@export var dest_stage := ""
@export var dest_room := 0
@export var dest_spawn := 0
var armed := false   # arriving through this door puts Link inside the box: wait until he leaves

func _ready() -> void:
    body_entered.connect(_on_body_entered)
    body_exited.connect(_on_body_exited)
    await get_tree().create_timer(0.5).timeout
    armed = true
    for b in get_overlapping_bodies():
        if b is CharacterBody3D:
            armed = false

func _on_body_exited(body: Node3D) -> void:
    if body is CharacterBody3D:
        armed = true

func _on_body_entered(body: Node3D) -> void:
    if armed and body is CharacterBody3D:
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


def _copy_music(rip_dir: Path, out_dir: Path, stages: list[str]) -> int:
    """bgm.json (which song each stage / sea room plays) + the rendered WAVs those
    stages need, from <rip>/audio/music (``gcrip music``). Missing songs are skipped."""
    from gcrip.music import BGM_TABLE, songs_for_stages

    if BGM_TABLE.exists():
        shutil.copyfile(BGM_TABLE, out_dir / "bgm.json")
    src = rip_dir / "audio" / "music"
    if not src.is_dir():
        return 0
    base = sorted({st.split("_r")[0] for st in stages})
    dst = out_dir / "audio" / "music"
    n = 0
    for song in sorted(songs_for_stages(base)):
        wav = src / (song[:-4] + ".wav")
        if not wav.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        target = dst / wav.name
        if not target.exists() or target.stat().st_mtime < wav.stat().st_mtime:
            shutil.copyfile(wav, target)
        n += 1
    return n


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
item_next={_action(k["TAB"], _joy_button(JOY_DPAD_RIGHT))}
item_prev={_action(k["R"], _joy_button(JOY_DPAD_LEFT))}
wind_next={_action(k["F"], _joy_button(JOY_DPAD_UP))}
calibrate={_action(k["F1"])}

[physics]

common/physics_ticks_per_second=30
common/physics_interpolation=true

[importer_defaults]

wav={{
"compress/mode": 2,
"edit/loop_mode": 1
}}

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
        elif surface in ("ladder", "ladder_top", "climb", "nohang", "hookshot") and "mesh" in node:
            # wall codes Link reads (ladders / vines / no-hang); stage.gd puts them on layer 32
            node["name"] = f"wall_{surface}_" + node.get("name", "col").replace("/", "_") + "-colonly"
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


def _animated_glb(src: Path, out_glb: Path, clips: tuple[str, ...]) -> list[str]:
    """Rigged model + the named clips as a small self-contained glb. Returns the clip
    names that were kept (in file order)."""
    doc = json.loads(src.read_text(encoding="utf-8"))
    blob = (src.parent / doc["buffers"][0]["uri"]).read_bytes()
    trimmed, new_bin = _trim_animations(doc, blob, clips)
    kept = [a.get("name", "") for a in trimmed.get("animations", [])]
    tmp_bin = src.parent / f"_gcrip_{out_glb.stem}.bin"
    tmp_gltf = src.parent / f"_gcrip_{out_glb.stem}.gltf"
    trimmed["buffers"] = [{"uri": tmp_bin.name, "byteLength": len(new_bin)}]
    try:
        tmp_bin.write_bytes(new_bin)
        tmp_gltf.write_text(json.dumps(trimmed), encoding="utf-8")
        out_glb.parent.mkdir(parents=True, exist_ok=True)
        out_glb.write_bytes(glbmod.pack(tmp_gltf))
    finally:
        tmp_gltf.unlink(missing_ok=True)
        tmp_bin.unlink(missing_ok=True)
    return kept


_ITEM_MODELS = {
    "arrow": "Link.arc/archive/bdlm/arrow.gltf",
    "boomerang": "Link.arc/archive/bdl/boomerang.gltf",
    "bomb": "Link.arc/archive/bdlm/bomb.gltf",
    "hookshot": "Link.arc/archive/bdl/hookshot.gltf",
    "bow": "Link.arc/archive/bdl/bow.gltf",
    "ship": "Ship.arc/archive/bdl/fn_body.gltf",
    "ship_head": "Ship.arc/archive/bdl/fn_head_h.gltf",
}


def _item_models(rip_dir: Path, out_dir: Path) -> int:
    """Link's item models (arrow, boomerang, bomb, hookshot, bow) -> items/<name>.glb."""
    results = rip_dir / "rip_results.json"
    if not results.exists():
        return 0
    models = json.loads(results.read_text(encoding="utf-8"))["models"]
    n = 0
    for name, suffix in _ITEM_MODELS.items():
        rel = next((m["out_rel"] for m in models if (m.get("out_rel") or "").endswith(suffix)), None)
        if rel is None or not (rip_dir / rel).exists():
            continue
        out_glb = out_dir / "items" / f"{name}.glb"
        src = rip_dir / rel
        if out_glb.exists() and out_glb.stat().st_mtime >= src.stat().st_mtime:
            n += 1
            continue
        try:
            doc = json.loads(src.read_text(encoding="utf-8"))
            clips = tuple(a.get("name", "") for a in doc.get("animations", [])[:1])
            _animated_glb(src, out_glb, clips)
            n += 1
        except (OSError, ValueError, KeyError):
            continue
    return n


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
    _animated_glb(rip_dir / rel, out_glb, _PLAYER_CLIPS)
    return True


# Actors that come alive with their own rig + clips (everything else stays a baked mesh).
# Clip choice: anything whose name contains one of these words, capped, so an NPC archive
# with 60 cutscene clips still exports small.
_ANIMATED_ACTORS = {
    "Aj1", "Ls1", "Ob1", "Ko1", "Ko2", "Yw1", "Ym1", "Ym2", "Bm1", "Ji1", "Ba1", "Kg1", "Kg2",
    "Dk", "Zl1", "NpcSo", "Bk", "Pig", "Kamome", "kani", "Ac1", "Cb1", "Hi1", "Md1", "De1",
    "Co1", "Zk1", "Tc", "Bs1", "Bs2", "Kp1", "Mt", "Ds1", "Sa1", "Gk1", "Um1", "Uo1", "Uo2",
    "Uo3", "Ub1", "Ub2", "Ub3", "Ub4", "Bj1", "Jb1", "Mk", "Hr", "Aj2", "Bmcon1", "Bms1",
    "Ah", "Auzu", "Puti", "c_green", "c_red", "c_blue", "c_black", "c_kiiro", "keeth", "Fkeeth",
}
_ANIM_WORDS = ("wait", "talk", "walk", "run", "attack", "damage", "dead", "fly", "swim", "idle")
_ANIM_CAP = 12


def _actor_models(rip_dir: Path, out_dir: Path, stage_data: dict) -> dict:
    """Export one animated glb per distinct model used by animated actors.
    Returns {model rel path: {"glb": res path, "clips": [...]}} (also written to
    actor_models.json)."""
    table_path = out_dir / "actor_models.json"
    table: dict = {}
    if table_path.exists():
        with contextlib.suppress(OSError, ValueError):
            table = json.loads(table_path.read_text(encoding="utf-8"))
    for info in stage_data.values():
        for rec in info.get("actors", []):
            if rec.get("actor") not in _ANIMATED_ACTORS:
                continue
            rel = rec.get("model")
            if not rel or rel in table:
                continue
            src = rip_dir / rel
            if not src.exists():
                continue
            try:
                doc = json.loads(src.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            names = [a.get("name", "") for a in doc.get("animations", [])]
            if not names or not doc.get("skins"):
                continue
            picked = [n for n in names if any(w in n.lower() for w in _ANIM_WORDS)]
            picked = (picked or names)[:_ANIM_CAP]
            glb_name = f"{Path(rel).parent.parent.parent.name}_{Path(rel).stem}.glb".replace(".arc", "")
            kept = _animated_glb(src, out_dir / "actors" / "models" / glb_name, tuple(picked))
            table[rel] = {"glb": f"res://actors/models/{glb_name}", "clips": kept}
    table_path.write_text(json.dumps(table, indent=1), encoding="utf-8")
    return table


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
        stage_data[name] = {
            "spawns": spawns,
            "actors": rep.get("actors") or [],
            "ships": rep.get("ships") or [],
            "wave_max": rep.get("wave_max") or {},
        }
        done.append(name)
        if not quiet:
            size = (out_dir / "stages" / f"{name}.glb").stat().st_size >> 20
            print(f"  {name:14} {size:4d} MB glb, {n_col} {kind}, "
                  f"spawn {tuple(round(v) for v in spawn)}")  # fmt: skip

    has_model = _player_model_glb(rip_dir, out_dir / "link.glb")
    n_models = len(_actor_models(rip_dir, out_dir, stage_data))
    if not quiet:
        print(f"  {n_models} animated actor models in actors/models/")
    dlg = Path(__file__).parent / "data" / "ww_npc_dialogue.json"
    if dlg.exists():
        shutil.copyfile(dlg, out_dir / "npc_dialogue.json")
    n_songs = _copy_music(rip_dir, out_dir, list(stage_data))
    if not quiet:
        print(f"  {n_songs} songs in audio/music/ (gcrip music renders more)")
    (out_dir / "player.gd").write_text(_PLAYER_GD, encoding="utf-8")
    (out_dir / "player.tscn").write_text(_player_tscn(has_model), encoding="utf-8")
    (out_dir / "game.gd").write_text(_GAME_GD, encoding="utf-8")
    (out_dir / "warp.gd").write_text(_WARP_GD, encoding="utf-8")
    (out_dir / "items").mkdir(parents=True, exist_ok=True)
    for fname, src in (("arrow.gd", _ARROW_GD), ("boomerang.gd", _BOOMERANG_GD),
                       ("bomb.gd", _BOMB_GD), ("hookshot.gd", _HOOKSHOT_GD),
                       ("ship.gd", _SHIP_GD)):
        (out_dir / "items" / fname).write_text(src, encoding="utf-8")
    n_items = _item_models(rip_dir, out_dir)
    if not quiet:
        print(f"  {n_items} item models in items/")
    (out_dir / "calib.gd").write_text(_CALIB_GD, encoding="utf-8")
    (out_dir / "calib.tscn").write_text(_CALIB_TSCN, encoding="utf-8")
    (out_dir / "stage.gd").write_text(_STAGE_GD, encoding="utf-8")
    (out_dir / "dialog.gd").write_text(_DIALOG_GD, encoding="utf-8")
    (out_dir / "dialog.tscn").write_text(_DIALOG_TSCN, encoding="utf-8")
    (out_dir / "menu.gd").write_text(_MENU_GD, encoding="utf-8")
    (out_dir / "menu.tscn").write_text(_MENU_TSCN, encoding="utf-8")
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
    # place names for every stage in the project (merged stage_data)
    from gcrip.data.ww_stages import WW_STAGE_NAMES

    names = {}
    for st in stage_data:
        m = re.match(r"^(.*)_r(\d+)$", st)
        key = f"{m.group(1)}/Room{m.group(2)}" if m else st
        if key in WW_STAGE_NAMES:
            names[st] = WW_STAGE_NAMES[key]
    (out_dir / "stage_names.json").write_text(json.dumps(names, indent=1), encoding="utf-8")
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
