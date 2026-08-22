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
const SWIM_START_DEPTH := 35.0       # how far below the surface swim engages (was 90, which
                                    # let Link plunge before catching - it read as a void)
const SWIM_RISE_ACCEL := 6.0         # swim.rise_accel
const SWIM_RISE_MAX := 20.0          # swim.rise_speed_max (raised so a dive surfaces quickly)
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

enum State { GROUND, AIR, ROLL, SWIM, LAND, ATTACK, JUMPCUT, JUMPCUT_LAND, DAMAGE, GLIDE, CARRY, GRAB, VJUMP, HANG, CLIMB, LADDER, CLIMBWALL, AIM, ITEM_WAIT, HOOKPULL, SHIP, ROPE_THROW, ROPE, LOOK, CROUCH, CRAWL, CONDUCT }
var ship: Node3D = null           # the King of Red Lions while riding

# --- X-button items (bow / boomerang / bombs / hookshot specs: projectile-items.md) ---
const X_ITEMS := ["leaf", "bow", "boomerang", "bomb", "hookshot", "rope", "telescope", "windwaker"]
const TELESCOPE_FOV := 25.0        # the scope's narrow view (subjectCamera zoom)
const STORY_X_ITEMS := ["telescope", "windwaker"]   # X items the story has to hand over first
const ITEM_NAMES := {"leaf": "Deku Leaf", "bow": "Bow", "boomerang": "Boomerang", "bomb": "Bombs", "hookshot": "Hookshot", "rope": "Grappling Hook", "windwaker": "Wind Waker"}
# --- grappling hook (d_a_player_rope.inc): aim, post search, pendulum ---
const ROPE_AIM_RANGE := 2200.0
const ROPE_POST_RANGE := 1000.0
const ROPE_PULL_ACCEL := 5.0
const ROPE_PULL_MAX := 50.0
const ROPE_AMP_START := 0x1800
const ROPE_AMP_MAX := 12000.0
const ROPE_PUMP := 0x40
const ROPE_DECAY := 0x20
const ROPE_DECAY_A := 0x200
const ROPE_RELEASE_XZ := 15.0
const ROPE_RELEASE_Y := 30.0
const ROPE_CLIMB := 5.0
const ROPE_SLIDE_ACCEL := 1.5
const ROPE_SLIDE_MAX := 27.0
const ROPE_TOP_MARGIN := 100.0
var rope: Node3D = null
var rope_hook := Vector3.ZERO
var rope_hang := Vector3.ZERO
var rope_len := 1.0
var rope_phase := 0.0
var rope_amp := 0.0
var rope_mode := "ready"      # ready / swing / hang / climb / slide
var rope_pull := 0.0
var rope_slide := 0.0
var rope_dir := Vector3.FORWARD
# --- first person / subject camera (d_camera.cpp subjectCamera SS01 / SX01 / SY01) ---
const FP_EYE_HEIGHT := 105.0           # Link's eyePos above his feet
const FP_EYE_BACK := 10.0              # Val5 = -10: eye sits 10 behind the head point
const FP_YAW_RATE := deg_to_rad(90.0) * 0.04    # Val24 x Val21 per frame at full stick
const FP_PITCH_RATE := deg_to_rad(70.0) * 0.04  # Val19 x Val21
const FP_PITCH_MAX := deg_to_rad(70.0)
const FP_FOV := 50.0                   # Val25
const FP_BLEND_FRAMES := 7
const FP_DEADBAND := 0.7
const BOOM_LOCK_MAX := 5
var fp_active := false
var fp_pitch := 0.0                    # positive = looking up
var fp_blend := 0
var fp_from_eye := Vector3.ZERO
var fp_from_center := Vector3.ZERO
var cstick_armed := true
var cstick_up_frames := 0
var boom_locks: Array = []
# --- boat camera (d_cam_style BN07: ride camera; rideCamera is a stub, rows inferred) ---
const BOAT_CAM_R := 800.0
const BOAT_CAM_PITCH := deg_to_rad(5.0)
const BOAT_CAM_PITCH_MIN := deg_to_rad(-10.0)
const BOAT_CAM_PITCH_MAX := deg_to_rad(30.0)
const BOAT_CAM_FOV := 70.0
const BOAT_CAM_YAW_RATE := 0.1
const BOAT_CAM_EYE_RATE := 0.2
var boat_cam_yaw := 0.0
# --- crouch / crawl (procCrouch, d_a_player_crawl.inc; crouch HIO table) ---
const CRAWL_PROBE_FRONT := 112.0       # l_crawl_start_front_offset
const CRAWL_PROBE_UP := 10.0
const CRAWL_CEILING := 125.0           # checkNotCrawlStand: stay down while roof - pos.y <= 125
const CRAWL_START_FRAMES := 9          # crawl_start_anim_end_frame (LIE)
const CRAWL_END_FRAMES := 8            # crawl_end_anim_end_frame (LIE reversed)
const CRAWL_SPEED_PEAK := 3.0          # crouch.crawl_speed_peak
const CRAWL_RATE_MIN := 1.0            # crawl_anim_rate_min_stick
const CRAWL_RATE_FULL := 3.0           # crawl_anim_rate_full_stick
const CRAWL_TURN_DIVISOR := 32.0
const CRAWL_TURN_MAX := 7000 * PI / 32768.0
const CRAWL_TURN_MIN := 500 * PI / 32768.0
const CRAWL_STROKE := 17.0             # LIEFORWARD half-cycle
var crawl_frame := 0.0
var crawl_phase := 0.0
var crawl_mode := "start"              # start / move / end
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
        if anim:
            for n in anim.get_animation_list():
                var l := n.to_lower()
                var loops := false
                for key in ["wait", "walk", "dash", "swim", "ladderltor", "ladderrtol", "wall", "crouch",
                            "lieforward", "grabwait", "bowwait", "boomwait", "hookshotwait", "ropewait",
                            "ropeclimb", "ropedown", "ropeswing", "hangmove", "walkbarrel"]:
                    if l.begins_with(key) or l == key:
                        loops = true
                if loops:
                    anim.get_animation(n).loop_mode = Animation.LOOP_LINEAR
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
    cam_manual = 90   # the auto-yaw stays off for 3 s after the last C-stick input

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
    var want: bool = Input.is_action_pressed("target") and st_no_lock == 0
    if st_no_lock > 0:
        st_no_lock -= 1
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
    _footstep_tick()
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
    if state == State.SHIP and ship and is_instance_valid(ship) and not Game.event_cam.has("eye") and not fp_active:
        _boat_camera()
        return
    if state == State.CRAWL and hud_prompt:
        hud_prompt.text = "crawling - stick: move   release R in the open: stand"
    if state == State.CONDUCT and hud_prompt:
        hud_prompt.text = conduct_prompt()
    if fp_active and not Game.event_cam.has("eye"):
        _fp_camera()
        return
    if Game.event_cam.has("eye"):
        # an event owns the camera (FIXEDFRM / UNITRANS / TALK ...)
        var eye: Vector3 = Game.event_cam["eye"]
        var center: Vector3 = Game.event_cam["center"]
        camera.global_position = eye
        if eye.distance_to(center) > 1.0:
            camera.look_at(center, Vector3.UP)
        camera.fov = float(Game.event_cam["fov"])
        cam_eye = eye
        cam_center = center
        return
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

# footsteps: walk.bck fires FT_WALK at frames 3 and 19 (ww_sound_effects.json, read off the
# disc) - one per foot.  The material comes from the collider under Link.
const FOOTFALL_FRAMES := [3.0, 19.0]
var _foot_last_frame := -1.0
var _foot_side := 0

func _footstep_tick() -> void:
    if anim == null or not is_on_floor():
        _foot_last_frame = -1.0
        return
    if current_clip != "walk" and current_clip != "dash":
        _foot_last_frame = -1.0
        return
    var frame := anim.current_animation_position * 30.0
    if _foot_last_frame >= 0.0:
        for f in FOOTFALL_FRAMES:
            var crossed: bool = (_foot_last_frame < f and frame >= f) \
                or (frame < _foot_last_frame and frame >= f)   # looped
            if crossed:
                var m := Game.ground_material(global_position)
                if m < 0:
                    m = 13          # stone, the most walked surface on the disc
                Game.play_sfx("foot_%d_%d" % [m, _foot_side], global_position,
                    -6.0 if current_clip == "walk" else -3.0)
                _foot_side = 1 - _foot_side
    _foot_last_frame = frame

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
    if Game.control_stick_frames > 0:
        return Game.control_stick
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

func swinging() -> bool:
    # mid sword swing: the CUT_* / JUMPCUT cut types daObjBarrier_c::break_start_wait_proc tests
    return state == State.ATTACK or state == State.JUMPCUT or state == State.JUMPCUT_LAND

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
    if absf(cx) > 0.15 or absf(cy) > 0.15:
        var kx := (absf(cx) - 0.15) / 0.85 * signf(cx)
        var ky := (absf(cy) - 0.15) / 0.85 * signf(cy)
        _orbit(kx * absf(kx) * 0.07, ky * absf(ky) * 0.05)

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
    if Game.event_running:
        _event_tick()
        return
    if Game.dialog_open:  # text box up: Link stands still
        _apply(Vector3.ZERO, -1.0)
        play_clip("wait")
        return
    if Input.is_action_just_pressed("action_y") and state in [State.GROUND, State.SWIM]:
        heavy = not heavy  # Iron Boots toggle (procBootsEquip; 19-frame anim skipped)
        _update_hud()
    if (Input.is_action_just_pressed("item_next") or Input.is_action_just_pressed("item_prev")) and state != State.CONDUCT:
        var step := 1 if Input.is_action_just_pressed("item_next") else -1
        var i := X_ITEMS.find(x_item)
        # story items only join the rotation once Link owns them (Aryll's Telescope)
        for _n in X_ITEMS.size():
            i = (i + step + X_ITEMS.size()) % X_ITEMS.size()
            if not STORY_X_ITEMS.has(X_ITEMS[i]) or Game.has_item(str(X_ITEMS[i])):
                break
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
        State.ROPE_THROW: _rope_throw()
        State.ROPE: _rope()
        State.LOOK: _look()
        State.CROUCH: _crouch()
        State.CRAWL: _crawl()
        State.CONDUCT: _conduct()
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

    if global_position.y < start_pos.y - 4000.0:  # fell out of the world (interiors have no floor past the door)
        start_pos = Game.safe_respawn(start_pos)
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
    var cy := -Input.get_joy_axis(0, JOY_AXIS_RIGHT_Y)   # C-stick up = +
    if cy < 0.2:
        cstick_armed = true
    if cstick_armed and cy > 0.95 and stick().length() < 0.5 and lock_target == null and speed < 1.0:
        cstick_up_frames += 1
        if cstick_up_frames >= 20:
            cstick_armed = false
            cstick_up_frames = 0
            _enter_look()
            return
    else:
        cstick_up_frames = 0
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

    if targeting and lock_target == null and dist < 0.05 and speed < 1.0 and is_on_floor():
        _enter_crouch()
        return
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
        if prompt_target != null and Engine.get_physics_frames() - Game.dialog_closed_frame > 8:
            prompt_target.interact(self)
            return
        if speed > 1.0:
            _enter_roll()
            return

    var was_on_floor := is_on_floor()
    if was_on_floor and dist > 0.3:
        # the ladder-top lip (wall code 5) at a platform edge: step over onto the ladder and
        # climb down (procLadderDown); the lip is on layer 32 only, so is_on_wall() never sees it
        var ftag := _front_wall(forward())
        if ftag == "ladder_top" and _enter_ladder_top():
            return
        if ftag == "ladder" and _enter_ladder(false):
            return
        # walking slowly up to an edge that has a ladder below it (no lip): climb down too
        if speed < AUTOJUMP_MIN_SPEED and _try_ladder_down():
            return
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

# ---------------------------------------------------------------- grappling hook (d_a_player_rope.inc / d_a_himo2.cpp)

func rope_hand() -> Vector3:
    return global_position + Vector3(0, 120.0, 0) + Basis(Vector3.UP, facing) * Vector3(-20.0, 0.0, 10.0)

func _find_post(d: Vector3) -> Node3D:
    # search_target: the nearest post in front, within range, close to the aim line
    var best: Node3D = null
    var best_score := 1.0e9
    for n in get_tree().get_nodes_in_group("grapple_post"):
        if not is_instance_valid(n) or not n.has_method("hook_point"):
            continue
        var hp: Vector3 = n.hook_point()
        var to := hp - rope_hand()
        var dist := to.length()
        if dist > ROPE_AIM_RANGE or dist < 100.0 or absf(to.y) > 1500.0:
            continue
        var ang := acos(clampf(to.normalized().dot(d), -1.0, 1.0))
        var tol := maxf(atan(60.0 * 6.0 / maxf(dist, 1.0)), deg_to_rad(12.0))
        # no first-person aim yet: a near post well inside the view counts even if the
        # camera is not pitched at it (the game's narrow screen-space test needs that)
        if ang > tol and not (dist <= ROPE_POST_RANGE and ang < deg_to_rad(30.0)):
            continue
        var score := dist + ang * 2000.0
        if score < best_score:
            best_score = score
            best = n
    return best

func _throw_rope(d: Vector3) -> void:
    var r := Node3D.new()
    r.set_script(load("res://items/rope.gd"))
    get_tree().current_scene.add_child(r)
    r.launch(self, rope_hand(), aim_yaw, aim_pitch, _find_post(d))
    rope = r
    projectile = r

func _rope_throw() -> void:
    # ROPE_THROW / ROPE_THROW_CATCH: Link stands in the throw pose until the rope is back
    facing = aim_yaw
    velocity = Vector3.ZERO
    _apply(Vector3.ZERO, -1.0)
    if rope == null or not is_instance_valid(rope):
        rope = null
        projectile = null
        _enter_ground()

func rope_done() -> void:
    rope = null
    projectile = null
    if state == State.ROPE_THROW:
        play_clip("ropethrowcatch", 2.0 / 30.0)
        state = State.ITEM_WAIT
        aim_frames = 0
    elif state == State.ROPE:
        _enter_air(Vector3.ZERO, 0.0, GRAVITY)

func rope_hooked(r: Node3D, hook: Vector3) -> void:
    # procRopeReady: the hang point sits under the hook; pull Link to it, then swing
    rope = r
    rope_hook = hook
    var space := get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(hook, hook - Vector3(0, 4000.0, 0), 1)
    var hit := space.intersect_ray(q)
    var hang_y := global_position.y + 95.0
    if hit and hook.y - hit.position.y < 1200.0:
        hang_y = hit.position.y + 175.0
    hang_y = minf(hang_y, hook.y - ROPE_TOP_MARGIN)
    rope_hang = Vector3(hook.x, hang_y, hook.z)
    rope_len = maxf(hook.y - hang_y, 50.0)
    rope_mode = "ready"
    rope_pull = 0.0
    rope_dir = forward()
    state = State.ROPE
    velocity = Vector3.ZERO
    play_clip("ropewait", 3.0 / 30.0)

func _rope_release(force_fall: bool) -> void:
    var r := rope
    rope = null
    projectile = null
    if r and is_instance_valid(r) and r.has_method("release"):
        r.release()
    if force_fall:
        _enter_air(Vector3.ZERO, 0.0, GRAVITY)
        return
    # swing release: 15 / 30 x (amp / max) x max(1, len / 5000), along the swing direction
    var factor := (rope_amp / ROPE_AMP_MAX) * maxf(1.0, rope_len / 5000.0)
    var moving := signf(cos(rope_phase))
    if moving == 0.0:
        moving = 1.0
    var h := rope_dir * moving * ROPE_RELEASE_XZ * factor
    facing = heading_of(rope_dir * moving) if h.length() > 0.1 else facing
    _enter_air(h, ROPE_RELEASE_Y * factor, GRAVITY)
    play_clip("jmped", 0.1)

func _rope() -> void:
    if rope == null or not is_instance_valid(rope):
        rope = null
        _enter_air(Vector3.ZERO, 0.0, GRAVITY)
        return
    velocity = Vector3.ZERO
    var s := stick()
    var fwd_in := 0.0
    if s.length() > 0.3:
        fwd_in = stick_world_dir(s).dot(rope_dir)
    var a_held := Input.is_action_pressed("action_a")
    match rope_mode:
        "ready":
            # pulled toward the hang point, +5 per frame up to 50
            rope_pull = minf(rope_pull + ROPE_PULL_ACCEL, ROPE_PULL_MAX)
            var to := rope_hang - global_position
            if to.length() <= 2.0 * rope_pull:
                global_position = rope_hang
                rope_mode = "swing"
                rope_amp = ROPE_AMP_START
                rope_phase = 0.0
                rope_len = maxf(rope_hook.y - rope_hang.y, 50.0)
            else:
                global_position += to.normalized() * rope_pull
            play_clip("ropewait")
        "swing":
            var omega := sqrt(2.0 / rope_len)
            rope_phase += omega
            if absf(fwd_in) > 0.3:
                rope_amp += ROPE_PUMP * absf(cos(rope_phase))
            elif a_held:
                rope_amp -= ROPE_DECAY_A
            else:
                rope_amp -= ROPE_DECAY
            rope_amp = clampf(rope_amp, 0.0, ROPE_AMP_MAX)
            var theta := rope_amp * S16_TO_RAD * sin(rope_phase)
            global_position = rope_hook + rope_dir * (sin(theta) * rope_len) - Vector3(0, cos(theta) * rope_len, 0)
            play_clip("ropeswingf" if cos(rope_phase) > 0.0 else "ropeswingb", 4.0 / 30.0)
            if Input.is_action_just_pressed("action_b") or Input.is_action_just_pressed("action_x"):
                _rope_release(false)
                return
            if rope_amp <= 0.0:
                rope_mode = "hang"
        "hang":
            global_position = Vector3(rope_hook.x, global_position.y, rope_hook.z)
            play_clip("ropewait")
            if a_held and fwd_in > 0.3:
                rope_mode = "climb"
            elif a_held and fwd_in < -0.3:
                rope_mode = "slide"
                rope_slide = 0.0
            elif not a_held and absf(fwd_in) > 0.3:
                rope_mode = "swing"
                rope_amp = 2048.0 * minf(1.0, 500.0 / rope_len)
                rope_phase = 0.0
                rope_len = maxf(rope_hook.y - global_position.y, 50.0)
            elif Input.is_action_just_pressed("action_b"):
                _rope_release(true)
                return
        "climb":
            var top := rope_hook.y - ROPE_TOP_MARGIN
            global_position.y = minf(global_position.y + ROPE_CLIMB, top)
            play_clip("ropeclimb", 2.0 / 30.0)
            if not a_held or fwd_in <= 0.3:
                rope_mode = "hang"
        "slide":
            rope_slide = minf(rope_slide + ROPE_SLIDE_ACCEL, ROPE_SLIDE_MAX)
            var bottom := rope_hang.y - 300.0
            var space := get_world_3d().direct_space_state
            var q := PhysicsRayQueryParameters3D.create(global_position + Vector3(0, 10.0, 0), global_position - Vector3(0, 400.0, 0), 1)
            var hit := space.intersect_ray(q)
            if hit:
                bottom = maxf(bottom, hit.position.y + 175.0)
            global_position.y = maxf(global_position.y - rope_slide, bottom)
            play_clip("ropedown", 2.0 / 30.0)
            if not a_held or fwd_in >= -0.3 or global_position.y <= bottom:
                rope_mode = "hang"

# ---------------------------------------------------------------- crouch / crawl

func _enter_crouch() -> void:
    state = State.CROUCH
    speed = 0.0
    velocity = Vector3.ZERO
    play_clip("crouch", 3.0 / 30.0)

func _crouch() -> void:
    _apply(Vector3.ZERO, -1.0)
    var s := stick()
    if not Input.is_action_pressed("target") or lock_target != null:
        _enter_ground()
        return
    if s.length() > 0.5:
        var want := heading_of(stick_world_dir(s))
        var off := absf(wrapf(want - facing, -PI, PI))
        if off < deg_to_rad(60.0):
            turn_toward(want, TURN_MAX_STEP, TURN_MIN_STEP, TURN_DIVISOR)
            if _crawl_gap_ahead():
                _enter_crawl()
                return
        # moving out of the crouch: back to normal play (strafe / walk)
        _enter_ground()
        return
    play_clip("crouch")

func _crawl_gap_ahead() -> bool:
    # procCrouch: a wall 112 ahead at knee height (+10) with open space under 125 - a crawl hole
    var space := get_world_3d().direct_space_state
    var from := global_position + Vector3(0, CRAWL_PROBE_UP, 0)
    var low := PhysicsRayQueryParameters3D.create(from, from + forward() * CRAWL_PROBE_FRONT, 1)
    if space.intersect_ray(low):
        return false   # solid at knee height: no hole
    var head := global_position + Vector3(0, 60.0, 0)
    var mid := PhysicsRayQueryParameters3D.create(head, head + forward() * CRAWL_PROBE_FRONT, 1)
    return not space.intersect_ray(mid).is_empty()

func _roof_height() -> float:
    # RoofChk: ceiling above Link's feet, 1e9 if none within reach
    var space := get_world_3d().direct_space_state
    var from := global_position + Vector3(0, 5.0, 0)
    var q := PhysicsRayQueryParameters3D.create(from, from + Vector3(0, 400.0, 0), 1)
    var hit := space.intersect_ray(q)
    return (hit.position.y - global_position.y) if hit else 1.0e9

func _enter_crawl() -> void:
    state = State.CRAWL
    crawl_mode = "start"
    crawl_frame = 0.0
    crawl_phase = 0.0
    speed = 0.0
    play_clip("lie", 3.0 / 30.0, 1.0)

func _crawl() -> void:
    var s := stick()
    var dist := minf(s.length(), 1.0)
    match crawl_mode:
        "start":
            crawl_frame += 1.0
            _apply(forward() * 1.5, -1.0)   # eases under the lip while lying down
            if crawl_frame >= CRAWL_START_FRAMES:
                crawl_mode = "move"
                crawl_phase = 0.0
                play_clip("lieforward", 5.0 / 30.0, CRAWL_RATE_MIN)
        "move":
            var roof := _roof_height()
            var in_tunnel := roof <= CRAWL_CEILING
            if dist > 0.1:
                var want := heading_of(stick_world_dir(s))
                var back: bool = absf(wrapf(want - facing, -PI, PI)) > PI * 0.5
                if not back:
                    turn_toward(want, CRAWL_TURN_MAX, CRAWL_TURN_MIN, CRAWL_TURN_DIVISOR)
                    _crawl_side_steer()
                var rate := lerpf(CRAWL_RATE_MIN, CRAWL_RATE_FULL, dist)
                crawl_phase += rate
                var sp := CRAWL_SPEED_PEAK * rate * absf(sin(PI * crawl_phase / CRAWL_STROKE))
                _apply(forward() * (-sp if back else sp), -1.0)
                play_clip("lieforward", ANIM_BLEND, rate * (-1.0 if back else 1.0))
            else:
                _apply(Vector3.ZERO, -1.0)
                play_clip("lieforward", ANIM_BLEND, 0.0)
            if not in_tunnel and (dist < 0.1 or not Input.is_action_pressed("target")):
                # checkNotCrawlStand: nothing overhead any more -> stand up
                crawl_mode = "end"
                crawl_frame = 0.0
                play_clip("lie", 2.0 / 30.0, -1.0)
            if not is_on_floor():
                _enter_air(forward() * speed, 0.0, GRAVITY)
        "end":
            crawl_frame += 1.0
            _apply(Vector3.ZERO, -1.0)
            if crawl_frame >= CRAWL_END_FRAMES:
                _enter_ground()

func _crawl_side_steer() -> void:
    # checkCrawlSideWall: tunnel walls 60-75 apart centre Link between them
    var space := get_world_3d().direct_space_state
    var right := forward().cross(Vector3.UP)
    var c := global_position + Vector3(0, 30.0, 0)
    var ql := PhysicsRayQueryParameters3D.create(c, c + right * 75.0, 1)
    var qr := PhysicsRayQueryParameters3D.create(c, c - right * 75.0, 1)
    var hl := space.intersect_ray(ql)
    var hr := space.intersect_ray(qr)
    if hl and hr:
        var dl: float = c.distance_to(hl.position)
        var dr: float = c.distance_to(hr.position)
        var d := dl + dr
        if d * d > 3600.0 and d * d < 5625.0:
            global_position += right * (dr - dl) * 0.25

# ---------------------------------------------------------------- first person (subjectCamera)

func _fp_enter() -> void:
    fp_active = true
    fp_pitch = 0.0
    fp_blend = FP_BLEND_FRAMES
    fp_from_eye = camera.global_position
    fp_from_center = cam_center
    if model:
        model.visible = false

func snap_camera_behind() -> void:
    cam_center = global_position + Vector3(0, CAM_ATTN_HEIGHT, 0)
    cam_eye = cam_center - forward() * 380.0 + Vector3(0, 120.0, 0)
    camera.global_position = cam_eye
    camera.look_at(cam_center, Vector3.UP)
    camera.reset_physics_interpolation()

func _fp_exit() -> void:
    if not fp_active:
        return
    fp_active = false
    if model:
        model.visible = true
    camera.fov = cam_fov
    # the follow camera resumes behind Link
    cam_center = global_position + Vector3(0, CAM_ATTN_HEIGHT, 0)
    cam_eye = cam_center - forward() * 380.0 + Vector3(0, 120.0, 0)
    if hud_reticle and lock_target == null:
        hud_reticle.visible = false

func _fp_stick() -> void:
    # CalcSubjectAngle: main stick past the 0.7 dead-band turns the body / pitches the eye
    var s := stick()
    var sx := 0.0
    var sy := 0.0
    if absf(s.x) > FP_DEADBAND * 0.5:
        sx = clampf((absf(s.x) - FP_DEADBAND * 0.5) / (1.0 - FP_DEADBAND * 0.5), 0.0, 1.0) * signf(s.x)
    if absf(s.y) > FP_DEADBAND * 0.5:
        sy = clampf((absf(s.y) - FP_DEADBAND * 0.5) / (1.0 - FP_DEADBAND * 0.5), 0.0, 1.0) * signf(s.y)
    # C-stick / mouse also look around
    sx += Input.get_joy_axis(0, JOY_AXIS_RIGHT_X)
    sy += -Input.get_joy_axis(0, JOY_AXIS_RIGHT_Y)
    facing -= clampf(sx, -1.0, 1.0) * FP_YAW_RATE
    fp_pitch = clampf(fp_pitch + clampf(sy, -1.0, 1.0) * FP_PITCH_RATE, -FP_PITCH_MAX, FP_PITCH_MAX)

func fp_eye() -> Vector3:
    return global_position + Vector3(0, FP_EYE_HEIGHT, 0) - forward() * FP_EYE_BACK

func fp_look_dir() -> Vector3:
    return Vector3(sin(facing) * cos(fp_pitch), sin(fp_pitch), cos(facing) * cos(fp_pitch))

func _fp_camera() -> void:
    var eye := fp_eye()
    var center := eye + fp_look_dir() * 300.0
    var fov := FP_FOV
    if fp_blend > 0:
        var k := 1.0 - float(fp_blend) / FP_BLEND_FRAMES
        fp_blend -= 1
        eye = fp_from_eye.lerp(eye, k)
        center = fp_from_center.lerp(center, k)
        fov = lerpf(cam_fov, FP_FOV, k)
    camera.global_position = eye
    camera.look_at(center, Vector3.UP)
    camera.fov = fov
    cam_eye = eye
    cam_center = center
    if hud_reticle:
        hud_reticle.visible = true
        hud_reticle.text = "+" if boom_locks.is_empty() else "+ %d" % boom_locks.size()
        var vp := get_viewport().get_visible_rect().size
        hud_reticle.position = vp * 0.5 - hud_reticle.size * 0.5

func _paint_boom_locks(d: Vector3) -> void:
    # boomerang in first person: everything the reticle line crosses gets a lock (max 5)
    boom_locks = boom_locks.filter(func(l): return l != null and is_instance_valid(l))
    if boom_locks.size() >= BOOM_LOCK_MAX:
        return
    var space := get_world_3d().direct_space_state
    var from := fp_eye()
    var q := PhysicsRayQueryParameters3D.create(from, from + d * 2500.0, 8 | 16)
    q.collide_with_areas = true
    var hit := space.intersect_ray(q)
    if hit:
        var c = hit.collider
        if c and (c.is_in_group("enemy") or c.is_in_group("interact")) and not boom_locks.has(c):
            boom_locks.append(c)

var telescope := false     # looking down the Telescope rather than plain first person

func _enter_look() -> void:
    state = State.LOOK
    speed = 0.0
    velocity = Vector3.ZERO
    telescope = false
    _fp_enter()
    play_clip("wait")

func _look() -> void:
    _apply(Vector3.ZERO, -1.0)
    _fp_stick()
    if telescope:
        camera.fov = TELESCOPE_FOV
        var eye := fp_eye()
        var d := Vector3(sin(facing) * cos(fp_pitch), sin(fp_pitch), cos(facing) * cos(fp_pitch))
        if Game.telescope_look(eye, d):
            telescope = false
            _fp_exit()
            _enter_ground()
            return
    var cy := -Input.get_joy_axis(0, JOY_AXIS_RIGHT_Y)
    if Input.is_action_just_pressed("action_b") or Input.is_action_just_pressed("action_a") or cy < -0.74:
        telescope = false
        _fp_exit()
        _enter_ground()
        return
    if Input.is_action_just_pressed("action_x") and x_item != "leaf":
        _fp_exit()
        if _use_item():
            return

# ---------------------------------------------------------------- conducting (d_a_player_tact.inc)

const CONDUCT_PLAY_FRAMES := 54        # the takt swing runs this long before the tablet judges it
const CONDUCT_PICK_COOL := 12          # stick repeat while scrolling the song list

var conduct_song := 0                  # index into Game.CONDUCT_SONGS (the save's tact order)
var conduct_playing := false
var conduct_frames := 0
var conduct_cool := 0

func _enter_conduct() -> void:
    # procTactWait_init: Link plants his feet, the baton comes up, and the game raises
    # daPyStts1_WIND_WAKER_CONDUCT_e - the flag every tablet's case 0 is watching for.
    state = State.CONDUCT
    speed = 0.0
    velocity = Vector3.ZERO
    conduct_playing = false
    conduct_frames = 0
    conduct_cool = 0
    play_clip("wait")

func conduct_prompt() -> String:
    if conduct_playing:
        return "conducting..."
    var t: Dictionary = Game.conduct_tablet(self)
    var near := ""
    if not t.is_empty():
        near = "   (a tablet is listening)"
    return "Wind Waker: %s   stick L/R: choose   A: conduct   B: put it away%s" % [
        str(Game.CONDUCT_SONGS[conduct_song]), near]

func _conduct() -> void:
    _apply(Vector3.ZERO, -1.0)
    if conduct_playing:
        conduct_frames += 1
        if conduct_frames < CONDUCT_PLAY_FRAMES:
            return
        conduct_playing = false
        # drop the baton state BEFORE the tablet orders its event: event_end() only hands
        # control back to a Link who is already standing on the ground
        _enter_ground()
        Game.conduct_play(self, conduct_song)
        return
    if conduct_cool > 0:
        conduct_cool -= 1
    else:
        var sx := stick().x
        if absf(sx) > 0.6:
            var step: int = 1 if sx > 0.0 else -1
            conduct_song = wrapi(conduct_song + step, 0, Game.CONDUCT_SONGS.size())
            conduct_cool = CONDUCT_PICK_COOL
    if Input.is_action_just_pressed("action_b"):
        _enter_ground()
        return
    if Input.is_action_just_pressed("action_a"):
        conduct_playing = true
        conduct_frames = 0
        # the two baked conducting swings Link owns: taktchisin is the Earth God's Lyric,
        # taktfujin the Wind God's Aria.  Any other melody reuses the Earth swing.
        var clip: String = "taktfujin" if conduct_song == 4 else "taktchisin"
        play_clip(clip, 4.0 / 30.0)

func conduct_pick(song: int) -> void:
    # harness hook: a synthesised press never reaches the stick poll, so set the song here
    conduct_song = clampi(song, 0, Game.CONDUCT_SONGS.size() - 1)

# ---------------------------------------------------------------- cutscenes (event_runner.gd)

var ev_walk_target := Vector3.ZERO
var ev_walking := false
var ev_clip := "wait"

func event_begin() -> void:
    ev_walking = false
    ev_clip = "wait"
    speed = 0.0
    velocity = Vector3.ZERO
    if state in [State.AIR, State.ROLL, State.ATTACK, State.AIM, State.ITEM_WAIT]:
        state = State.GROUND

func event_end() -> void:
    ev_walking = false
    if state == State.GROUND:
        _enter_ground()

func event_walk_to(p: Vector3) -> void:
    ev_walk_target = p
    ev_walking = true

func event_clip(c: String) -> void:
    ev_clip = c

func event_reached() -> bool:
    return not ev_walking

func _event_tick() -> void:
    if state == State.SHIP:
        _ship()
        return
    if ev_walking:
        var to := ev_walk_target - global_position
        to.y = 0.0
        if to.length() < 15.0:
            ev_walking = false
            speed = 0.0
            _apply(Vector3.ZERO, -1.0)
            play_clip("wait")
            return
        facing = heading_of(to.normalized())
        speed = minf(to.length(), 8.0)
        _apply(forward() * speed, -1.0)
        if not Game.cutscene_running():
            play_clip("walk", ANIM_BLEND, 1.0)
        return
    _apply(Vector3.ZERO, -1.0)
    if not Game.cutscene_running():
        play_clip(ev_clip)   # a .stb drives Link's animation itself

# ---------------------------------------------------------------- the boat (d_a_player_ship.inc)

func _boat_camera() -> void:
    # BN07: ~800 behind the boat, 5 deg up, FOV 70, slow yaw (0.1) and eye (0.2) rates;
    # the C-stick still orbits through cam_manual
    var attn: Vector3 = ship.global_position + Vector3(0, 92.5, 0)
    var yaw_goal: float = ship.yaw + PI
    if cam_manual > 0:
        cam_manual -= 1
        yaw_goal = boat_cam_yaw + cam_manual_yaw
        cam_manual_yaw = 0.0
    boat_cam_yaw += wrapf(yaw_goal - boat_cam_yaw, -PI, PI) * BOAT_CAM_YAW_RATE
    var pitch := clampf(BOAT_CAM_PITCH + cam_manual_pitch * 0.5, BOAT_CAM_PITCH_MIN, BOAT_CAM_PITCH_MAX)
    cam_center += (attn - cam_center) * 0.5
    var eye_goal := cam_center + _sph(BOAT_CAM_R, pitch, boat_cam_yaw)
    eye_goal.y = maxf(eye_goal.y, Game.sea_height(eye_goal.x, eye_goal.z) + 60.0)
    cam_eye += (eye_goal - cam_eye) * BOAT_CAM_EYE_RATE
    cam_fov += (BOAT_CAM_FOV - cam_fov) * 0.1
    _camera_output(attn)

func board(boat: Node3D) -> void:
    ship = boat
    # daShip_c raises RODE_KORL the first time Link boards the King of Red Lions; the continue
    # table stops forcing a stage once it is set, which is the moment the game opens up
    # (src/d/actor/d_a_ship.cpp:1570, src/d/d_com_inf_game.cpp:1305)
    if not Game.event_bit(0x2A08):
        Game.set_event_bit(0x2A08)
        Game.story_event_done("ff_board_korl")
    boat_cam_yaw = boat.yaw + PI
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
    if Game.has_item("rope"):
        if hud_prompt:
            hud_prompt.text += "   Y: Salvage"
        if Input.is_action_just_pressed("action_y"):
            Game.try_salvage(ship.global_position)
    if Input.is_action_just_pressed("target") and ship.jump_ok:
        ship.try_jump()
    if hud_prompt and ship.jump_ok:
        hud_prompt.text += "   R: Jump"
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
var st_no_lock := 0   # self-test: suppress Z-target acquisition for N frames (crouch test)
var st_ladder_foot := Vector3.ZERO
var st_ladder_n := Vector3.FORWARD
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
    560: ["target", true], 561: ["target", false],
    720: ["action_x", true], 721: ["action_x", false],
    760: ["action_a", true], 860: ["action_a", false],
    900: ["action_a", true], 901: ["action_a", false],
    # grappling hook: stand 500 in front of the nearest post, throw, pump, let go
    905: ["target", true], 906: ["crouch", true], 935: ["move_forward", true], 937: ["move_forward", false], 945: ["target", false],
    950: ["to_post", true],
    922: ["item_next", true], 923: ["item_next", false],
    990: ["action_x", true], 992: ["move_forward", true], 1004: ["move_forward", false], 1005: ["action_x", false],
    1080: ["move_forward", true], 1200: ["move_forward", false],
    1230: ["action_b", true], 1231: ["action_b", false],
    # the lookout ladder (sea_r44): climb to the platform, step back onto it to descend
    1300: ["to_ladder", true],
    1310: ["move_forward", true], 1660: ["move_forward", false],
    1680: ["to_hatch", true],
    1690: ["move_forward", true], 1860: ["move_forward", false],
}

func _selftest_tick() -> void:
    _st_frame += 1
    if _st_frame >= 1880:
        print("selftest done")
        get_tree().quit()
        return
    if _st_frame in [1740, 1830]:
        # free overhead view of the platform for the screenshot (event camera override)
        Game.set_event_cam(global_position + Vector3(-500, 700, -500), global_position + Vector3(100, 0, 200), 60.0)
    if _st_frame in [1665, 1760, 1850]:
        var img := get_viewport().get_texture().get_image()
        img.save_png("user://ladder_%d.png" % _st_frame)
        Game.clear_event_cam()
    if _st_frame == 12:
        Game.save_game("selftest")
    if _st_frame == 14:
        var ok := Game.load_game()
        print("selftest: save file exists=", FileAccess.file_exists(Game.save_path()), " reload=", ok, " keys=", Game.save.keys().size())
    if _ST_SCRIPT.has(_st_frame):
        var a: Array = _ST_SCRIPT[_st_frame]
        if a[0] == "board":
            var boat := get_tree().current_scene.get_node_or_null("KingOfRedLions")
            if boat:
                board(boat)
        elif a[0] == "to_ladder":
            # foot of the nearest ladder collider (layer 32, meta wall = ladder), facing it
            var best_d := 1.0e12
            var foot := Vector3.ZERO
            var nrm := Vector3.FORWARD
            var col := get_tree().current_scene.get_node_or_null("Collision")
            if col:
                for body in col.find_children("*", "StaticBody3D", true, false):
                    if not (body.has_meta("wall") and str(body.get_meta("wall")) == "ladder"):
                        continue
                    for shape in body.find_children("*", "CollisionShape3D", true, false):
                        var cs: CollisionShape3D = shape
                        var poly := cs.shape as ConcavePolygonShape3D
                        if poly == null:
                            continue
                        var faces := poly.get_faces()
                        var i := 0
                        while i + 2 < faces.size():
                            var a0: Vector3 = cs.global_transform * faces[i]
                            var a1: Vector3 = cs.global_transform * faces[i + 1]
                            var a2: Vector3 = cs.global_transform * faces[i + 2]
                            var c := (a0 + a1 + a2) / 3.0
                            var lo := minf(a0.y, minf(a1.y, a2.y))
                            var n := (a1 - a0).cross(a2 - a0)
                            if n.length() > 1.0 and lo < 200.0 and c.y > 200.0 and c.distance_to(global_position) < best_d:
                                best_d = c.distance_to(global_position)
                                nrm = n.normalized()
                                nrm.y = 0.0
                                nrm = nrm.normalized()
                                foot = Vector3(c.x, lo, c.z)
                            i += 3
            if best_d < 1.0e12:
                if state == State.SHIP and ship:
                    ship.clear_rider()
                    ship = null
                # the outside of the ladder is the side with the lower ground (the tower is the other)
                var space := get_world_3d().direct_space_state
                var best_side := 1.0
                var best_gy := 1.0e9
                for sgn in [1.0, -1.0]:
                    var from: Vector3 = foot + nrm * float(sgn) * 90.0 + Vector3(0, 60.0, 0)
                    var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(from, from - Vector3(0, 600.0, 0), 1))
                    var gy: float = hit.position.y if hit else 1.0e8
                    if gy < best_gy:
                        best_gy = gy
                        best_side = sgn
                nrm *= best_side
                global_position = Vector3(foot.x, best_gy + 5.0, foot.z) + nrm * 90.0
                facing = heading_of(-nrm)
                st_ladder_foot = foot
                st_ladder_n = nrm
                velocity = Vector3.ZERO
                state = State.GROUND
                snap_camera_behind()
                print("selftest: at ladder foot ", foot.round(), " normal ", nrm)
        elif a[0] == "to_hatch":
            # on the platform, 120 inside the ladder's top edge, facing out over it
            var space := get_world_3d().direct_space_state
            var spot := Vector3(st_ladder_foot.x, global_position.y + 200.0, st_ladder_foot.z) - st_ladder_n * 120.0
            var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(spot, spot - Vector3(0, 600.0, 0), 1))
            if hit:
                global_position = hit.position + Vector3(0, 5.0, 0)
                facing = heading_of(st_ladder_n)
                velocity = Vector3.ZERO
                state = State.GROUND
                snap_camera_behind()
                print("selftest: at hatch ", global_position.round(), " facing out")
        elif a[0] == "crouch":
            lock_target = null
            st_no_lock = 45
            if state == State.GROUND:
                _enter_crouch()
        elif a[0] == "to_post":
            # a post with solid (not lava) ground somewhere around it: the pit's edge
            var best: Node3D = null
            var stand := Vector3.ZERO
            var space := get_world_3d().direct_space_state
            for n in get_tree().get_nodes_in_group("grapple_post"):
                var hp0: Vector3 = n.hook_point()
                for dist_i in [500.0, 700.0, 900.0, 1100.0, 1300.0]:
                    for k in 8:
                        var ang := k * PI / 4.0
                        var spot: Vector3 = hp0 + Vector3(sin(ang), 0.0, cos(ang)) * float(dist_i)
                        var q := PhysicsRayQueryParameters3D.create(spot + Vector3(0, 100.0, 0), spot - Vector3(0, 900.0, 0), 1 | 4)
                        var hit := space.intersect_ray(q)
                        if hit and hit.collider and not hit.collider.has_meta("liquid") and hp0.y - hit.position.y > 150.0 and hp0.y - hit.position.y < 900.0:
                            best = n
                            stand = hit.position + Vector3(0, 5.0, 0)
                            break
                    if best:
                        break
                if best:
                    break
            if best:
                if state == State.SHIP and ship:
                    ship.clear_rider()
                    ship = null
                var hp: Vector3 = best.hook_point()
                global_position = stand
                var back := stand - hp
                back.y = 0.0
                back = back.normalized()
                facing = heading_of(-back)
                velocity = Vector3.ZERO
                state = State.GROUND
                cam_center = global_position + Vector3(0, CAM_ATTN_HEIGHT, 0)
                cam_eye = cam_center - forward() * 380.0 + Vector3(0, 120.0, 0)
                print("selftest: at post ", hp.round())
        elif a[1]:
            Input.action_press(a[0])
        else:
            Input.action_release(a[0])
    if _st_frame % 30 == 0:
        var boat_info := ""
        if state == State.ROPE:
            boat_info = " rope mode=%s amp=%.0f phase=%.2f len=%.0f" % [rope_mode, rope_amp, rope_phase, rope_len]
        if fp_active:
            boat_info += " fp pitch=%.0fdeg" % rad_to_deg(fp_pitch)
        if state == State.LADDER:
            boat_info += " ladder y=%.0f" % global_position.y
        if ship and is_instance_valid(ship):
            boat_info = " ship mode=%d sail=%s speed=%.1f yaw=%.0f tiller=%.0f y=%.1f pitch=%.0f fly=%s jump_ok=%s" % [
                ship.mode, str(ship.sail_on), ship.speed_f, rad_to_deg(ship.yaw), ship.tiller,
                ship.global_position.y, ship.pitch, str(ship.flying), str(ship.jump_ok)]
        print("selftest f%d state=%s item=%s arrows=%d bombs=%d projectile=%s live_arrows=%d live_bombs=%d pos=%s%s" % [
            _st_frame, State.keys()[state], x_item, arrows, bombs,
            str(projectile != null and is_instance_valid(projectile)),
            live_arrows.filter(func(x): return x != null and is_instance_valid(x)).size(),
            live_bombs.filter(func(x): return x != null and is_instance_valid(x)).size(),
            str(global_position.round()), boat_info])

func _use_item() -> bool:
    match x_item:
        "windwaker":
            if not Game.has_item("windwaker"):
                return false
            _enter_conduct()
            return true
        "telescope":
            if not Game.has_item("telescope"):
                return false
            _enter_look()
            telescope = true
            camera.fov = TELESCOPE_FOV
            return true
        "bow", "boomerang", "hookshot", "rope":
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
    boom_locks = []
    if lock_target == null or not is_instance_valid(lock_target):
        _fp_enter()
    match x_item:
        "bow": play_clip("bowwait", 4.0 / 30.0)
        "boomerang": play_clip("boomwait", 4.0 / 30.0)
        "hookshot": play_clip("hookshotwait", 4.0 / 30.0)
        "rope": play_clip("ropethrowwait", 4.0 / 30.0)

func _aim_dir() -> Vector3:
    # first person: the subject camera's look angles; Z-target: at the target's eyes (pitch
    # clamped 22.5 deg); otherwise where the follow camera looks
    if fp_active:
        _fp_stick()
        aim_yaw = facing
        aim_pitch = -fp_pitch
        return Vector3(sin(aim_yaw) * cos(aim_pitch), -sin(aim_pitch), cos(aim_yaw) * cos(aim_pitch))
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
    if x_item == "boomerang" and fp_active:
        _paint_boom_locks(d)
    if Input.is_action_just_pressed("action_b") or Input.is_action_just_pressed("action_a"):
        _fp_exit()
        _enter_ground()   # cancelItemUpperReadyAnime
        return
    if Input.is_action_pressed("action_x"):
        return
    _fp_exit()
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
        "rope":
            _throw_rope(d)
            play_clip("ropethrow", 2.0 / 30.0)
            state = State.ROPE_THROW
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
    for l in boom_locks:
        if l != null and is_instance_valid(l) and not locks.has(l):
            locks.append(l)
    boom_locks = []
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
    # wall code of the tagged collider (layer 32) 25 + radius ahead of Link's waist, "" if none;
    # ladder tops are a short lip (code 5) at the platform edge, so a knee-height probe follows
    var space := get_world_3d().direct_space_state
    var from := global_position + Vector3(0, 60.0, 0)
    var q := PhysicsRayQueryParameters3D.create(from, from + into * 70.0, 32)
    var hit := space.intersect_ray(q)
    if not hit:
        from = global_position + Vector3(0, 18.0, 0)
        hit = space.intersect_ray(PhysicsRayQueryParameters3D.create(from, from + into * 90.0, 32))
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
    var q2 := PhysicsRayQueryParameters3D.create(probe, probe - d * 160.0, 32)
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

func _enter_ladder_top() -> bool:
    # from the platform: swing over the lip onto the ladder's outer face and descend
    var n := wall_hit_n
    n.y = 0.0
    if n.length() < 0.5:
        return false
    n = n.normalized()
    # the lip's normal may face either way; the ladder's outside is where the ground is lower
    var space := get_world_3d().direct_space_state
    var outward := n
    var best_gy := 1.0e9
    for sgn in [1.0, -1.0]:
        var from: Vector3 = wall_hit_pos + n * float(sgn) * 60.0 + Vector3(0, 40.0, 0)
        var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(from, from - Vector3(0, 800.0, 0), 1))
        var gy: float = hit.position.y if hit else -1.0e8
        if gy < best_gy:
            best_gy = gy
            outward = n * float(sgn)
    state = State.LADDER
    velocity = Vector3.ZERO
    speed = 0.0
    wall_hold = 0
    climb_over = 0
    ladder_n = outward
    facing = heading_of(-outward)
    var top_y := wall_hit_pos.y
    global_position = Vector3(wall_hit_pos.x, top_y - 30.0, wall_hit_pos.z) + outward * LADDER_OFFSET
    play_clip("ladderdwst", 3.0 / 30.0, 1.0)
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
    if state in [State.GROUND, State.CARRY, State.SWIM]:
        for n in get_tree().get_nodes_in_group("interact"):
            if not is_instance_valid(n) or n == held:
                continue
            var to_n: Vector3 = n.global_position - global_position
            to_n.y = 0.0
            # an NPC knows its own dAttention_c TALK distance (up to 500 for the Fishman);
            # this scan must not cap it at the generic pick-up reach
            var reach := 220.0
            if n.has_method("talk_range"):
                reach = maxf(reach, n.talk_range())
            if n.has_method("seat_point"):
                reach = maxf(reach, 450.0)   # the King of Red Lions is a big hull
            if to_n.length() > reach:
                continue
            if to_n.length() > 30.0 and forward().dot(to_n.normalized()) < 0.2:
                continue  # must roughly face it
            var p: String = n.interact_prompt(self)
            if p != "":
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
    # kill the fall: a small dive at most, so entering water reads as a splash, not a plunge
    velocity.y = clampf(velocity.y, -6.0 * 30.0, 0.0)
    # if a fast fall already carried him well under, lift him back near the surface at once
    var surf := water_surface()
    if surf > -1.0e8 and global_position.y < surf - 120.0:
        global_position.y = surf - 60.0
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
    if Input.is_action_just_pressed("action_a") and prompt_target != null             and prompt_target.has_method("seat_point"):
        prompt_target.interact(self)   # climb aboard the King of Red Lions from the water
        return
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
# clips whose root translation the game (and player.gd) applies from code: the ladder cycle
# climbs 37.5 per clip, the shimmy slides, the ledge climb rises 111 - played raw on top of
# our movement they double up and snap back every loop (the "jittery ladder")
_PLAYER_ROOT_MOTION_CLIPS = (
    "ladderltor",
    "ladderrtol",
    "ladderupedl",
    "ladderdwst",
    "ladderupst",
    "wallpl",
    "walldw",
    "wallwl",
    "wallwr",
    "wallholdup",
    "vjmpcl",
    "hangmovel",
    "hangmover",
    "ropeclimb",
    "ropedown",
    "mstepover",
)
_PLAYER_CLIPS = (
    "wait", "walk", "dash", "mjmp", "jmped", "mrolll", "swimwait", "swiming",
    "cuta", "cutf", "cutr", "cutl", "cutea", "cuteb", "jattack", "jattackland",
    "damf", "damb", "daml", "damr", "dam", "damff", "damfb", "talka",
    "grabup", "grabwait", "grabthrow", "walkbarrel",
    "vjmp", "vjmpcha", "vjmpchb", "vjmpcl", "mstepover", "hangmovel", "hangmover", "jmpeds",
    "bowwait", "arrowshoot", "boomwait", "boomthrow", "boomcatch", "hookshotwait", "hookshotjmp",
    "ropethrow", "ropethrowwait", "ropethrowcatch", "ropewait", "ropeswingf", "ropeswingb", "ropeclimb", "ropedown",
    "crouch", "lie", "lieforward",
    "taktchisin", "taktfujin",
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
var dialog_closed_frame := -1000
var stage_names: Dictionary = {}
var menu: Node = null
var bgm: Dictionary = {}           # data/ww_bgm.json: stages / sea_rooms -> song
var bgm_player: AudioStreamPlayer = null
var bgm_song := ""
var selftest: bool = "--selftest" in OS.get_cmdline_user_args()   # scripted input run
var shot_actor := ""   # --shot=<actor>: screenshot that actor's face to user://shot.png and quit
var door_test := false   # --door[=<dest stage>]: take the first (matching) door, report the landing
var door_want := ""
var door_legs := 0
var story_test: bool = "--story" in OS.get_cmdline_user_args()   # walk every story state
var story_tick := 0     # NPC-ordered story events are checked twice a second, not every frame
var hit_log: Array = []   # every event a breakable story object has ordered, in order
var menu_test := ""   # --menu: open the Start menu, cycle every tab, screenshot each
var menu_frames := 0
var event_test := ""  # --event=<NAME>: run that stage event and report what it drives
var event_frames := 0
var newgame_test: bool = "--newgame" in OS.get_cmdline_user_args()   # fresh save from the top
var talk_test := ""   # --talk=<actor>: stand in front of that NPC, talk, report the story step
# --dialogue: replay the opening's story states and print every villager's line at each one
var dialogue_test: bool = "--dialogue" in OS.get_cmdline_user_args()
# --scope: hand Link the Telescope and point it at the story step's look target
var scope_test: bool = "--scope" in OS.get_cmdline_user_args()
# --near: walk Link into the NPC-ordered story event that is waiting in this stage
var near_test: bool = "--near" in OS.get_cmdline_user_args()
# --conduct[=bad]: stand Link and his duet partner at this stage's MknjD tablet and play
# the melody it demands.  =bad puts the partner round the far side, for the ERROR branch.
var conduct_test := false
var conduct_bad := false
# --object: satisfy the object-ordered story step waiting in this stage and let the object fire
var object_test: bool = "--object" in OS.get_cmdline_user_args()
var object_fired := false
# --opening: play the mined opening graph end to end, one step at a time, and report each
var opening_test: bool = "--opening" in OS.get_cmdline_user_args()
# --sweep[=<from>:<to>]: walk every exported stage, land Link on its first spawn and check that
# the ground is really under him.  This is the check a play-test cannot do 161 times.
var sweep_test := false
var sweep_from := 0
var sweep_to := 100000
var sweep_list: Array = []
var sweep_idx := -1
var sweep_wait := 0
var sweep_y := 0.0
var sweep_report: Array = []
# --doors[=<from>:<to>]: arrive at every door landing in the game (door_targets.json, written
# by the export from the Warp nodes) and check Link has ground under him.  "I went through a
# door and fell into a void" is the one bug a play-test keeps finding and cannot enumerate.
var doors_test := false
var doors_list: Array = []
var doors_idx := -1
var doors_wait := 0
var doors_report: Array = []
# --models: load every animated actor model and report the ones with no mesh, no clips, or a
# head model that does not resolve.  --cutscenes: play every baked .stb through to its end.
var models_test: bool = "--models" in OS.get_cmdline_user_args()
# --no-toon : load without any shading override at all
var no_toon: bool = "--no-toon" in OS.get_cmdline_user_args()
# --shade=toon|hybrid|clay|paper|pbr : the look to start in (F6 cycles them in play)
var shade_arg := ""
# --gi : turn SDFGI on (off by default: at this world scale it is heavy, and it crashed once)
var gi_on: bool = "--gi" in OS.get_cmdline_user_args()

# --hitsw[=<kind>] : strike every hit switch in this stage with that attack kind
var hitsw_test := ""
# --dungeon : report every locked door in this stage, then try each one with and without its key
var dungeon_test: bool = "--dungeon" in OS.get_cmdline_user_args()
# --salvage=<kind> : sail the boat onto a point of that kind and work the crane
var salvage_test := -1
# --island=<type> : stand Link inside that island's TagIsl, satisfy its terms, watch it fire
var island_test := -1
# --timer=<step id>[:win] : raise the island's switch, then run the clock out (or open the chest)
var timer_test := ""
var timer_win := false
var timer_lose := false   # go INTO the cave and let it expire there: the ejection branch
var timer_settle := 0     # frames to let a deferred ejection warp actually land
# --hit: raise the waiting hit step's bits before the stage loads, then break its object
var hit_test: bool = "--hit" in OS.get_cmdline_user_args()
var hit_struck := 0
# --clock: step the clock through a whole in-game day headlessly, reporting the hour,
# `night` and the placement layer a handful of stages pick; then nightStop and a rollover.
var clock_test: bool = "--clock" in OS.get_cmdline_user_args()
var clock_frames := 0
var clock_step := 0
# --defeat=<actor>[:boss] or --defeat=room:<n> : report which story step a death would advance
var defeat_test := ""
# --control[=<port>]: open the debug command channel (control.gd) on 127.0.0.1
var control_port := 0
var control: Node = null
var control_stick := Vector2.ZERO      # a stick position pushed in over the channel
var control_stick_frames := 0
var cuts_test := false
var cuts_list: Array = []
var cuts_idx := -1
var cuts_wait := 0
var cuts_report: Array = []
var cuts_frame := 0
var cuts_stall := 0
var open_idx := -1
var open_wait := 0
var open_settle := 0
var open_retry := false
var open_report: Array = []
var open_forced: Dictionary = {}
var start_stage := ""   # --stage=<key>[:<spawn>]: boot straight into that stage
var start_spawn := 0
const DLG_STATES := [
    ["fresh file", [], []],
    ["after the storybook (Hero's Clothes)", [0x2A80], ["clothes"]],
    ["after the telescope scene", [0x2A80, 0x0310, 0x0001], ["clothes", "telescope"]],
    ["after Orca's sword", [0x2A80, 0x0310, 0x0001, 0x2F10, 0x0501],
     ["clothes", "telescope", "sword"]],
    ["after Aryll is taken", [0x2A80, 0x0310, 0x0001, 0x2F10, 0x0501, 0x0101, 0x0E20],
     ["clothes", "telescope", "sword"]],
    ["with Grandma's shield", [0x2A80, 0x0310, 0x0001, 0x2F10, 0x0501, 0x0101, 0x0E20, 0x3202],
     ["clothes", "telescope", "sword", "shield"]],
]
var auto_a := 0
var story_idx := -1
var story_frames := 0
var door_frames := 0
var shot_frames := 0
var events: Dictionary = {}        # this stage's event_list.dat: name -> event
var enemies: Dictionary = {}       # enemies.json: actor -> constants (data/ww_enemies_*.json)
var layers: Dictionary = {}        # layers.json: story-state -> which placement layer is live
var story: Dictionary = {}         # story.json: the mined opening graph (steps -> bits)
const STORY_OBJ_NOWHERE := Vector3(-1.0e9, -1.0e9, -1.0e9)   # no such object placed in this stage
# ---- day / night clock (src/d/d_kankyo.cpp).  The save keeps the time of day as a float
# in [0, 360): dKy_getdaytime_hour() is (int)(time / 15.0f) (d_kankyo.cpp:613-616), so 15
# units are one in-game hour and 360 units a whole day.  setDaytime() adds mTimeAdv (0.02f,
# envcolor_init at d_kankyo.cpp:476) once per frame and the game runs at 30 fps, so 0.6
# units pass per real second: a full in-game day is 600 s (10 real minutes) and one in-game
# hour is 25 real seconds.  Crossing 360 bumps the date and runs dKankyo_DayProc()
# (d_kankyo.cpp:524-530).
const DAY_UNITS := 360.0            # mCurTime wraps here
const UNITS_PER_HOUR := 15.0        # dKy_getdaytime_hour: (int)(time / 15.0f)
const TIME_ADV := 0.02              # g_env_light.mTimeAdv, added once per frame
const GAME_FPS := 30.0              # TWW's frame rate (d_a_ib.cpp:109 setItemTimerForIball(3*30, 2*30))
const DAY_START_HOUR := 6           # dKy_daynight_check: 6 <= hour < 18 is day
const NIGHT_START_HOUR := 18
const NIGHT_STOP_BIT := 0x0A02      # ENDLESS_NIGHT; dKy_checkEventNightStop, d_kankyo.cpp:3160
const FRESH_DAY_TIME := 165.0       # dSv_player_status_b_c::init (d_save.cpp:51-60): a new
                                    # file opens at mTime = 165.0f, i.e. 11:00 on day 0
# Derived from the clock, never assigned: getLayerNo picks the day or the night variant of a
# placement layer with exactly this test (d_com_inf_game.cpp:189-190).
var night: bool:
    get:
        return is_night()
var _night_live := -1              # what the layers on screen assume; -1 until the first tick
# The real game does NOT rebuild a loaded room when the clock crosses dawn or dusk:
# getLayerNo runs from layerLoader when a room is DECODED (d_stage.cpp:2148-2150), so the new
# layer only appears the next time you enter. Rebuilding it under the player's feet blinks the
# whole world and swaps which buildings exist - twice every in-game day, which at 600 s/day is
# every couple of minutes of play. That is the "buildings render, then stop rendering".
var clock_reload_on_flip := false  # opt-in only; the layer is picked up at the next stage load
signal day_passed(day: int)        # midnight rolled over: dKankyo_DayProc's hook
const SAVE_FILE := "user://gcrip_save.json"
const SAVE_FILE_TEST := "user://gcrip_save_test.json"

var _save_file := ""   # latched on first use: a harness that ends its scripted phase must not
                       # fall through to the player's file afterwards

func save_path() -> String:
    # a headless harness must never touch the file a person plays on - that is how a --defeat
    # test once left "dr_gohma" in the user's save.  Decided ONCE per process.
    if _save_file == "":
        _save_file = SAVE_FILE_TEST if (scripted() or OS.get_cmdline_user_args().size() > 0)             else SAVE_FILE
    return _save_file
var autosave_frames := 0
var continued := false
var event_running := false
var event_runner: Node = null
var event_cam: Dictionary = {}     # {eye, center, fov} while an event drives the camera
var world_offset := Vector3.ZERO   # stage recentring offset (event positions are authored unshifted)
var fade_rect: ColorRect = null
# persistent player state (survives stage warps; the Player node is rebuilt per stage)
var save := {"hearts": 12, "hearts_max": 12, "magic": 16, "rupees": 0, "heavy": false,
             "items": {},
             "day": 0, "day_time": FRESH_DAY_TIME}

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
    var sy := FileAccess.open("res://story.json", FileAccess.READ)
    if sy:
        var parsed_y = JSON.parse_string(sy.get_as_text())
        if parsed_y is Dictionary:
            story = parsed_y
    var ly := FileAccess.open("res://layers.json", FileAccess.READ)
    if ly:
        var parsed_l = JSON.parse_string(ly.get_as_text())
        if parsed_l is Dictionary:
            layers = parsed_l
    var en := FileAccess.open("res://enemies.json", FileAccess.READ)
    if en:
        var parsed_e = JSON.parse_string(en.get_as_text())
        if parsed_e is Dictionary:
            enemies = parsed_e
    var bg := FileAccess.open("res://bgm.json", FileAccess.READ)
    if bg:
        var parsed_b = JSON.parse_string(bg.get_as_text())
        if parsed_b is Dictionary:
            bgm = parsed_b
    for a in OS.get_cmdline_user_args():
        if a.begins_with("--shot="):
            shot_actor = a.substr(7)
        elif a == "--story":
            story_test = true
        elif a == "--menu":
            menu_test = "stages"
        elif a.begins_with("--event="):
            event_test = a.substr(8)
        elif a.begins_with("--talk="):
            talk_test = a.substr(7)
        elif a.begins_with("--hitsw"):
            hitsw_test = a.substr(8) if a.length() > 8 else "sword"
        elif a.begins_with("--salvage="):
            salvage_test = int(a.substr(10))
        elif a.begins_with("--shade="):
            shade_arg = a.substr(8)
        elif a.begins_with("--island="):
            island_test = int(a.substr(9))
        elif a.begins_with("--timer="):
            var tspec := a.substr(8).split(":")
            timer_test = tspec[0]
            timer_win = tspec.size() > 1 and tspec[1] == "win"
            timer_lose = tspec.size() > 1 and tspec[1] == "lose"
        elif a.begins_with("--defeat="):
            defeat_test = a.substr(9)
        elif a.begins_with("--control"):
            control_port = int(a.substr(10)) if a.begins_with("--control=") else 8787
        elif a.begins_with("--cutscenes"):
            cuts_test = true
            if a.begins_with("--cutscenes="):
                var cspan := a.substr(12).split(":")
                sweep_from = int(cspan[0])
                if cspan.size() > 1:
                    sweep_to = int(cspan[1])
        elif a.begins_with("--doors"):
            doors_test = true
            if a.begins_with("--doors="):
                var dspan := a.substr(8).split(":")
                sweep_from = int(dspan[0])
                if dspan.size() > 1:
                    sweep_to = int(dspan[1])
        elif a.begins_with("--sweep"):
            sweep_test = true
            if a.begins_with("--sweep="):
                var span := a.substr(8).split(":")
                sweep_from = int(span[0])
                if span.size() > 1:
                    sweep_to = int(span[1])
        elif a.begins_with("--conduct"):
            conduct_test = true
            conduct_bad = a.ends_with("=bad")
        elif a.begins_with("--stage="):
            var want := a.substr(8).split(":")
            start_stage = want[0]
            start_spawn = int(want[1]) if want.size() > 1 else 0
        elif a.begins_with("--door"):
            door_test = true
            if a.begins_with("--door="):
                door_want = a.substr(7)
    if island_test >= 0:
        # deferred, like _hit_prepare: load_game() further down _ready REPLACES `save`, so a
        # bit raised here and now is wiped before the stage ever picks a layer
        _island_prepare.call_deferred()
    if hit_test:
        _hit_prepare.call_deferred()
    if start_stage != "":
        go_to_stage.call_deferred(start_stage, start_spawn)
    # pad mappings at boot (was only done on a menu warp: a shortcut launch ran the pad raw)
    _apply_saved_pad_mappings.call_deferred()
    Input.joy_connection_changed.connect(func(_id, _c): _apply_saved_pad_mappings())
    if no_toon:
        toon_on = false
    if shade_arg != "" and SHADE_MODES.has(shade_arg):
        shade_mode = shade_arg
    var lf := FileAccess.open("res://lighting.json", FileAccess.READ)
    if lf:
        var lp = JSON.parse_string(lf.get_as_text())
        if lp is Dictionary:
            physical = bool(lp.get("physical", false))
    var dgf := FileAccess.open("res://dungeons.json", FileAccess.READ)
    if dgf:
        var dgp = JSON.parse_string(dgf.get_as_text())
        if dgp is Dictionary:
            dungeons = dgp
    if load_game():
        print("gcrip: save file loaded (", str(save.get("saved_at", "?")), ")")
        if shade_arg == "" and SHADE_MODES.has(str(save.get("shade_mode", ""))):
            shade_mode = str(save["shade_mode"])
        if start_stage == "" and not selftest and shot_actor == "" and not door_test and not story_test and menu_test == "" and event_test == "" and not newgame_test and talk_test == "" and not dialogue_test and not clock_test:
            _continue_saved.call_deferred()
    bgm_player = AudioStreamPlayer.new()
    bgm_player.bus = "Master"
    bgm_player.volume_db = -6.0
    add_child(bgm_player)
    process_mode = Node.PROCESS_MODE_ALWAYS   # the pause menu must not freeze the autoload
    if cuts_test:
        # playback-only test: step the 30 Hz timeline as fast as the machine can, or a sweep
        # of 49 scenes takes their real running time (over an hour)
        Engine.physics_ticks_per_second = 960
        Engine.max_physics_steps_per_frame = 64
    if control_port > 0:
        control = load("res://control.gd").new()
        control.process_mode = Node.PROCESS_MODE_ALWAYS
        add_child(control)
        if not control.start(control_port):
            control.queue_free()
            control = null
    var fade_layer := CanvasLayer.new()
    fade_layer.layer = 40
    add_child(fade_layer)
    fade_rect = ColorRect.new()
    fade_rect.color = Color(0, 0, 0, 0)
    fade_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
    fade_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
    fade_layer.add_child(fade_rect)

# ---- events (event_list.dat -> events/<stage>.json; event_runner.gd plays one)

# ---- save file (the game's quest status: hearts, items, event bits, switches, place)

func save_game(reason := "") -> void:
    if dialogue_test or clock_test:
        return      # --dialogue / --clock rewrite `save` to walk state: never let that hit the disk
    var link := player()
    var cs := get_tree().current_scene
    if link and cs:
        save["last_stage"] = String(cs.name)
        var pos: Vector3 = link.global_position
        save["last_pos"] = [pos.x, pos.y, pos.z]
        save["last_facing"] = float(link.get("facing"))
    save["saved_at"] = Time.get_datetime_string_from_system()
    var f := FileAccess.open(save_path(), FileAccess.WRITE)
    if f:
        f.store_string(JSON.stringify(save, " "))
        if reason != "":
            print("gcrip: saved (", reason, ")")

func load_game() -> bool:
    var f := FileAccess.open(save_path(), FileAccess.READ)
    if f == null:
        return false
    var parsed = JSON.parse_string(f.get_as_text())
    if not (parsed is Dictionary):
        return false
    for k in parsed:
        save[k] = parsed[k]
    return true

func new_game() -> void:
    save = {"hearts": 12, "hearts_max": 12, "magic": 16, "rupees": 0, "heavy": false,
            "items": {},
            "day": 0, "day_time": FRESH_DAY_TIME}
    if FileAccess.file_exists(save_path()):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(save_path()))
    get_tree().paused = false
    if stage_data.has("sea_r44"):
        go_to_stage("sea_r44", 206)   # d_save.cpp: a fresh file starts on Outset's lookout
    else:
        go_to_stage(str(stage_data.keys()[0]))

func _continue_saved() -> void:
    # boot: pick up where the file left off (stage + position)
    var st := str(save.get("last_stage", ""))
    if st == "" or not stage_data.has(st):
        return
    continued = true
    var cs := get_tree().current_scene
    if cs and String(cs.name) == st:
        _restore_position.call_deferred()
        return
    last_warp_ms = -100000
    pending = {"stage": st, "room": 0, "spawn": 0, "restore": true}
    get_tree().change_scene_to_file.call_deferred("res://scenes/%s.tscn" % st)
    _place_player.call_deferred()

func _restore_position() -> void:
    var link := player()
    var pos: Array = save.get("last_pos", [])
    if link and pos.size() == 3:
        var p := Vector3(float(pos[0]), float(pos[1]) + 10.0, float(pos[2]))
        if not has_ground(p):
            print("gcrip: saved position has no floor - using the stage spawn")
            return
        link.global_position = p
        link.set("facing", float(save.get("last_facing", 0.0)))
        link.set("start_pos", link.global_position)

const OPEN_STEP_FRAMES := 3000     # a single step may not hold the walk up for ever

func _models_report() -> void:
    var bad := 0
    var n := 0
    var keys: Array = actor_models.keys()
    keys.sort()
    for k in keys:
        n += 1
        var am: Dictionary = actor_models[k]
        var glb := str(am.get("glb", ""))
        if glb == "" or not ResourceLoader.exists(glb):
            print("gcrip models: MISSING %s - %s" % [k, glb])
            bad += 1
            continue
        var scene: PackedScene = load(glb)
        if scene == null:
            print("gcrip models: FAIL    %s - will not load" % k)
            bad += 1
            continue
        var rig: Node3D = scene.instantiate()
        var meshes := 0
        var clips := 0
        for c in rig.find_children("*", "MeshInstance3D", true, false):
            meshes += 1
        for a in rig.find_children("*", "AnimationPlayer", true, false):
            clips += (a as AnimationPlayer).get_animation_list().size()
        var head := str(am.get("head", ""))
        var head_ok := head == "" or ResourceLoader.exists(head)
        if meshes == 0:
            print("gcrip models: NOMESH  %s - %d clips" % [k, clips])
            bad += 1
        elif not head_ok:
            print("gcrip models: NOHEAD  %s - head %s is missing" % [k, head])
            bad += 1
        elif clips == 0 and am.get("clips", []).size() > 0:
            print("gcrip models: NOCLIP  %s - json lists %d clips, the glb has none" % [
                k, (am.get("clips", []) as Array).size()])
            bad += 1
        rig.queue_free()
    print("gcrip models: %d models, %d with a problem" % [n, bad])

func _cuts_tick() -> void:
    if get_tree().current_scene == null:
        return          # nothing to parent a cutscene to yet: the boot stage is still loading
    if cuts_list.is_empty():
        var dir := DirAccess.open("res://cutscenes")
        var all: Array = []
        if dir:
            for f in dir.get_files():
                if f.ends_with(".json") and f != "index.json":
                    all.append(f.get_basename())
        all.sort()
        if all.is_empty():
            print("gcrip cutscenes: no baked cutscenes in res://cutscenes")
            get_tree().quit()
            return
        for i in all.size():
            if i >= sweep_from and i < sweep_to:
                cuts_list.append(all[i])
        print("gcrip cutscenes: ", cuts_list.size(), " scenes (", sweep_from, "..", sweep_to, ")")
    if cuts_wait > 0:
        cuts_wait -= 1
        if cutscene_running():
            # a scene is only wrong if its OWN frame counter stops: process frames run far
            # faster than the 30 Hz timeline in a headless run, so a wall-clock cap lies
            var fr := int(cutscene.frame)
            if fr > cuts_frame:
                cuts_frame = fr
                cuts_stall = 0
            else:
                cuts_stall += 1
            if cuts_stall < CUTS_STALL and cuts_wait > 0:
                return
            cuts_report.append("STUCK %s - frame %d of %d stopped advancing" % [
                str(cuts_list[cuts_idx]), fr, int(cutscene.frames)])
            cutscene.queue_free()
            cutscene = null
            cuts_wait = 0
            return
        cuts_report.append("ok    %s - played %d frames" % [str(cuts_list[cuts_idx]), cuts_frame])
        cuts_wait = 0
        return
    cuts_idx += 1
    if cuts_idx >= cuts_list.size():
        print("gcrip cutscenes: ---- result ----")
        var bad := 0
        for line in cuts_report:
            print("gcrip cutscenes: ", line)
            if not str(line).begins_with("ok"):
                bad += 1
        print("gcrip cutscenes: %d scenes, %d with a problem" % [cuts_report.size(), bad])
        get_tree().quit()
        return
    var nm := str(cuts_list[cuts_idx])
    if not play_cutscene(nm, Vector3.ZERO, 0.0):
        cuts_report.append("FAIL  %s - play_cutscene refused it" % nm)
        return
    cuts_wait = CUTS_CAP
    cuts_frame = 0
    cuts_stall = 0

const CUTS_CAP := 200000
const CUTS_STALL := 900

func _doors_tick() -> void:
    if doors_list.is_empty():
        var f := FileAccess.open("res://door_targets.json", FileAccess.READ)
        var parsed = JSON.parse_string(f.get_as_text()) if f else null
        if not (parsed is Array) or (parsed as Array).is_empty():
            print("gcrip doors: door_targets.json is missing or empty")
            get_tree().quit()
            return
        for i in (parsed as Array).size():
            if i >= sweep_from and i < sweep_to:
                doors_list.append(parsed[i])
        print("gcrip doors: ", doors_list.size(), " landings (", sweep_from, "..", sweep_to, ")")
    if doors_wait > 0:
        doors_wait -= 1
        if doors_wait == 0:
            _doors_check()
        return
    doors_idx += 1
    if doors_idx >= doors_list.size():
        print("gcrip doors: ---- result ----")
        var bad := 0
        for line in doors_report:
            print("gcrip doors: ", line)
            if not str(line).begins_with("ok"):
                bad += 1
        print("gcrip doors: %d landings, %d with a problem" % [doors_report.size(), bad])
        get_tree().quit()
        return
    var d: Dictionary = doors_list[doors_idx]
    var st := str(d.get("stage", ""))
    if not stage_data.has(st):
        doors_report.append("FAIL  %s spawn %d - stage is not in the build (from %s)" % [
            st, int(d.get("spawn", 0)), str(d.get("from", []))])
        doors_wait = 0
        return
    last_warp_ms = -100000
    warp(st, int(d.get("room", 0)), int(d.get("spawn", 0)))
    doors_wait = SWEEP_SETTLE

func _doors_check() -> void:
    var d: Dictionary = doors_list[doors_idx]
    var label := "%s room %d spawn %d" % [
        str(d.get("stage", "")), int(d.get("room", 0)), int(d.get("spawn", 0))]
    var lk := player()
    if lk == null:
        doors_report.append("FAIL  %s - no player" % label)
        return
    var pos: Vector3 = lk.global_position
    var start = lk.get("start_pos")
    var fell := 0.0
    if start is Vector3:
        fell = float(start.y) - pos.y
    var under := ground_under(pos)
    if under == "":
        doors_report.append("VOID  %s - nothing under Link at %s (from %s)" % [
            label, str(pos.round()), str(d.get("from", []))])
    elif fell > 2000.0:
        doors_report.append("DROP  %s - fell %.0f to %s (from %s)" % [
            label, fell, under, str(d.get("from", []))])
    else:
        doors_report.append("ok    %s - on %s" % [label, under])

const SWEEP_SETTLE := 150

func _sweep_tick() -> void:
    if sweep_list.is_empty():
        var all: Array = stage_data.keys()
        all.sort()
        for i in all.size():
            if i >= sweep_from and i < sweep_to:
                sweep_list.append(all[i])
        print("gcrip sweep: ", sweep_list.size(), " stages (", sweep_from, "..", sweep_to, ")")
    if sweep_wait > 0:
        sweep_wait -= 1
        if sweep_wait == 0:
            _sweep_check()
        return
    sweep_idx += 1
    if sweep_idx >= sweep_list.size():
        print("gcrip sweep: ---- result ----")
        var bad := 0
        for line in sweep_report:
            print("gcrip sweep: ", line)
            if not str(line).begins_with("ok"):
                bad += 1
        print("gcrip sweep: %d stages, %d with a problem" % [sweep_report.size(), bad])
        get_tree().quit()
        return
    var key := str(sweep_list[sweep_idx])
    go_to_stage(key)
    sweep_wait = SWEEP_SETTLE
    sweep_y = 0.0

func _sweep_check() -> void:
    var key := str(sweep_list[sweep_idx])
    var cs := get_tree().current_scene
    var lk := player()
    if cs == null or String(cs.name) == "":
        sweep_report.append("FAIL  %s - no scene" % key)
        return
    if lk == null:
        sweep_report.append("FAIL  %s - no player" % key)
        return
    var pos: Vector3 = lk.global_position
    var start = lk.get("start_pos")
    var fell := 0.0
    if start is Vector3:
        fell = float(start.y) - pos.y
    var under := ground_under(pos)
    var actors := get_tree().get_nodes_in_group("interact").size() \
        + get_tree().get_nodes_in_group("enemy").size()
    if under == "":
        sweep_report.append("VOID  %s - nothing under Link at %s (fell %.0f)" % [key, str(pos.round()), fell])
    elif fell > 2000.0:
        sweep_report.append("DROP  %s - fell %.0f to %s" % [key, fell, under])
    else:
        sweep_report.append("ok    %s - on %s, %d actors" % [key, under, actors])

func _open_scene_for(step: Dictionary) -> String:
    var stage := str(step.get("stage", ""))
    var room = step.get("room")
    if room != null and stage_data.has("%s_r%d" % [stage, int(room)]):
        return "%s_r%d" % [stage, int(room)]
    return stage if stage_data.has(stage) else ""

func _opening_tick() -> void:
    var steps: Array = story.get("steps", [])
    # busy: let the step play out (with a cap, so one long cutscene does not own the run)
    if event_running or cutscene_running() or dialog_open:
        open_wait += 1
        if open_wait < OPEN_STEP_FRAMES:
            return
        if event_runner and is_instance_valid(event_runner):
            event_runner.abort()
        if cutscene_running():
            cutscene.queue_free()
            cutscene = null
        # cut short, but the graph still needs what it would have raised, or every later
        # step that waits on those bits reports a failure this run never really had
        if open_idx >= 0 and open_idx < steps.size():
            var cur: Dictionary = steps[open_idx]
            var cev := sfield(cur, "event")
            print("gcrip opening: ", cur.get("id", "?"), " ran long - finishing it by hand")
            open_forced[str(cur.get("id", ""))] = true
            story_event_done(cev if cev != "" else str(cur.get("id", "")))
        open_wait = 0
        open_settle = 60
        return
    if open_settle > 0:
        open_settle -= 1
        return
    if open_retry:
        # the last tick only warped to the step's stage: run the step itself now
        open_retry = false
        open_wait = 0
        _opening_start(steps[open_idx], true)
        return
    if open_idx >= 0 and open_idx < steps.size():
        var prev: Dictionary = steps[open_idx]
        var pid := str(prev.get("id", ""))
        var mark := "MISS"
        if story_done(pid):
            mark = "SLOW" if open_forced.has(pid) else "OK  "
        open_report.append("%s %s" % [mark, pid])
    open_idx += 1
    open_wait = 0
    open_settle = 45
    if open_idx >= steps.size():
        print("gcrip opening: ---- result ----")
        for line in open_report:
            print("gcrip opening: ", line)
        var ok := 0
        for line in open_report:
            if str(line).begins_with("OK") or str(line).begins_with("SLOW"):
                ok += 1
        print("gcrip opening: %d/%d steps reached" % [ok, open_report.size()])
        get_tree().quit()
        return
    _opening_start(steps[open_idx])

func _opening_start(step: Dictionary, arrived := false) -> void:
    var id := str(step.get("id", ""))
    if story_done(id):
        print("gcrip opening: ", id, " (already done)")
        return
    var scene := _open_scene_for(step)
    var cs := get_tree().current_scene
    var here_scene := String(cs.name) if cs else ""
    if not arrived and scene != "" and scene != here_scene:
        last_warp_ms = -100000
        warp(scene, int(step.get("room", 0)) if step.get("room") != null else 0, 0)
        open_settle = 90
        open_retry = true
        print("gcrip opening: ", id, " - warping to ", scene)
        return          # arrive first; the next tick triggers the step
    var trig = step.get("trigger", {})
    var kind := str(trig.get("kind", "")) if trig is Dictionary else ""
    if step.get("look") is Dictionary:
        kind = "look"
    elif step.get("near") is Dictionary:
        kind = "near"
    elif step.get("object") is Dictionary:
        kind = "object"
    print("gcrip opening: ", id, " by ", kind)
    var lk := player()
    match kind:
        "talk":
            var who := str(step.get("actor", ""))
            if who == "" or _find_actor(who) == null:
                print("gcrip opening: ", id, " - no ", who, " placed here")
                return
            story_talk(who)
        "object":
            var obj: Dictionary = step["object"]
            var opos := story_object_pos(str(obj.get("actor", "")))
            if opos == STORY_OBJ_NOWHERE or lk == null:
                print("gcrip opening: ", id, " - no ", obj.get("actor", "?"), " placed here")
                return
            give_item(str(obj.get("item", "")))
            var orad := float(obj.get("radius", 0.0))
            if orad > 0.0:
                lk.global_position = opos + Vector3(0, 5, maxf(orad * 0.5, 40.0))
            story_object_tick()
        "near":
            var near: Dictionary = step["near"]
            var n := _find_actor(str(near.get("actor", "")))
            if n == null or lk == null:
                print("gcrip opening: ", id, " - no ", near.get("actor", "?"), " placed here")
                return
            lk.global_position = n.global_position + Vector3(0, 5, 60)
            story_npc_tick()      # check now: Link may not stay put for the next sweep
        "look":
            var look: Dictionary = step["look"]
            var t := _find_actor(str(look.get("actor", "")))
            if t == null or lk == null:
                print("gcrip opening: ", id, " - no ", look.get("actor", "?"), " placed here")
                return
            give_item("telescope")
            var eye: Vector3 = lk.global_position + Vector3(0, 105.0, 0)
            var to: Vector3 = t.global_position + Vector3(0, float(look.get("y", 0.0)), 0) - eye
            telescope_look(eye, to.normalized())
        "conduct":
            give_item("windwaker")
            var ct := conduct_pose(step)
            if ct.is_empty() or lk == null:
                print("gcrip opening: ", id, " - no MknjD tablet placed here")
                return
            conduct_play(lk, int(ct["song"]))
        "spawn", "tag", "room_enter", _:
            var ev := sfield(step, "event")
            if ev != "" and events.has(ev):
                run_event(ev)
            else:
                story_event_done(id if ev == "" else ev)

func _hitsw_report() -> void:
    var sws := get_tree().get_nodes_in_group("hit_switch")
    print("gcrip hit_switch: ", sws.size(), " in ", current_stage_key(),
        "; striking each with '", hitsw_test, "'")
    var by_need := {}
    for w in sws:
        var nd := str(w.get("needs"))
        by_need[nd] = int(by_need.get(nd, 0)) + 1
    print("gcrip hit_switch: by accepted attack ", by_need)
    var done := 0
    for w in sws:
        w.call("take_hit", 1, (w as Node3D).global_position + Vector3(0, 0, 100), hitsw_test)
        if bool(w.get("thrown")):
            done += 1
    print("gcrip hit_switch: ", done, " of ", sws.size(), " reacted to '", hitsw_test,
        "'; switches now ", (save.get("switches", {}) as Dictionary).size())
    get_tree().quit()

func _dungeon_report() -> void:
    var doors: Array = get_tree().get_nodes_in_group("door")
    var locked: Array = doors.filter(func(d): return int(d.get("lock")) != 0)
    print("gcrip dungeon: ", current_stage_key(), " slot ", dungeon_slot(),
        " key counter shown ", dungeon_shows_keys())
    print("gcrip dungeon: ", doors.size(), " doors placed, ", locked.size(), " of them locked")
    var kinds := ["none", "small key", "big key", "room clear"]
    for d in locked:
        print("gcrip dungeon:   ", d.get("actor"), " type ", d.get("dtype"), " -> ",
            kinds[int(d.get("lock"))], " front room ", d.get("front_room"),
            " switch ", d.get("swbit"), " warp ", "paired" if d.get("warp") != null else "NONE")
    var lk := player()
    # a small-key door with no key, then with one
    for d in locked:
        if int(d.get("lock")) != 1:
            continue
        if lk:
            lk.global_position = (d as Node3D).global_position + Vector3(0, 5, 100)
        print("gcrip dungeon: with 0 keys -> prompt '", d.call("interact_prompt", lk), "'")
        d.call("interact", lk)
        print("gcrip dungeon:   opened? ", d.get("opened"))
        add_key(1)
        print("gcrip dungeon: with 1 key -> prompt '", d.call("interact_prompt", lk), "'")
        d.call("interact", lk)
        print("gcrip dungeon:   opened? ", d.get("opened"), " keys left ", key_count())
        break
    # and a Big Key door, which must spend nothing
    for d in locked:
        if int(d.get("lock")) != 2:
            continue
        if lk:
            lk.global_position = (d as Node3D).global_position + Vector3(0, 5, 100)
        print("gcrip dungeon: big-key door without it -> '", d.call("interact_prompt", lk), "'")
        d.call("interact", lk)
        var before := key_count()
        give_dungeon_item(DUNGEON_BIG_KEY)
        d.call("interact", lk)
        print("gcrip dungeon:   opened? ", d.get("opened"), " keys ", before, " -> ",
            key_count(), " (a big-key door must spend none)")
        break
    print("gcrip dungeon: block now ", save.get("dungeon", {}))
    get_tree().quit()

func _salvage_test() -> void:
    give_item("rope")
    # put the world into the state this kind needs, the way real play would have by then:
    # kind 4 wants night, kind 6 the full moon's night, kind 2 the switch a Warship drops
    match salvage_test:
        4:
            save["day_time"] = 300.0
        6:
            save["day"] = 0
            save["day_time"] = 300.0
        2:
            for sp0 in get_tree().get_nodes_in_group("salvage"):
                if int(sp0.get("kind")) == 2:
                    set_switch(int(sp0.get("room")), int(sp0.get("switch_no")))
    var pts := get_tree().get_nodes_in_group("salvage")
    var want: Node3D = null
    var seen := {}
    for sp in pts:
        seen[int(sp.get("kind"))] = int(seen.get(int(sp.get("kind")), 0)) + 1
        if int(sp.get("kind")) == salvage_test and want == null and sp.call("available"):
            want = sp
    print("gcrip salvage: ", pts.size(), " points here by kind ", seen,
        " | this file's candidate = ", random_salvage_point())
    if want == null:
        print("gcrip salvage: no AVAILABLE kind-", salvage_test, " point in this stage")
        get_tree().quit()
        return
    var at: Vector3 = want.global_position
    print("gcrip salvage: working the crane over a kind-", salvage_test, " point at ",
        at.round(), " ring ", want.get("ring"), " depth ", want.get("depth"),
        " type ", want.get("type"), " item 0x%02X" % int(want.get("item_no")))
    var got := try_salvage(at)
    print("gcrip salvage: result ", got)
    print("gcrip salvage: still available? ", want.call("available"),
        " | collect_map ", save.get("collect_map", {}), " ocean ", save.get("ocean", {}))
    get_tree().quit()

func _island_prepare() -> void:
    # arrivalTerms()/otherCheck() bits have to be up before the stage picks a layer - the
    # Windfall volume is placed only on layers 2 and 3, the endless-night dressing
    match island_test:
        4:
            set_event_bit(0x0A02)
        7:
            set_event_bit(0x0A02)
            give_item("bomb")
        5:
            set_event_bit(0x1608)
        6:
            set_event_bit(0x1604)

func _island_test_begin() -> void:
    var cs := get_tree().current_scene
    var lk := player()
    if cs == null or lk == null:
        print("gcrip island: no scene / player")
        get_tree().quit()
        return
    for c in cs.get_children():
        if not c.name.begins_with("TagIsl_") or int(c.get("type")) != island_test:
            continue
        lk.global_position = (c as Node3D).global_position + Vector3(0, 5, 0)
        lk.velocity = Vector3.ZERO
        print("gcrip island: standing in TagIsl type ", island_test, " at ",
            (c as Node3D).global_position.round(), " radius ", c.get("radius"),
            " -> expecting ", c.call("event_name"))
        return
    print("gcrip island: no TagIsl of type ", island_test, " on this stage's current layer")
    get_tree().quit()

func _timer_test_begin() -> void:
    # stand in for the fire/ice arrow: raise the sea-side switch this island waits on
    for step in story.get("steps", []):
        var clock = step.get("timer")
        if not (clock is Dictionary) or not bool(clock.get("start", false)):
            continue
        if sfield(step, "id") != timer_test:
            continue
        var room := int(clock.get("room", 0))
        var sw := int(clock.get("switch", -1))
        print("gcrip timer: raising switch ", sw, " in room ", room, " of ",
            current_stage_key(), " (the fire/ice arrow's job)")
        set_switch(room, sw)
        story_timer_tick(0.0)
        if not story_timer_running():
            print("gcrip timer: the clock did not start")
            get_tree().quit()
            return
        # which chest ends it, so --timer=<step>:win can open the right one
        for other in story.get("steps", []):
            var b = other.get("timer")
            if b is Dictionary and bool(b.get("beaten", false)) \
                    and str(b.get("cave_stage", "")) == str(clock.get("cave_stage", "")):
                timer_info["tbox_win"] = int(b.get("tbox", -1))
        var cave := str(clock.get("cave_stage", ""))
        if (timer_win or timer_lose) and stage_data.has(cave):
            print("gcrip timer: warping into ", cave)
            last_warp_ms = -100000
            warp(cave, 0, 0)
        else:
            # let it expire where Link stands: 300 s at 30 fps is 9000 frames, so wind it down
            timer_left = 3.0
            print("gcrip timer: winding the clock down to 3 s to watch it expire")
        return
    print("gcrip timer: no start step called ", timer_test)
    get_tree().quit()

func _hit_prepare() -> void:
    # the wall only exists on the endless-night layers, so its bits have to be up before the
    # stage picks a layer - this runs deferred ahead of the --stage warp
    for st in story.get("steps", []):
        if not (st.get("hit") is Dictionary) or story_done(str(st.get("id", ""))):
            continue
        for b in st.get("requires_bits", []):
            var bid := _bit_value(b)
            if bid != 0 and not event_bit(bid):
                set_event_bit(bid)
                print("gcrip hit: raised ", b, " for ", st.get("id", "?"))
        _hit_prepare_layer(st)

func _hit_prepare_layer(step: Dictionary) -> void:
    # A step's requires_bits are what the STEP waits on.  Which story layer the object stands
    # on is decided separately (d_com_inf_game.cpp getLayerNo), and real play satisfies that
    # rule chapters earlier - Outset room 44 needs 0x0520, set when Link is launched at the
    # Forsaken Fortress.  Find the rule that yields a layer this actor is actually placed on
    # and raise its bits, so the harness stands in the story state the placement belongs to.
    var hit: Dictionary = step.get("hit", {})
    var who := str(hit.get("actor", ""))
    var base := sfield(step, "stage")
    if who == "" or base == "":
        return
    var want: Dictionary = {}       # layers this actor is placed on, in this stage
    var room := -1
    for key in [base, "%s_r%d" % [base, int(hit.get("room", -1))]]:
        for rec in (stage_data.get(key, {}) as Dictionary).get("logic", []):
            if str(rec.get("actor", "")) != who:
                continue
            if hit.get("room") != null and int(rec.get("room", -1)) != int(hit["room"]):
                continue
            want[int(rec.get("layer", -1))] = true
            room = int(rec.get("room", -1))
    if want.is_empty() or want.has(-1):
        return                      # placed unconditionally, or not placed at all
    for rule in layers.get("rules", []):
        if str(rule.get("stage", "")) != base:
            continue
        var r = rule.get("room")
        if r != null and room >= 0 and int(r) != room:
            continue
        if not want.has(int(rule.get("layer_night" if night else "layer_day", -99))):
            continue
        for t in rule.get("tests", []):
            if bool(t[1]) and not event_bit(int(t[0])):
                set_event_bit(int(t[0]))
                print("gcrip hit: raised 0x%04X for the layer rule that places %s"
                    % [int(t[0]), who])
        return
    print("gcrip hit: no layer rule for ", base, " room ", room, " yields ", want.keys(),
        " (night=", night, ")")

func _hit_objects() -> Array:
    var out: Array = []
    var cs := get_tree().current_scene
    if cs == null:
        return out
    for n in cs.get_children():
        if n is StaticBody3D and n.has_method("take_hit") and n.has_method("setup_hit"):
            out.append(n)
    return out

func _hit_tick() -> void:
    var objs := _hit_objects()
    if event_frames == 40:
        print("gcrip hit: ", objs.size(), " breakable story objects placed in ",
            current_stage_key(), " (layer ", story_layer(current_stage_key(), 44), ")")
        for o in objs:
            print("gcrip hit:   ", o.name, " at ", (o as Node3D).global_position.round(),
                " events ", o.get("events"), " min_damage ", o.get("min_damage"))
        if objs.is_empty():
            print("gcrip hit: nothing to strike")
            get_tree().quit()
            return
    var standing := 0
    for o in objs:
        if bool(o.get("broken")):
            continue
        standing += 1
        var dmg := maxi(int(o.get("min_damage")), 1)
        var lk := player()
        if lk:
            lk.global_position = (o as Node3D).global_position + Vector3(0, 5, 300)
        o.take_hit(dmg, lk.global_position if lk else Vector3.ZERO)
        hit_struck += 1
        print("gcrip hit: struck ", o.name, " for ", dmg, " (blow ", hit_struck, ", stage ",
            o.get("stage_i"), ")")
    if standing == 0:
        var done: Array = (save.get("story_done", {}) as Dictionary).keys()
        print("gcrip hit: all broken after ", hit_struck, " blows; story done ", done,
            " hit_log ", hit_log)
        get_tree().quit()

func _object_tick() -> bool:
    # the harness for a step a placed object orders itself: raise its bits, stand Link where the
    # predicate wants him, hand him what it wants, then poll once.  False = try again later
    # (the stage's arrival camera can still be up when the first attempt lands).
    if event_running or cutscene_running() or dialog_open:
        return false
    var step: Dictionary = {}
    for st in story.get("steps", []):
        if st.get("object") is Dictionary and not story_done(str(st.get("id", ""))) \
                and str(st.get("stage", "")) == current_stage_key().split("_r")[0]:
            step = st
            break
    if step.is_empty():
        print("gcrip object: no object-ordered step is waiting in this stage")
        get_tree().quit()
        return true
    for b in step.get("requires_bits", []):
        var bid := _bit_value(b)
        if bid != 0 and not event_bit(bid):
            set_event_bit(bid)
    var obj: Dictionary = step["object"]
    var pos := story_object_pos(str(obj.get("actor", "")))
    if pos == STORY_OBJ_NOWHERE:
        print("gcrip object: no ", obj.get("actor", "?"), " placed in this stage")
        get_tree().quit()
        return true
    var lk := player()
    if lk == null:
        print("gcrip object: no player")
        get_tree().quit()
        return true
    give_item(str(obj.get("item", "")))
    var sw = obj.get("switch")
    if sw != null:
        set_switch(int(obj.get("room", 0)), int(sw))
    var near_r := float(obj.get("radius", 0.0))
    var far_r := float(obj.get("min_radius", 0.0))
    if far_r > 0.0:
        lk.global_position = pos + Vector3(0, 5, far_r + 200.0)
    elif near_r > 0.0:
        lk.global_position = pos + Vector3(0, 5, maxf(near_r * 0.5, 40.0))
    print("gcrip object: ", step.get("id", "?"), " - ", obj.get("actor", "?"), " at ",
          pos.round(), ", Link ", round(pos.distance_to(lk.global_position)), " units off")
    if bool(obj.get("swing", false)):
        print("gcrip object: this step also wants a sword swing - headless cannot fake one")
    story_object_tick()
    if not story_done(str(step.get("id", ""))):
        print("gcrip object: the predicate did not take - step blocked")
    return true

func _near_tick() -> void:
    var step: Dictionary = {}
    for st in story.get("steps", []):
        if st.get("near") is Dictionary and not story_done(str(st.get("id", ""))) \
                and str(st.get("stage", "")) == current_stage_key().split("_r")[0]:
            step = st
            break
    if step.is_empty():
        print("gcrip near: no NPC-ordered step is waiting in this stage")
        get_tree().quit()
        return
    for b in step.get("requires_bits", []):
        var id := _bit_value(b)
        if id != 0 and not event_bit(id):
            set_event_bit(id)
    var near: Dictionary = step["near"]
    var who := _find_actor(str(near.get("actor", "")))
    var lk := player()
    if who == null or lk == null:
        print("gcrip near: no ", near.get("actor", "?"), " in this stage")
        get_tree().quit()
        return
    lk.global_position = who.global_position + Vector3(0, 5, maxf(float(near.get("radius", 0.0)) * 0.5, 60.0))
    print("gcrip near: ", step.get("id", "?"), " - Link set ",
          round(lk.global_position.distance_to(who.global_position)), " units from ",
          near.get("actor", "?"))

func _scope_tick() -> void:
    # stand where the step expects, hand over the Telescope, and look straight at the target
    give_item("telescope")
    var step: Dictionary = {}
    for st in story.get("steps", []):
        if st.get("look") is Dictionary and not story_done(str(st.get("id", ""))):
            step = st
            break
    if step.is_empty():
        print("gcrip scope: no story step is waiting on a telescope look")
        get_tree().quit()
        return
    var look: Dictionary = step["look"]
    for b in step.get("requires_bits", []):
        var id := _bit_value(b)
        if id != 0 and not event_bit(id):
            set_event_bit(id)      # the harness starts from the step, not from the whole opening
    var target := _find_actor(str(look.get("actor", "")))
    var lk := player()
    if target == null or lk == null:
        print("gcrip scope: no ", look.get("actor", "?"), " in this stage")
        get_tree().quit()
        return
    var eye: Vector3 = lk.global_position + Vector3(0, 105.0, 0)
    var to: Vector3 = target.global_position + Vector3(0, float(look.get("y", 0.0)), 0) - eye
    print("gcrip scope: ", step.get("id", "?"), " target ", look.get("actor", "?"), " at ",
          target.global_position.round(), " ", round(to.length()), " units away")
    if not telescope_look(eye, to.normalized()):
        print("gcrip scope: the look did not take - step blocked")
        get_tree().quit()

func _dlg_peek(ids: Array) -> String:
    if ids.is_empty():
        return "(nothing)"
    var t := str(messages.get(int(ids[0]), "?")).replace(String.chr(10), " ")
    return t.substr(0, 64)

func _dialogue_report() -> void:
    # every villager, at every story state of the opening: first talk, then a repeat talk
    var who: Array = ["Ba1", "Ls1", "Ji1", "Aj1", "Ko1", "Ko2", "Ob1", "Yw1", "Ym1", "Bm1"]
    for st in DLG_STATES:
        print("--- ", str(st[0]), " ---")
        for actor in who:
            save = {"items": {}}
            for b in st[1]:
                set_event_bit(int(b))
            for it in st[2]:
                (save["items"] as Dictionary)[str(it)] = true
            _npc_spawn_bits(str(actor))
            var a: Array = npc_messages(str(actor))
            var b2: Array = npc_messages(str(actor))
            print("  %-4s %s then %s  |  %s" % [actor, str(a), str(b2), _dlg_peek(a)])

func _process(delta: float) -> void:
    _arrival_guard()
    clock_tick(delta)
    if clock_test:
        _clock_tick()
        return
    if control_stick_frames > 0:
        control_stick_frames -= 1
        if control_stick_frames == 0:
            control_stick = Vector2.ZERO
    if not _timer_eject.is_empty() and not (event_running or cutscene_running() or dialog_open):
        var go: Array = _timer_eject
        _timer_eject = []
        # setNextStage is unconditional in the real actor: this is a scripted story warp, not
        # the player walking back through a door, so the anti-bounce guard must not eat it
        last_warp_ms = -100000
        warp("sea", int(go[0]), int(go[1]))
    story_tick += 1
    if story_tick % 15 == 0:
        story_npc_tick()
        story_timer_tick(15.0 / 30.0)
        story_bits_tick()
        conduct_tick()
        story_object_tick()
    if dialogue_test:
        event_frames += 1
        if event_frames == 20:
            _dialogue_report()
            get_tree().quit()
        return
    if shot_actor != "":
        _shot_tick()
    if defeat_test != "":
        event_frames += 1
        if event_frames == 40:
            var parts := defeat_test.split(":")
            var before: int = (save.get("story_done", {}) as Dictionary).keys().size()
            if parts[0] == "room":
                print("gcrip defeat: clearing room ", parts[1])
                story_room_cleared(int(parts[1]))
            else:
                var is_boss: bool = parts.size() > 1 and parts[1] == "boss"
                print("gcrip defeat: ", parts[0], " dies (boss=", is_boss, ")")
                story_enemy_defeated(parts[0], is_boss)
            var after: Array = (save.get("story_done", {}) as Dictionary).keys()
            print("gcrip defeat: story steps done ", before, " -> ", after.size(),
                  " ", after.slice(maxi(after.size() - 3, 0)))
            print("gcrip defeat: boss_dead ", save.get("boss_dead", {}))
        elif event_frames > 300:
            get_tree().quit()
    if hitsw_test != "":
        event_frames += 1
        if event_frames == 40:
            _hitsw_report()
        elif event_frames > 300:
            get_tree().quit()
    if dungeon_test:
        event_frames += 1
        if event_frames == 40:
            _dungeon_report()
        elif event_frames > 200:
            get_tree().quit()
    if salvage_test >= 0:
        event_frames += 1
        if event_frames == 40:
            _salvage_test()
        elif event_frames > 400:
            get_tree().quit()
    if island_test >= 0:
        event_frames += 1
        if event_frames == 30:
            _island_test_begin()
        elif event_frames > 30 and event_frames % 60 == 0:
            var cs := get_tree().current_scene
            var tg: Node = null
            if cs:
                for c in cs.get_children():
                    if c.name.begins_with("TagIsl_") and int(c.get("type")) == island_test:
                        tg = c
            print("gcrip island: f", event_frames, " event=", event_running, " cut=",
                cutscene_running(), " fired=", tg.get("fired") if tg else "?",
                " done=", (save.get("story_done", {}) as Dictionary).keys())
            if event_frames > 900 or (tg and bool(tg.get("fired")) and not event_running
                    and not cutscene_running()):
                print("gcrip island: done")
                get_tree().quit()
    if timer_test != "":
        event_frames += 1
        if event_frames == 30:
            _timer_test_begin()
        elif event_frames > 30 and event_frames % 30 == 0:
            if story_timer_running():
                print("gcrip timer: %.0f s left, stage %s" % [timer_left, current_stage_key()])
                var in_cave := current_stage_key() == str(timer_info.get("cave_stage", ""))
                if timer_win and in_cave:
                    print("gcrip timer: opening the chest (tbox ", timer_info.get("tbox_win"), ")")
                    story_timer_beaten(int(timer_info.get("tbox_win", -1)))
                elif timer_lose and in_cave and timer_left > 5.0:
                    print("gcrip timer: inside the cave - winding down to watch the ejection")
                    timer_left = 2.0
            elif event_frames > 120:
                # the timeout branch orders TAG_VOLCANO first and only warps once it ends, so
                # do not call it finished while that is still in flight
                if not _timer_eject.is_empty() or event_running or cutscene_running():
                    timer_settle = 90     # a warp is deferred; do not read the stage yet
                    return
                if timer_settle > 0:
                    timer_settle -= 1
                    return
                print("gcrip timer: clock is stopped in ", current_stage_key(),
                    "; story done ", (save.get("story_done", {}) as Dictionary).keys())
                get_tree().quit()
        if event_frames > 4000:
            print("gcrip timer: done (timeout)")
            get_tree().quit()
    if hit_test:
        event_frames += 1
        if event_frames >= 40 and event_frames % 40 == 0 and not event_running \
                and not cutscene_running() and not dialog_open:
            _hit_tick()
        if event_frames > 2400:
            print("gcrip hit: done (timeout)")
            get_tree().quit()
    if models_test:
        _models_report()
        get_tree().quit()
        return
    if cuts_test:
        _cuts_tick()
    if doors_test:
        _doors_tick()
    if sweep_test:
        _sweep_tick()
    if opening_test:
        _opening_tick()
    if object_test:
        event_frames += 1
        if not object_fired and event_frames >= 40 and event_frames <= 200 and event_frames % 40 == 0:
            object_fired = _object_tick()
        elif event_frames > 40 and event_frames % 120 == 0:
            print("gcrip object: f%d event=%s cut=%s dialog=%s" % [
                event_frames, str(event_running), str(cutscene_running()), str(dialog_open)])
            if event_frames > 1800:
                print("gcrip object: done")
                get_tree().quit()
    if near_test:
        event_frames += 1
        if event_frames == 40:
            _near_tick()
        elif event_frames > 40 and event_frames % 120 == 0:
            print("gcrip near: f%d event=%s cut=%s dialog=%s" % [
                event_frames, str(event_running), str(cutscene_running()), str(dialog_open)])
            if event_frames > 1800:
                print("gcrip near: done")
                get_tree().quit()
    if scope_test:
        event_frames += 1
        if event_frames == 40:
            _scope_tick()
        elif event_frames > 40 and event_frames % 120 == 0:
            print("gcrip scope: f%d event=%s cut=%s dialog=%s" % [
                event_frames, str(event_running), str(cutscene_running()), str(dialog_open)])
            if event_frames > 1800:
                print("gcrip scope: done")
                get_tree().quit()
    if conduct_test:
        event_frames += 1
        if event_frames == 40:
            _conduct_tick()
        elif event_frames > 40 and event_frames % 120 == 0:
            print("gcrip conduct: f%d event=%s cut=%s dialog=%s" % [
                event_frames, str(event_running), str(cutscene_running()), str(dialog_open)])
            if event_frames > 1800:
                print("gcrip conduct: done")
                get_tree().quit()
    if conduct_test or newgame_test or event_test != "" or talk_test != "" or story_test or scope_test \
            or near_test or opening_test or sweep_test or doors_test or cuts_test or object_test:
        # tests have no player: advance text boxes directly (a synthesised action press raises
        # no InputEvent, so the box would never turn its page and the event would never end)
        auto_a += 1
        if dialog_open and auto_a % 12 == 0 and dialog != null:
            dialog.advance()
    if talk_test != "":
        event_frames += 1
        if event_frames == 40:
            var target: Node3D = null
            for grp in ["interact", "enemy"]:
                for n in get_tree().get_nodes_in_group(grp):
                    if is_instance_valid(n) and str(n.get("actor")) == talk_test:
                        target = n
                        break
            var lk := player()
            if target and lk:
                lk.global_position = target.global_position + Vector3(0, 5, 120)
                print("gcrip talk: found ", talk_test, " at ", target.global_position.round())
                target.interact(lk)
            else:
                print("gcrip talk: no ", talk_test, " in this stage")
                get_tree().quit()
        elif event_frames > 40 and event_frames % 60 == 0:
            print("gcrip talk: f%d event=%s cut=%s dialog=%s" % [
                event_frames, str(event_running), str(cutscene_running()), str(dialog_open)])
            if event_frames % 240 == 0 and not event_running and not dialog_open:
                # the first attempt can land while an arrival event still owns the scene
                for grp2 in ["interact", "enemy"]:
                    for n2 in get_tree().get_nodes_in_group(grp2):
                        if is_instance_valid(n2) and str(n2.get("actor")) == talk_test:
                            n2.interact(player())
                            break
            if event_frames > 3600:
                print("gcrip talk: done")
                get_tree().quit()
    if newgame_test:
        event_frames += 1
        if event_frames == 30:
            print("gcrip newgame: starting")
            new_game()
        elif event_frames in [200, 700, 1400, 2100]:
            var img := get_viewport().get_texture().get_image()
            img.save_png("user://open_%d.png" % event_frames)
        elif event_frames > 30 and event_frames % 90 == 0:
            var cs2 := get_tree().current_scene
            var cut2 := cutscene if cutscene_running() else null
            var link2 := player()
            print("gcrip newgame: f%d scene=%s cut=%s frame=%s link=%s" % [
                event_frames, str(cs2.name) if cs2 else "?", str(cut2 != null),
                str(cut2.frame) if cut2 else "-",
                str(link2.global_position.round()) if link2 else "?"])
            if event_frames > 2400:
                print("gcrip newgame: done")
                get_tree().quit()
    if event_test != "":
        event_frames += 1
        if event_frames == 40:
            print("gcrip evtest: running ", event_test, " have=", events.has(event_test))
            run_event(event_test)
        elif event_frames > 40 and event_frames % 60 == 0:
            var cam := get_viewport().get_camera_3d()
            var cs := cutscene if cutscene_running() else null
            print("gcrip evtest: f%d event=%s cut=%s frame=%s cam=%s fov=%.0f" % [
                event_frames, str(event_running), str(cs != null),
                str(cs.frame) if cs else "-", str(cam.global_position.round()) if cam else "?",
                cam.fov if cam else 0.0])
            if event_frames > 40 and not event_running and not cutscene_running():
                print("gcrip evtest: done")
                get_tree().quit()
            if event_frames > 1800:
                print("gcrip evtest: timeout")
                get_tree().quit()
    if menu_test != "":
        menu_frames += 1
        if menu_frames == 30:
            open_menu()
        elif menu_frames > 30 and menu_frames % 40 == 0 and menu != null:
            var img := get_viewport().get_texture().get_image()
            img.save_png("user://menu_%s.png" % str(menu.mode))
            var rows: int = (menu.list.item_count if menu.list else -1)
            print("gcrip menu: tab '", menu.mode, "' rows=", rows,
                  " first='", (menu.list.get_item_text(0) if rows > 0 else ""), "'")
            if str(menu.mode) == "game":
                print("gcrip menu: done")
                get_tree().quit()
                return
            menu.mode = {"stages": "events", "events": "story", "story": "game"}[str(menu.mode)]
            menu._fill()
    if story_test:
        story_frames += 1
        if story_frames % 40 == 0:
            var cs0 := get_tree().current_scene
            var stage := String(cs0.name) if cs0 else ""
            var states := story_states(stage)
            if story_idx >= 0 and story_idx < states.size():
                var rule: Dictionary = states[story_idx]
                var shown := 0
                var lvl := cs0.get_node_or_null("Level") if cs0 else null
                if lvl:
                    for n in lvl.find_children("*", "Node3D", true, false):
                        if (n as Node3D).visible:
                            shown += 1
                print("gcrip story: state %d tests %s -> layer %d, %d visible nodes" % [
                    story_idx, str(rule.get("tests", [])), story_layer(stage, 44), shown])
            story_idx += 1
            if story_idx >= states.size():
                print("gcrip story: done")
                get_tree().quit()
            else:
                for t in states[story_idx].get("tests", []):
                    if bool(t[1]):
                        set_event_bit(int(t[0]))
                    else:
                        clear_event_bit(int(t[0]))
                reload_stage()
    if door_test:
        door_frames += 1
        var cs := get_tree().current_scene
        if door_frames == 30 and cs:
            for n in cs.find_children("*", "Area3D", true, false):
                if n.get("dest_stage") == null:
                    continue
                var ok_dest: bool = door_want == "" or str(n.dest_stage) == door_want or String(cs.name) == door_want
                if ok_dest:
                    print("gcrip door: ", cs.name, " -> ", n.dest_stage, " room ", n.dest_room, " spawn ", n.dest_spawn)
                    last_warp_ms = -100000
                    warp(str(n.dest_stage), int(n.dest_room), int(n.dest_spawn))
                    break
        if door_frames == 200:
            var link := player()
            var cs2 := get_tree().current_scene
            if link and cs2:
                var space := (cs2 as Node3D).get_world_3d().direct_space_state
                var q := PhysicsRayQueryParameters3D.create(link.global_position + Vector3(0, 80, 0), link.global_position + Vector3(0, 80, 0) + Vector3(sin(float(link.get("facing"))), 0, cos(float(link.get("facing")))) * 120.0, 1)
                var blocked := not space.intersect_ray(q).is_empty()
                print("gcrip door: landed in ", cs2.name, " at ", link.global_position.round(), " ground=", ground_under(link.global_position), " wall_ahead=", blocked, " state=", link.get("state"))
            print("gcrip door: facing=", rad_to_deg(float(link.get("facing"))), " cam_yaw=", rad_to_deg(link.cam_yaw_angle()), " fwd=", Vector3(sin(float(link.get("facing"))), 0, cos(float(link.get("facing")))).round())
            Input.action_press("move_forward")   # then walk straight ahead for 2 s: still on a floor?
        if door_frames == 260:
            Input.action_release("move_forward")
            var link2 := player()
            if link2:
                print("gcrip door: after walking ahead ", link2.global_position.round(), " ground=", ground_under(link2.global_position), " state=", link2.get("state"))
            door_legs += 1
            if door_legs >= 4:
                get_tree().quit()
            else:
                door_frames = 0   # go back through the door and do it again
    autosave_frames += 1
    if autosave_frames >= 30 * 60 and not dialog_open and not event_running and not selftest and shot_actor == "" and not door_test and not story_test and menu_test == "" and event_test == "" and talk_test == "":
        autosave_frames = 0
        save_game("autosave")

func _shot_tick() -> void:
    shot_frames += 1
    var cs := get_tree().current_scene
    var cam := get_viewport().get_camera_3d()
    if cs == null or cam == null:
        return
    var target: Node3D = null
    for n in cs.find_children("A_" + shot_actor + "*", "", true, false):
        target = n
        break
    if target == null:
        if shot_frames > 120:
            print("gcrip shot: no actor ", shot_actor)
            get_tree().quit()
        return
    var link := player()
    if link:
        link.set_physics_process(false)
        link.visible = false
    var head := target.global_position + Vector3(0, 120.0, 0)
    var rig: Node3D = target.get_child(target.get_child_count() - 1) as Node3D
    var fwd := Vector3(sin(float(target.get("facing"))), 0.0, cos(float(target.get("facing"))))
    var side := 1.0 if shot_frames < 75 else -1.0
    cam.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
    if cam.get_parent():
        cam.get_parent().physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
    cam.global_position = head + fwd * 220.0 * side + Vector3(0, 30.0, 0)
    cam.look_at(head, Vector3.UP)
    cam.fov = 45.0
    cam.reset_physics_interpolation()
    if shot_frames == 60 or shot_frames == 105:
        var img := get_viewport().get_texture().get_image()
        var fn := "user://shot_%s.png" % ("front" if shot_frames == 60 else "back")
        img.save_png(fn)
        print("gcrip shot: saved ", fn, " for ", shot_actor, " at ", target.global_position.round(), " rig=", str(rig != null))
        if shot_frames == 105:
            get_tree().quit()

# ---- story layers (dzr ACT0..ACTb): which set of actors this room shows right now

# ---- the clock (src/d/d_kankyo.cpp)

func day_time() -> float:
    # dComIfGs_getTime(): the save's mTime, 0.0 .. 360.0
    return float(save.get("day_time", 0.0))

func set_day_time(t: float) -> void:
    save["day_time"] = fposmod(t, DAY_UNITS)
    _clock_after()

func day_number() -> int:
    # dComIfGs_getDate(); dKy_get_dayofweek() is this % 7 (d_kankyo.cpp:3570-3572)
    return int(save.get("day", 0))

func hour() -> int:
    # dKy_getdaytime_hour (d_kankyo.cpp:613-616)
    return int(day_time() / UNITS_PER_HOUR)

func minute() -> int:
    # dKy_getdaytime_minute (d_kankyo.cpp:618-623): the fraction of the hour, times 60
    return int(fposmod(day_time(), UNITS_PER_HOUR) * (60.0 / UNITS_PER_HOUR))

func clock_string() -> String:
    return "%02d:%02d" % [hour(), minute()]

func night_stop() -> bool:
    # dKy_checkEventNightStop (d_kankyo.cpp:3160-3167): during the endless-night chapter the
    # clock is pinned to night - envcolor_init even forces the time to 0.0 (d_kankyo.cpp:477).
    if not event_bit(NIGHT_STOP_BIT):
        return false
    # ... && !dComIfGs_isSymbol(dSymbol_NAYRU_e).  The three pearls are not modelled yet, so
    # the second half of the test reads a save flag nothing sets so far.
    return not bool((save.get("symbols", {}) as Dictionary).get("nayru", false))

func is_night() -> bool:
    # dKy_daynight_check (d_kankyo.cpp:625-632) plus the nightStop override getLayerNo
    # applies before it (d_com_inf_game.cpp:189-190)
    if night_stop():
        return true
    var h := hour()
    return h < DAY_START_HOUR or h >= NIGHT_START_HOUR

func clock_running() -> bool:
    # setDaytime only advances the clock outside events (d_kankyo.cpp:519-524), and the
    # endless night freezes it entirely
    if night_stop():
        return false
    if event_running or dialog_open or cutscene_running():
        return false
    return not get_tree().paused

func clock_tick(delta: float) -> void:
    # --clock steps the clock by hand; otherwise it follows real time at the game's rate
    # (mTimeAdv per frame at 30 fps = 0.6 units of game time per real second)
    if clock_test or not clock_running():
        return
    clock_advance(delta * TIME_ADV * GAME_FPS)

func clock_advance(units: float) -> void:
    # setDaytime (d_kankyo.cpp:524-530): add, and each time the total passes 360 the date
    # goes up by one and dKankyo_DayProc() runs.  (The game snaps mCurTime to 0.0 on the
    # rollover; keeping the remainder only matters when something jumps the clock by hours.)
    var t := day_time() + units
    while t >= DAY_UNITS:
        t -= DAY_UNITS
        save["day"] = day_number() + 1
        day_proc(day_number())
    save["day_time"] = t
    _clock_after()

# dKankyo_DayProc (src/d/d_kankyo_dayproc.inc) is a long list of "another day has passed"
# save edits - letters arriving, shop stock resetting, counters ticking up.  Only the rules
# whose state this remake actually models live here; each is {requires: bits that must all
# be set, sets: bits to raise, why: what it means}.  Hang new ones off day_passed instead
# if they need more than a bit test.
const DAY_RULES := [
    # d_kankyo_dayproc.inc:101-102 -- if (isEventBit(UNK_2F01)) onEventBit(UNK_3080).
    # 0x2F01 is raised when a figurine is ordered from Carlov; a day later 0x3080 says the
    # sculpture is finished and waiting in the Nintendo Gallery.
    {"requires": [0x2F01], "sets": [0x3080],
     "why": "the Nintendo Gallery figurine (0x2F01) is carved -> 0x3080"},
]

func day_proc(day: int) -> void:
    for rule in DAY_RULES:
        var ok := true
        for b in rule.get("requires", []):
            if not event_bit(int(b)):
                ok = false
                break
        if not ok:
            continue
        for b in rule.get("sets", []):
            set_event_bit(int(b))
        print("gcrip clock: day ", day, " - ", str(rule.get("why", "")))
    day_passed.emit(day)

func _clock_after() -> void:
    # getLayerNo runs from layerLoader when a room is decoded (d_stage.cpp:2148-2150), so a
    # dusk / dawn crossing only shows on screen once the stage is rebuilt.
    var now: int = 1 if night else 0
    if now == _night_live:
        return
    if _night_live < 0:
        _night_live = now       # first look: whatever is loading already matches
        return
    if not clock_reload_on_flip or scripted():
        _night_live = now
        # nothing to do on screen: the next stage or room load reads the clock and picks the
        # right layer by itself, exactly as layerLoader does
        return
    if event_running or dialog_open or cutscene_running() or get_tree().paused:
        return                  # busy: try again on the next tick
    if get_tree().current_scene == null:
        return
    _night_live = now
    var word: String = "night" if now == 1 else "day"
    print("gcrip clock: ", clock_string(), " - ", word, " now; reloading the stage for its layer")
    reload_stage()

# ---- --clock: a whole day, headless

# stages whose layer the report follows: Outset and Forest Haven have day/night placements,
# Windfall carries the nightStop rule, Forsaken Fortress is time-independent, the Cafe Bar
# is a plain default-layer interior with a different night cast.
const CLOCK_STAGES := [["sea_r44", 44], ["sea_r11", 11], ["sea_r1", 1], ["Opub", -1],
                       ["A_mori", -1]]

func _clock_report(tag: String) -> void:
    var line := "gcrip clock: " + tag + " " + clock_string() + " night=" + str(night)
    for st in CLOCK_STAGES:
        line += "  " + str(st[0]) + "=" + str(story_layer(str(st[0]), int(st[1])))
    print(line)

func _clock_tick() -> void:
    clock_frames += 1
    if clock_frames == 1:
        print("gcrip clock: %.0f units per day, %.0f per hour, %.2f per frame at %.0f fps" % [
            DAY_UNITS, UNITS_PER_HOUR, TIME_ADV, GAME_FPS])
        print("gcrip clock: -> %.0f s of real play per in-game day, %.0f s per in-game hour" % [
            DAY_UNITS / (TIME_ADV * GAME_FPS), UNITS_PER_HOUR / (TIME_ADV * GAME_FPS)])
        save["day"] = 0
        save["day_time"] = 0.0
        save["event_flags"] = []      # a clean file: no story bit set anywhere
        _night_live = -1
        _clock_report("start")
        return
    if clock_step < 24:
        clock_step += 1
        clock_advance(UNITS_PER_HOUR)
        _clock_report("+%dh" % clock_step)
        return
    if clock_step == 24:
        clock_step += 1
        print("gcrip clock: a whole day rolled over: day = ", day_number())
        print("gcrip clock: 0x3080 before a figurine is ordered = ", event_bit(0x3080))
        set_event_bit(0x2F01)
        clock_advance(DAY_UNITS)
        print("gcrip clock: 0x2F01 set, one more day passed -> day = ", day_number(),
              ", 0x3080 = ", event_bit(0x3080))
        return
    if clock_step == 25:
        clock_step += 1
        set_event_bit(NIGHT_STOP_BIT)
        set_day_time(12.0 * UNITS_PER_HOUR)
        print("gcrip clock: ENDLESS_NIGHT 0x0A02 set, clock at noon - night_stop=",
              night_stop(), " clock_running=", clock_running())
        _clock_report("noon+EN")
        clear_event_bit(NIGHT_STOP_BIT)
        _clock_report("noon")
        return
    print("gcrip clock: done")
    get_tree().quit()

func story_layer(stage: String, room: int) -> int:
    # normalised rules from the decomp (layers.json): the first rule for this stage / room
    # whose event-bit tests all hold wins; `night` - the clock, above - picks the variant
    var base := stage.split("_r")[0]
    for rule in layers.get("rules", []):
        if str(rule.get("stage", "")) != base:
            continue
        var r = rule.get("room")
        if r != null and int(r) != room:
            continue
        # a rule whose condition also calls nightStop() (Windfall, d_com_inf_game.cpp:204-205)
        # belongs to the endless night alone - its bit tests on their own would fire it every
        # single day and pin the island to layer 3
        if str(rule.get("extra", "")).find("nightStop") >= 0 and not night_stop():
            continue
        var ok := true
        for t in rule.get("tests", []):
            if event_bit(int(t[0])) != bool(t[1]):
                ok = false
                break
        if ok:
            return int(rule.get("layer_night" if night else "layer_day", 0))
    return int(layers.get("default_night" if night else "default_day", 0))

# dSv_event_flag_c: u8 mFlags[0x100]; an "event bit" id packs the byte index in its high
# byte and the MASK (not a bit index) in its low byte - isEventBit(0x0520) = mFlags[5] & 0x20.
# Some ids use multi-bit masks as packed registers, so keep the real byte array.
const EVENT_FLAG_BYTES := 0x100

func event_flags() -> Array:
    var f: Array = save.get("event_flags", [])
    if f.size() != EVENT_FLAG_BYTES:
        f = []
        f.resize(EVENT_FLAG_BYTES)
        f.fill(0)
        save["event_flags"] = f
    return f

# ---- inventory (only the opening's quest items; the decomp gates these on collect[] bits)

const ITEM_NAMES := {"sword": "Hero's Sword", "shield": "Hero's Shield",
                     "telescope": "Telescope", "clothes": "Hero's Clothes",
                     "windwaker": "Wind Waker",
                     "leaf": "Deku Leaf", "boomerang": "Boomerang"}
const COLLECT_ITEMS := {"collect[0] bit0": "sword", "collect[1] bit0": "shield"}

func has_item(name: String) -> bool:
    return bool((save.get("items", {}) as Dictionary).get(name, false))

func give_item(name: String) -> void:
    if name == "" or has_item(name):
        return
    var items: Dictionary = save.get("items", {})
    items[name] = true
    save["items"] = items
    print("gcrip: got the ", ITEM_NAMES.get(name, name))
    save_game("item")

func event_bit(id: int) -> bool:
    var mask := id & 0xFF
    if mask == 0:
        return false
    return (int(event_flags()[(id >> 8) & 0xFF]) & mask) == mask

func set_event_bit(id: int) -> void:
    var f := event_flags()
    var i := (id >> 8) & 0xFF
    f[i] = int(f[i]) | (id & 0xFF)
    save["event_flags"] = f

func event_reg(id: int) -> int:
    # An event REGISTER shares the very same 256-byte array as the event bits; the low byte of
    # the id is a MASK, not a bit index, and neither accessor shifts.  So a 0xFF-mask register
    # is a plain 0-255 byte of the save (src/d/d_save.cpp:1201-1210).  Minigame records, the
    # figurine collection and the Joy Pendant count all live here - modelling the flags as named
    # booleans instead of a raw byte array would silently corrupt every one of them.
    return int(event_flags()[(id >> 8) & 0xFF]) & (id & 0xFF)

func set_event_reg(id: int, value: int) -> void:
    var f := event_flags()
    var i := (id >> 8) & 0xFF
    var mask := id & 0xFF
    f[i] = (int(f[i]) & ~mask) | (value & mask)
    save["event_flags"] = f

func _bit_value(b) -> int:
    # story.json writes bits as "0x3510"; accept plain numbers too
    if b is float or b is int:
        return int(b)
    var t := str(b).strip_edges()
    return t.hex_to_int() if t.begins_with("0x") else int(t)

func _story_bits_ok(step: Dictionary) -> bool:
    # every requirement must be an event bit we can test, and it must be set
    var sets: Array = step.get("sets_bits", [])
    for b in step.get("requires_bits", []):
        var t := str(b).strip_edges()
        if COLLECT_ITEMS.has(t):
            if not has_item(str(COLLECT_ITEMS[t])):
                return false
            continue
        if not t.begins_with("0x"):
            return false          # gated on a counter we do not model yet
        if sets.has(b) or sets.has(t):
            # A step that requires a bit it also SETS is not gated on anything - it is the
            # mined way of writing "while this has not happened yet".  Ganon's Tower does it
            # because the four trials may be cleared in any order, so no trial names another;
            # Hyrule's barrier does it because 0x2C02 is what the break RAISES.  Read as a
            # hard requirement it is a deadlock: only this step can produce the bit.
            continue
        if not event_bit(_bit_value(t)):
            return false
    return true

func story_done(id: String) -> bool:
    var done: Dictionary = save.get("story_done", {})
    return done.has(id)

func _mark_story_done(id: String) -> void:
    var done: Dictionary = save.get("story_done", {})
    done[id] = true
    save["story_done"] = done

func story_talk(actor: String) -> bool:
    # Link talked to `actor`: run the next step of the mined opening graph that waits on
    # exactly that, if its event bits allow it. True when a step took over the conversation.
    if actor == "" or event_running or cutscene_running():
        return false
    var here := current_stage_key()
    for step in story.get("steps", []):
        var trig: Dictionary = step.get("trigger", {})
        if str(trig.get("kind", "")) != "talk":
            continue
        if str(step.get("actor", "")) != actor:
            continue
        var st := str(step.get("stage", ""))
        if st != "" and st != here:
            continue
        var id := sfield(step, "id")
        if story_done(id) or not _story_bits_ok(step):
            continue
        _mark_story_done(id)
        var ev := sfield(step, "event")
        if ev != "" and events.has(ev):
            print("gcrip story: ", actor, " -> ", id, " (event ", ev, ")")
            if run_event(ev):
                return true
        # no event of its own: the step just advances the story
        print("gcrip story: ", actor, " -> ", id)
        story_event_done(id)
        return false
    return false

func sfield(step: Dictionary, key: String) -> String:
    # the mined graph leaves event / stb null on the steps that have none, and str(null) is
    # the string "<null>" - which would then match EVERY such step at once
    var v = step.get(key)
    return "" if v == null else str(v)

func story_event_done(name: String) -> void:
    # a step of the mined opening graph finished: raise the event bits it is known to set
    if name == "":
        return
    var raised: Array = []
    for step in story.get("steps", []):
        var ev := sfield(step, "event")
        var stb := sfield(step, "stb")
        if ev != name and stb != name and (stb == "" or stb != name + ".stb")                 and sfield(step, "id") != name:
            continue
        _mark_story_done(str(step.get("id", "")))
        for b in step.get("sets_bits", []):
            var id := _bit_value(b)
            if id != 0 and not event_bit(id):
                set_event_bit(id)
                raised.append("0x%04X" % id)
        give_item(sfield(step, "item_key"))
    if not raised.is_empty():
        save_game("story")
        print("gcrip story: '", name, "' set ", ", ".join(raised))
    _story_chain_after(name)

func _story_chain_after(name: String) -> void:
    # the step after this one may be reached by the game calling setNextStage: do that warp,
    # which lands on a spawn whose params auto-play the next event (Grandma's tale -> tale.stb)
    var steps: Array = story.get("steps", [])
    var idx := -1
    for i in steps.size():
        var st: Dictionary = steps[i]
        if str(st.get("id", "")) == name or str(st.get("event", "")) == name \
                or str(st.get("stb", "")) == name or str(st.get("stb", "")) == name + ".stb":
            idx = i
            break
    if idx < 0 or idx + 1 >= steps.size():
        return
    var nxt: Dictionary = steps[idx + 1]
    var w = nxt.get("warp")
    if not (w is Dictionary):
        return
    if story_done(str(nxt.get("id", ""))) or not _story_bits_ok(nxt):
        return
    _mark_story_done(str(nxt.get("id", "")))
    var stage := str(w.get("stage", ""))
    var scene := stage
    if not stage_data.has(scene):
        return
    print("gcrip story: chaining to ", scene, " spawn ", int(w.get("spawn", 0)))
    last_warp_ms = -100000
    warp(scene, int(w.get("room", 0)) if w.get("room") != null else 0, int(w.get("spawn", 0)))

func warp_objects(stage: String) -> Array:
    # The mined "warp" steps of this stage, grouped into one entry per placed object. Several
    # steps can describe the SAME object taking different branches, so they are collected
    # under one (stage, actor) and the branch is chosen when Link steps in.
    var out: Array = []
    var index: Dictionary = {}
    for step in story.get("steps", []):
        var w = step.get("warp_object")
        if not (w is Dictionary):
            continue
        if str(w.get("stage", "")) != stage:
            continue
        var actor := str(w.get("actor", ""))
        var obj: Dictionary
        if index.has(actor):
            obj = out[int(index[actor])]
        else:
            index[actor] = out.size()
            obj = {"actor": actor, "stage": stage, "room": -1, "pos": null, "branches": []}
            out.append(obj)
        if int(obj["room"]) < 0 and w.get("room") != null:
            obj["room"] = int(w.get("room"))
        var pos = w.get("pos")
        if obj["pos"] == null and pos is Array:
            var pa: Array = pos
            if pa.size() >= 3:
                obj["pos"] = Vector3(float(pa[0]), float(pa[1]), float(pa[2]))
        var req: Array = []
        var raw = w.get("requires", [])
        if raw is Array:
            req = raw
        var branches: Array = obj["branches"]
        branches.append({
            "step": str(step.get("id", "")),
            "event": str(w.get("event", "")),
            "dest": w.get("dest", {}),
            "requires": req,
        })
    return out

func warp_branch(obj: Dictionary) -> Dictionary:
    # daWarpf_c::CreateInit: the same flower orders WARP_WIND while this dungeon's reward is
    # untaken and WARP_WIND_AFTER once it has been taken - checkEndDemo() reading the save
    # (event bit 0x2D10 for the Tower of the Gods, a held item for the other dungeons). The
    # mined branches carry that test as requires_bits, so the most specific branch the save
    # satisfies wins and the unconditional one is the fallback.
    var best: Dictionary = {}
    var best_score := -1
    var branches: Array = obj.get("branches", [])
    for b in branches:
        var req: Array = b.get("requires", [])
        if not _story_bits_ok({"requires_bits": req}):
            continue
        if req.size() > best_score:
            best_score = req.size()
            best = b
    return best

func story_states(stage: String) -> Array:
    # every layer rule that applies to this scene, in the decomp's order. A "sea_rNN" scene is
    # one island, so drop the rules that belong to the other islands' rooms.
    var base := stage.split("_r")[0]
    var room := -1
    var i := stage.rfind("_r")
    if i >= 0 and stage.substr(i + 2).is_valid_int():
        room = int(stage.substr(i + 2))
    var out: Array = []
    for rule in layers.get("rules", []):
        if str(rule.get("stage", "")) != base:
            continue
        var r = rule.get("room")
        if room >= 0 and r != null and int(r) != room:
            continue
        out.append(rule)
    return out

func apply_story_state(rule: Dictionary) -> void:
    # set / clear exactly the bits this rule tests, then reload the stage so the layer swaps
    for t in rule.get("tests", []):
        if bool(t[1]):
            set_event_bit(int(t[0]))
        else:
            clear_event_bit(int(t[0]))
    reload_stage()

func reload_stage() -> void:
    var cs := get_tree().current_scene
    if cs == null:
        return
    var link := player()
    var keep: Vector3 = link.global_position if link else Vector3.ZERO
    var st := String(cs.name)
    last_warp_ms = -100000
    pending = {"stage": st, "room": 0, "spawn": 0}
    get_tree().change_scene_to_file.call_deferred("res://scenes/%s.tscn" % st)
    _place_player.call_deferred()
    if keep != Vector3.ZERO:
        save["last_pos"] = [keep.x, keep.y, keep.z]

func clear_event_bit(id: int) -> void:
    var f := event_flags()
    var i := (id >> 8) & 0xFF
    f[i] = int(f[i]) & ~(id & 0xFF)
    save["event_flags"] = f

func is_switch(room: int, bit: int) -> bool:
    var sw: Dictionary = save.get("switches", {})
    return sw.has("%s/%d/%d" % [current_stage_key(), room, bit])

func set_switch(room: int, bit: int) -> void:
    var sw: Dictionary = save.get("switches", {})
    sw["%s/%d/%d" % [current_stage_key(), room, bit]] = true
    save["switches"] = sw

func clear_switch(room: int, bit: int) -> void:
    # the timed islands need this: when the countdown expires the sea-side VolTag turns its
    # switch back OFF, which is what makes GiceL re-freeze / daObjVolcano re-erupt
    var sw: Dictionary = save.get("switches", {})
    sw.erase("%s/%d/%d" % [current_stage_key(), room, bit])
    save["switches"] = sw

func current_stage_key() -> String:
    var cs := get_tree().current_scene
    return String(cs.name).split("_r")[0] if cs else ""

func load_events(stage: String) -> void:
    events = {}
    var f := FileAccess.open("res://events/%s.json" % stage, FileAccess.READ)
    if f == null:
        return
    var parsed = JSON.parse_string(f.get_as_text())
    if parsed is Array:
        for ev in parsed:
            events[str(ev.get("name", ""))] = ev
    var info: Dictionary = stage_data.get(stage, {})
    var off: Array = info.get("offset", [0, 0, 0])
    world_offset = Vector3(float(off[0]), float(off[1]), float(off[2]))

func run_event(name: String) -> bool:
    if event_running or not events.has(name):
        return false
    var scene := get_tree().current_scene
    if scene == null:
        return false
    event_runner = Node.new()
    event_runner.set_script(load("res://event_runner.gd"))
    event_runner.name = "Event_" + name
    scene.add_child(event_runner)
    event_runner.start(events[name])
    print("gcrip event: ", name)
    return true

var cutscene: Node = null

func play_cutscene(name: String, offset_pos: Vector3, offset_angy: float) -> bool:
    var scene := get_tree().current_scene
    if scene == null:
        return false
    if cutscene and is_instance_valid(cutscene):
        cutscene.abort()
    cutscene = Node.new()
    cutscene.set_script(load("res://cutscene.gd"))
    cutscene.name = "Cutscene_" + name
    scene.add_child(cutscene)
    if not cutscene.play(name, offset_pos, offset_angy):
        cutscene.queue_free()
        cutscene = null
        return false
    return true

func cutscene_running() -> bool:
    return cutscene != null and is_instance_valid(cutscene)

func set_event_cam(eye: Vector3, center: Vector3, fov: float) -> void:
    event_cam = {"eye": eye, "center": center, "fov": fov}

func clear_event_cam() -> void:
    event_cam = {}

func event_cam_eye() -> Vector3:
    if event_cam.has("eye"):
        return event_cam["eye"]
    var cam := get_viewport().get_camera_3d()
    return cam.global_position if cam else Vector3.ZERO

func event_cam_center() -> Vector3:
    if event_cam.has("center"):
        return event_cam["center"]
    var cam := get_viewport().get_camera_3d()
    return (cam.global_position - cam.global_transform.basis.z * 300.0) if cam else Vector3.ZERO

func event_cam_fov() -> float:
    if event_cam.has("fov"):
        return float(event_cam["fov"])
    var cam := get_viewport().get_camera_3d()
    return cam.fov if cam else 60.0

func fade(to_alpha: float, frames: int) -> void:
    if fade_rect == null:
        return
    var tw := create_tween()
    tw.tween_property(fade_rect, "color:a", to_alpha, frames / 30.0)

# ---- the Great Sea (d_a_sea.cpp wi_prm_ocean) and the wind (d_kankyo_wether.cpp)

const SEA_WAVES := [
    # amplitude, wavelength, phase (s16), dir x, dir z, period (frames)
    [2.5, 13600.0, 0.0, 0.98, 0.20, 200.0],
    [2.5, 11200.0, 4000.0, 0.20, 0.98, 190.0],
    [2.5, 8800.0, 8000.0, -0.98, 0.20, 210.0],
    [2.5, 6400.0, 12000.0, 0.20, -0.98, 180.0],
]
# A room's MULT chunk carries wave_max, and the values on the disc are NOT a 0..10 range:
# measured across every stage, the only ones that occur are 0 (431 rooms - harbours and
# interiors), 5 (3), 15 (1), 30 (30 - the open sea), 50 (9 - the roughest water), and -1 where
# the room has no MULT entry at all.
const SEA_WAVE_OPEN := 30.0    # the value every open-sea room actually carries
var sea_wave_max: Dictionary = {}   # "room" -> wave_max of the current stage (from MULT)
var sea_cur_scale := SEA_WAVE_OPEN  # daSea_WaveInfo::GetScale eases towards the target
var wind_yaw := 0.0            # Wind's Requiem yaw: 0 = east (new file), 45 deg steps
var wind_power := 0.9

func sea_wave_target(x: float, z: float) -> float:
    # which wave_max this point wants, before smoothing
    if sea_wave_max.is_empty():
        return SEA_WAVE_OPEN
    var room := str(sea_room_at(Vector3(x, 0.0, z)))
    var v := -1.0
    if sea_wave_max.has(room):
        v = float(sea_wave_max[room])
    elif sea_wave_max.size() == 1:
        v = float(sea_wave_max.values()[0])
    if v < 0.0:
        return SEA_WAVE_OPEN    # -1 = the room has no MULT entry
    return v

var _wave_ease_frame := -1

func sea_wave_scale(x: float, z: float) -> float:
    # d_a_sea.cpp:171-174 - one eased scalar for the whole sheet, not a per-point value, so
    # sailing from open water into a harbour ramps the swell down over about a second and a
    # half instead of snapping flat at the room boundary.  Eased ONCE per physics frame no
    # matter how many callers ask: sea_height() is called several times a frame by the boat's
    # four wave probes, and easing per call ran the ramp at four times the game's rate.
    var frame := Engine.get_physics_frames()
    if frame == _wave_ease_frame:
        return sea_cur_scale
    _wave_ease_frame = frame
    var want := sea_wave_target(x, z)
    sea_cur_scale += (want - sea_cur_scale) / 100.0
    if absf(want - sea_cur_scale) < 0.01:
        sea_cur_scale = want
    return sea_cur_scale

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

func playable(stage: String) -> bool:
    # a few ripped stages are empty shells (no PLYR chunk at all): the name-entry screen, an
    # unused second cut of Outset, and two room scenes with no room.  There is nowhere to stand.
    var info: Dictionary = stage_data.get(stage, {})
    return not (info.get("spawns", []) as Array).is_empty()

func go_to_stage(stage: String, want_spawn := -1) -> void:
    if not playable(stage):
        print("gcrip: ", stage, " has no spawn point - nothing to stand on, staying put")
        _show_banner("%s has no spawn point in the rip" % stage)
        return
    var info: Dictionary = stage_data.get(stage, {})
    var spawns: Array = info.get("spawns", [])
    var room := 0
    var spawn := 0
    if spawns.size() > 0:
        room = int(spawns[0].get("room", 0))
        spawn = int(spawns[0].get("id", 0))
    for sp in spawns:
        if want_spawn >= 0 and int(sp.get("id", -1)) == want_spawn:
            room = int(sp.get("room", 0))
            spawn = want_spawn
            break
    last_warp_ms = -100000
    warp(stage, room, spawn)
    _apply_saved_pad_mappings()

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

func scripted() -> bool:
    # any headless harness run: nobody is holding the pad, so "press any key" waits must pass
    return conduct_test or selftest or story_test or newgame_test or dialogue_test or door_test         or talk_test != "" or event_test != "" or shot_actor != "" or scope_test or near_test or defeat_test != "" or hit_test or timer_test != "" or island_test >= 0 or salvage_test >= 0 or dungeon_test or hitsw_test != "" or opening_test or sweep_test or doors_test \
        or models_test or cuts_test or object_test or clock_test

func stage_boss_dead(stage := "") -> bool:
    # A dungeon boss's death is NOT an event bit: dComIfGs_onStageBossEnemy writes its own save
    # area, and several actors key off it (the warp flower, the heart container, the partner NPC
    # who appears afterwards).  So it gets its own dictionary here too.
    var key := stage if stage != "" else current_stage_key()
    return bool((save.get("boss_dead", {}) as Dictionary).get(key, false))

func set_stage_boss_dead(stage := "") -> void:
    var key := stage if stage != "" else current_stage_key()
    var dead: Dictionary = save.get("boss_dead", {})
    dead[key] = true
    save["boss_dead"] = dead
    print("gcrip: boss of ", key, " is down")

func _defeat_matches(step: Dictionary, actor: String, boss: bool) -> bool:
    var d = step.get("defeat")
    if not (d is Dictionary):
        return false
    if bool(d.get("room_clear", false)):
        return false            # room clears come through story_room_cleared instead
    if str(d.get("enemy", "")) != actor:
        return false
    if bool(d.get("boss", false)) != boss:
        return false
    var want := str(d.get("stage", ""))
    if want == "":
        want = sfield(step, "stage")
    return want == "" or want == current_stage_key()

func story_enemy_defeated(actor: String, boss := false) -> void:
    # one enemy died; if a step was waiting on exactly that, it happens now
    if actor == "":
        return
    if boss:
        set_stage_boss_dead()
    for step in story.get("steps", []):
        if not _defeat_matches(step, actor, boss):
            continue
        var id := sfield(step, "id")
        if story_done(id) or not _story_bits_ok(step):
            continue
        _mark_story_done(id)
        var ev := sfield(step, "event")
        print("gcrip story: ", actor, " defeated -> ", id, " (event ", ev, ")")
        if ev != "" and events.has(ev) and run_event(ev):
            return
        story_event_done(id)
        return

func room_live_enemies(room: int) -> int:
    var n := 0
    for e in get_tree().get_nodes_in_group("enemy"):
        if is_instance_valid(e) and int(e.get("room")) == room and not bool(e.get("dead")):
            n += 1
    return n

func story_room_cleared(room: int) -> void:
    # the last enemy in a room died.  A door built into ACT_GENOCIDE opens on exactly this, and
    # Dragon Roost's second Mori1 door is what un-pins Medli when it does.
    if room_live_enemies(room) > 0:
        return
    var key := "%s:r%d" % [current_scene_key(), room]
    var cleared: Dictionary = save.get("rooms_cleared", {})
    if cleared.has(key):
        return
    cleared[key] = true
    save["rooms_cleared"] = cleared
    for step in story.get("steps", []):
        var d = step.get("defeat")
        if not (d is Dictionary) or not bool(d.get("room_clear", false)):
            continue
        var st := sfield(step, "stage")
        if st != "" and st != current_stage_key():
            continue
        if step.get("room") != null and int(step["room"]) != room:
            continue
        var id := sfield(step, "id")
        if story_done(id) or not _story_bits_ok(step):
            continue
        _mark_story_done(id)
        print("gcrip story: room ", room, " cleared -> ", id)
        var ev := sfield(step, "event")
        if ev != "" and events.has(ev) and run_event(ev):
            return
        story_event_done(id)
        return

func story_item_step(actor: String) -> Dictionary:
    # the mined "item" step a placed pickup belongs to. The exporter pulled the actor name out
    # of the trigger prose into step["pickup"], so the engine never has to read English.
    if actor == "":
        return {}
    var here := current_stage_key()
    for step in story.get("steps", []):
        var trig = step.get("trigger", {})
        if not (trig is Dictionary) or str(trig.get("kind", "")) != "item":
            continue
        var pick = step.get("pickup", {})
        if not (pick is Dictionary) or str(pick.get("actor", "")) != actor:
            continue
        var st := sfield(step, "stage")
        if st != "" and st != here:
            continue
        return step
    return {}

func story_pickup_ok(step: Dictionary) -> bool:
    # d_a_deku_item.cpp:105-131 - _create returns cPhs_ERROR_e both when the item bit is
    # already collected and when its event bit is clear, so a placed pickup does not exist
    # yet (it is not hidden - it is absent) until its own step is reachable and unfinished.
    if step.is_empty():
        return true
    return _story_bits_ok(step) and not story_done(sfield(step, "id"))

# d_item_data.h:28, :83-85 - the four items that belong to the dungeon block, not the bag
const ITEM_SMALL_KEY := 0x15
const ITEM_MAP := 0x4C
const ITEM_COMPASS := 0x4D
const ITEM_BIG_KEY := 0x4E

func dungeon_item_collected(item_no: int) -> bool:
    # the four items that live in dSv_memBit_c rather than the inventory; true if handled
    match item_no:
        ITEM_SMALL_KEY:
            add_key(1)
            return true
        ITEM_MAP:
            give_dungeon_item(DUNGEON_MAP)
            return true
        ITEM_COMPASS:
            give_dungeon_item(DUNGEON_COMPASS)
            return true
        ITEM_BIG_KEY:
            give_dungeon_item(DUNGEON_BIG_KEY)
            return true
    return false

func story_item_collected(item_no: int, actor: String) -> void:
    dungeon_item_collected(item_no)
    # picking a placed item up, or opening the chest that holds it, closes the step that names
    # it: pickups match on their actor, chests on the dItemNo mined out of the gives_item prose
    var here := current_stage_key()
    for step in story.get("steps", []):
        var trig = step.get("trigger", {})
        if not (trig is Dictionary) or str(trig.get("kind", "")) != "item":
            continue
        var pick = step.get("pickup", {})
        var by_actor: bool = actor != "" and pick is Dictionary and str(pick.get("actor", "")) == actor
        var by_no := false
        if item_no >= 0:
            for n in step.get("item_nos", []):
                if int(n) == item_no:
                    by_no = true
                    break
        if not (by_actor or by_no):
            continue
        var id := sfield(step, "id")
        if story_done(id):
            continue
        var st := sfield(step, "stage")
        if st != "" and st != here:
            continue
        _mark_story_done(id)
        var what: String = ("0x%02X" % item_no) if item_no >= 0 else actor
        print("gcrip story: got ", what, " -> ", id)
        story_event_done(id)
        return

func story_chest_opened(item_id: int) -> void:
    # a chest story step records the dItemNo it holds; the chest decodes the same number out of
    # its rot.z, so the two match without having to name the chest itself
    var here := current_stage_key()
    for step in story.get("steps", []):
        var trig = step.get("trigger", {})
        if not (trig is Dictionary) or str(trig.get("kind", "")) != "chest":
            continue
        if int(step.get("item_no", -1)) != item_id:
            continue
        var id := sfield(step, "id")
        if story_done(id):
            continue
        var st := sfield(step, "stage")
        if st != "" and st != here:
            continue
        _mark_story_done(id)
        print("gcrip story: chest -> ", id, " (item 0x%02X)" % item_id)
        story_event_done(id)
        return

# ---- the timed islands (daTagvolcano::Act_c) -------------------------------------------
# Lives on Game, not on the scene, because the clock has to survive the warp into the cave.
var timer_left := -1.0            # seconds remaining, < 0 = no timer running
var timer_info: Dictionary = {}   # the start step's timer block, so the cave knows its island

func story_hit_switch(actor: String, room: int, swbit: int) -> void:
    # a hit step whose object is one of these switches finishes when its switch goes on
    var here := current_stage_key()
    for step in story.get("steps", []):
        var trig = step.get("trigger")
        if not (trig is Dictionary) or str(trig.get("kind", "")) != "hit":
            continue
        var id := sfield(step, "id")
        if story_done(id) or not _story_bits_ok(step):
            continue
        var st := sfield(step, "stage")
        if st != "" and st != here and st != here.split("_r")[0]:
            continue
        if str(trig.get("detail", "")).find(actor) < 0:
            continue
        _mark_story_done(id)
        print("gcrip story: ", actor, " switch ", swbit, " (room ", room, ") -> ", id)
        var ev := sfield(step, "event")
        if ev != "" and events.has(ev) and run_event(ev):
            return
        story_event_done(id)
        return

func story_timer_running() -> bool:
    return timer_left >= 0.0

func _timer_start(step: Dictionary, clock: Dictionary) -> void:
    timer_info = clock.duplicate()
    timer_left = float(clock.get("seconds", 300.0))
    timer_info["step"] = sfield(step, "id")
    _mark_story_done(sfield(step, "id"))
    print("gcrip timer: ", timer_info["step"], " - ", timer_left, " s to reach the chest in ",
        clock.get("cave_stage", "?"))

func _timer_stop() -> void:
    timer_left = -1.0
    timer_info = {}

func story_timer_beaten(tbox: int) -> void:
    # the cave-side VolTag: dComIfGs_isTbox(bitTRB) went true, so the island is settled for good
    if not story_timer_running():
        return
    var here := current_stage_key()
    for step in story.get("steps", []):
        var clock = step.get("timer")
        if not (clock is Dictionary) or not bool(clock.get("beaten", false)):
            continue
        if str(clock.get("cave_stage", "")) != here or int(clock.get("tbox", -1)) != tbox:
            continue
        var id := sfield(step, "id")
        if story_done(id):
            continue
        _timer_stop()
        _mark_story_done(id)
        print("gcrip timer: chest ", tbox, " opened -> ", id, " (the island is settled)")
        story_event_done(id)
        return

func _timer_expired() -> void:
    # switch back off: the sea-side actor re-seals the island the moment its switch drops
    var sw = timer_info.get("switch")
    if sw != null:
        clear_switch(int(timer_info.get("room", 0)), int(sw))
    var cave := str(timer_info.get("cave_stage", ""))
    var isle := int(timer_info.get("isle_room", 0))
    var inside := current_stage_key() == cave
    print("gcrip timer: out of time (switch ", int(sw) if sw != null else -1, " off, ",
        "Link is inside" if inside else "Link is outside", ")")
    _timer_stop()
    if not inside:
        return
    last_warp_ms = -100000
    # the cave-side branch: order TAG_VOLCANO, then throw Link out onto the island at spawn 2
    for step in story.get("steps", []):
        var clock = step.get("timer")
        if not (clock is Dictionary) or not bool(clock.get("timeout", false)):
            continue
        if str(clock.get("cave_stage", "")) != cave:
            continue
        var ev := sfield(step, "event")
        _mark_story_done(sfield(step, "id"))
        if ev != "" and events.has(ev) and run_event(ev):
            _timer_eject = [isle, 2]
            return
        break
    warp("sea", isle, 2)

var _timer_eject: Array = []      # [isle_room, spawn] to leave for once TAG_VOLCANO ends

func story_timer_tick(delta: float) -> void:
    # start any waiting island whose switch is on, then run the clock
    for step in story.get("steps", []):
        var clock = step.get("timer")
        if not (clock is Dictionary) or not bool(clock.get("start", false)):
            continue
        if story_done(sfield(step, "id")) or story_timer_running():
            continue
        if is_switch(int(clock.get("room", 0)), int(clock.get("switch", -1))):
            _timer_start(step, clock)
    if not story_timer_running():
        return
    if event_running or cutscene_running() or dialog_open:
        # the real actor pauses the clock for the length of any event and restarts it after
        if not _timer_eject.is_empty():
            return
        return
    if not _timer_eject.is_empty():
        var go: Array = _timer_eject
        _timer_eject = []
        warp("sea", int(go[0]), int(go[1]))
        return
    timer_left -= delta
    if timer_left <= 0.0:
        _timer_expired()

# ---- salvage (d_salvage.cpp / d_a_salvage.cpp) -----------------------------------------
# daSalvage_c::m_savelabel[16] - the only salvage state kept as event bits, d_com_static.cpp:115
const SALVAGE_FM_BITS := [0x2080, 0x2004, 0x2002, 0x2804, 0x2802, 0x2801, 0x2980, 0x2940,
                          0x3B01, 0x3C80, 0x3C40, 0x3C20, 0x3C10, 0x3C08, 0x3C04, 0x3C02]

func try_salvage(at: Vector3) -> Dictionary:
    # the crane comes down at the boat: find an available point whose ring holds this XZ
    var water := sea_height(at.x, at.z) if current_stage_key().begins_with("sea") else 0.0
    var best: Node3D = null
    var best_d := 1.0e30
    for sp in get_tree().get_nodes_in_group("salvage"):
        if not is_instance_valid(sp) or not sp.call("available"):
            continue
        var tip := Vector3(at.x, water - float(sp.get("depth")) - 1.0, at.z)
        if not sp.call("in_reach", tip, water):
            continue
        var d: float = at.distance_to((sp as Node3D).global_position)
        if d < best_d:
            best_d = d
            best = sp
    if best == null:
        return {"hit": false, "none": true}
    var out: Dictionary = best.call("dredge")
    var kinds := ["chart", "?", "switch", "free", "night", "decoy", "full moon"]
    var kn: String = kinds[int(out["kind"])] if int(out["kind"]) < kinds.size() else "?"
    if bool(out["hit"]):
        print("gcrip salvage: dredged a ", kn, " point -> item 0x%02X" % int(out["item"]))
        show_text("You pulled up a treasure!")
    else:
        print("gcrip salvage: the crane comes up empty (", kn, " point)",
            " - and something came with it" if bool(out["octorok"]) else "")
        show_text("Nothing but sand...")
    return out

# ---- dungeon progression (d_save.h dSv_memBit_c, d_door.cpp) ---------------------------
var dungeons: Dictionary = {}      # stage -> {slot, key_counter, type}

const DUNGEON_MAP := 1             # mDungeonItem bit 0
const DUNGEON_COMPASS := 2         # bit 1
const DUNGEON_BIG_KEY := 4         # bit 2

# ---- cel shading -----------------------------------------------------------------------
var sun_direction := Vector3(0.55, -0.72, 0.42)   # set by the stage's light rig each tick
# the luminance of a lit diffuse white right now, lux / pi - what unshaded shaders scale by so
# they sit at the same exposure as the lit surfaces (physical light units)
var physical := false          # physical light units + HDR rig; else simple always-on light
var scene_nits := 1.0          # unshaded multiplier; 1.0 in simple mode, high only in physical
# Four variants of each cel shader, keyed "" / "_ds" / "_a" / "_ds_a":
#   _ds = culling disabled (the game drew that material from both sides)
#   _a  = writes ALPHA (a genuinely BLENDED material; everything else is opaque or cutout)
var toon_shaders: Dictionary = {}
var lit_shaders: Dictionary = {}
var toon_shader: Shader = null         # the plain variant, kept for toon_ready()
var toon_ramp: Texture2D = null
var toon_on := true
# the look the whole world is drawn in.  "toon" is the game's own recipe, untouched; the others
# all run ww_material.gdshader with a different `look` uniform.
const SHADE_MODES := ["toon", "hybrid", "clay", "paper", "pbr"]
var shade_mode := "toon"
var material_classes: Dictionary = {}   # materials.json
var _toon_cache: Dictionary = {}     # source material -> the ShaderMaterial built from it

# ---- particles (JPA) -------------------------------------------------------------------
var _fx_defs: Dictionary = {}
var _fx_mats: Dictionary = {}
var fx_on := true

func fx_def(id: int) -> Dictionary:
    if _fx_defs.has(id):
        return _fx_defs[id]
    var path := "res://fx/%04x.json" % id
    var d := {}
    var f := FileAccess.open(path, FileAccess.READ)
    if f:
        var parsed = JSON.parse_string(f.get_as_text())
        if parsed is Dictionary:
            d = parsed
    _fx_defs[id] = d
    return d

func _fx_material(d: Dictionary) -> ShaderMaterial:
    var key := str(d.get("id", 0))
    if _fx_mats.has(key):
        return _fx_mats[key]
    var m := ShaderMaterial.new()
    if ResourceLoader.exists("res://fx.gdshader"):
        m.shader = load("res://fx.gdshader")
    var tp := "res://fx/tex/%s.png" % str(d.get("texture", ""))
    if ResourceLoader.exists(tp):
        m.set_shader_parameter("mask_tex", load(tp))
    var prm: Array = d.get("prm", [255, 255, 255, 255])
    var env: Array = d.get("env", [0, 0, 0, 255])
    m.set_shader_parameter("prm_color", Color(prm[0] / 255.0, prm[1] / 255.0, prm[2] / 255.0, prm[3] / 255.0))
    m.set_shader_parameter("env_color", Color(env[0] / 255.0, env[1] / 255.0, env[2] / 255.0, env[3] / 255.0))
    m.set_shader_parameter("additive", bool(d.get("additive", false)))
    m.set_shader_parameter("nits", scene_nits)
    _fx_mats[key] = m
    return m

func fx(id: int, at: Vector3, scale := 1.0) -> bool:
    # dComIfGp_particle_set, for a one-shot effect: build the emitter from the bank's own
    # numbers.  Every JPA time is 30 fps frames; base size is already in world units.
    if not fx_on:
        return false
    var d := fx_def(id)
    if d.is_empty():
        return false
    var cs := get_tree().current_scene
    if cs == null:
        return false
    var life := maxf(float(d.get("life_frames", 30)) / 30.0, 0.05)
    var span := maxf(float(d.get("max_frames", 1)), 1.0) / 30.0
    var gp := GPUParticles3D.new()
    var n := int(ceil(float(d.get("rate", 1.0)) * maxf(float(d.get("max_frames", 1)), 1.0)))
    gp.amount = clampi(n, 1, 200)
    gp.lifetime = life
    gp.one_shot = true
    gp.explosiveness = 1.0 if span <= life * 0.5 else 0.3
    gp.local_coords = false
    var pm := ParticleProcessMaterial.new()
    var sz: Array = d.get("base_size", [25.0, 25.0])
    var vol := float(d.get("volume_size", 0)) * scale
    pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
    pm.emission_sphere_radius = maxf(vol, 1.0)
    var v0 := (float(d.get("vel_omni", 0.0)) + float(d.get("vel_axis", 0.0))) * 30.0 * scale
    var vr := float(d.get("vel_rndm", 0.0)) * 30.0 * scale
    pm.initial_velocity_min = maxf(v0 - vr, 0.0)
    pm.initial_velocity_max = v0 + vr
    pm.spread = clampf(float(d.get("spread", 1.0)) * 180.0, 0.0, 180.0)
    pm.direction = Vector3.UP
    pm.gravity = Vector3(0, -300.0 if bool(d.get("fields", false)) else 0.0, 0)
    var sc: Array = d.get("scale", [0.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    pm.scale_min = maxf(float(sc[2]), 0.05) * scale
    pm.scale_max = maxf(float(sc[2]), 0.05) * scale
    var curve := Curve.new()
    var al: Array = d.get("alpha", [0.0, 1.0, 0.0, 1.0, 0.0])
    curve.add_point(Vector2(0.0, float(al[2])))
    curve.add_point(Vector2(clampf(float(al[0]), 0.0, 1.0), float(al[3])))
    curve.add_point(Vector2(clampf(float(al[1]), 0.0, 1.0), float(al[3])))
    curve.add_point(Vector2(1.0, float(al[4])))
    var ct := CurveTexture.new()
    ct.curve = curve
    pm.alpha_curve = ct
    gp.process_material = pm
    var quad := QuadMesh.new()
    quad.size = Vector2(float(sz[0]), float(sz[1])) * scale
    quad.material = _fx_material(d)
    gp.draw_pass_1 = quad
    cs.add_child(gp)
    gp.global_position = at
    gp.emitting = true
    gp.finished.connect(gp.queue_free)
    return true

# ---- sound effects --------------------------------------------------------------------
var _sfx_pool: Array = []
var _sfx_cache: Dictionary = {}
var sfx_on := true

func sfx_stream(name: String) -> AudioStream:
    if _sfx_cache.has(name):
        return _sfx_cache[name]
    var path := "res://sfx/%s.wav" % name
    var st: AudioStream = load(path) if ResourceLoader.exists(path) else null
    _sfx_cache[name] = st
    return st

func play_sfx(name: String, at: Vector3, volume_db := 0.0) -> bool:
    if not sfx_on:
        return false
    var st := sfx_stream(name)
    if st == null:
        return false
    var cs := get_tree().current_scene
    if cs == null:
        return false
    var pl: AudioStreamPlayer3D = null
    for p in _sfx_pool:
        if is_instance_valid(p) and not p.playing:
            pl = p
            break
    if pl == null:
        if _sfx_pool.size() >= 12:
            return false
        pl = AudioStreamPlayer3D.new()
        pl.max_distance = 3000.0
        pl.unit_size = 300.0
        _sfx_pool.append(pl)
    if pl.get_parent() != cs:
        if pl.get_parent():
            pl.get_parent().remove_child(pl)
        cs.add_child(pl)
    pl.global_position = at
    pl.stream = st
    pl.volume_db = volume_db
    pl.play()
    return true

func ground_material(p: Vector3) -> int:
    # the footstep material under a point: the solid collider is named Room{n}_solid_s{m}
    var under := ground_under(p)
    var i := under.find("_solid_s")
    if i < 0:
        return -1
    var rest := under.substr(i + 8)
    var digits := ""
    for ch in rest:
        if ch < "0" or ch > "9":
            break
        digits += ch
    return int(digits) if digits != "" else -1

func shade_look() -> int:
    return SHADE_MODES.find(shade_mode)

func _load_material_classes() -> void:
    if not material_classes.is_empty():
        return
    var f := FileAccess.open("res://materials.json", FileAccess.READ)
    if f:
        var parsed = JSON.parse_string(f.get_as_text())
        if parsed is Dictionary:
            material_classes = parsed

func classify_material(src: Material, archive: String) -> Dictionary:
    # (1) curated (archive, material substring) pairs - the only route to metal;
    # (2) name substrings; (3) default, dielectric and rough
    _load_material_classes()
    var classes: Dictionary = material_classes.get("classes", {})
    var mname := (src.resource_name if src else "").to_lower()
    var tname := ""
    if src is StandardMaterial3D and (src as StandardMaterial3D).albedo_texture:
        tname = (src as StandardMaterial3D).albedo_texture.resource_path.get_file().to_lower()
    var cls := "default"
    var curated: Dictionary = material_classes.get("curated", {})
    var arc := archive
    if curated.has(arc):
        for pair in curated[arc]:
            var sub := str(pair[0]).to_lower()
            if sub == "" or mname.find(sub) >= 0 or tname.find(sub) >= 0:
                cls = str(pair[1])
                break
    if cls == "default":
        var by_name: Dictionary = material_classes.get("by_name", {})
        for key in by_name:
            if str(key).begins_with("_"):
                continue
            if mname.find(str(key)) >= 0 or tname.find(str(key)) >= 0:
                cls = str(by_name[key])
                break
    var out: Dictionary = (classes.get(cls, classes.get("default", {})) as Dictionary).duplicate()
    out["class"] = cls
    return out

func toon_ready() -> bool:
    if not toon_on:
        return false
    if toon_shaders.is_empty():
        for v in ["", "_ds", "_a", "_ds_a"]:
            var tp := "res://toon%s.gdshader" % v
            if ResourceLoader.exists(tp):
                toon_shaders[v] = load(tp)
            var lp := "res://ww_material%s.gdshader" % v
            if ResourceLoader.exists(lp):
                lit_shaders[v] = load(lp)
        toon_shader = toon_shaders.get("", null)
    if toon_ramp == null and ResourceLoader.exists("res://toon_ramp.png"):
        toon_ramp = load("res://toon_ramp.png")
    return toon_shader != null and toon_ramp != null

var _shade_archive := ""     # set by toonify() so classify_material knows where a surface came from

func _toon_material(src: Material) -> ShaderMaterial:
    # one ShaderMaterial per source material, shared by every surface that used it
    var key := src.resource_path if src and src.resource_path != "" else str(src)
    key += "|" + shade_mode
    # the original's GX cull mode came through glTF doubleSided; keep it, or surfaces the
    # game drew from both sides go invisible from one side (the see-through bridge)
    var two_sided := (src is BaseMaterial3D
        and (src as BaseMaterial3D).cull_mode == BaseMaterial3D.CULL_DISABLED)
    # only a genuinely BLENDED material may write ALPHA.  Alpha-scissor is a cutout and stays
    # opaque (the shader discards); anything else that writes ALPHA lands in the transparent
    # queue, stops writing depth, and gets sorted against the sea by bounding-box centre.
    var blended := (src is BaseMaterial3D
        and (src as BaseMaterial3D).transparency == BaseMaterial3D.TRANSPARENCY_ALPHA)
    var variant := ("_ds" if two_sided else "") + ("_a" if blended else "")
    key += "|" + variant
    if _toon_cache.has(key):
        return _toon_cache[key]
    var m := ShaderMaterial.new()
    var lit: bool = shade_mode != "toon" and not lit_shaders.is_empty()
    var table: Dictionary = lit_shaders if lit else toon_shaders
    m.shader = table.get(variant, table.get("", null))
    m.set_shader_parameter("toon_ramp", toon_ramp)
    if lit:
        var cls := classify_material(src, _shade_archive)
        m.set_shader_parameter("look", shade_look())
        m.set_shader_parameter("metallic", float(cls.get("metallic", 0.0)))
        m.set_shader_parameter("roughness", float(cls.get("roughness", 0.75)))
        m.set_shader_parameter("specular", float(cls.get("specular", 0.4)))
        var sh: Array = cls.get("sheen", [0, 0, 0])
        m.set_shader_parameter("sheen_color", Vector3(float(sh[0]), float(sh[1]), float(sh[2])))
        m.set_shader_parameter("sheen_roughness", float(cls.get("sheen_roughness", 0.35)))
        m.set_shader_parameter("clearcoat", float(cls.get("clearcoat", 0.0)))
        m.set_shader_parameter("clearcoat_roughness", float(cls.get("clearcoat_roughness", 0.05)))
        m.set_shader_parameter("backlight", float(cls.get("backlight", 0.0)))
        # the looks that are about the surface grain
        var grain := 0.0
        if shade_mode == "clay":
            grain = 0.35
        elif shade_mode == "paper":
            grain = 0.5
        m.set_shader_parameter("micro_normal", grain)
        m.set_shader_parameter("grain_scale", 18.0 if shade_mode == "clay" else 9.0)
    var tex: Texture2D = null
    var col := Color(1, 1, 1, 1)
    var scissor := 0.0
    if src is StandardMaterial3D:
        var std := src as StandardMaterial3D
        tex = std.albedo_texture
        col = std.albedo_color
        if std.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR:
            scissor = std.alpha_scissor_threshold
        elif std.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA:
            m.render_priority = 1
    m.set_shader_parameter("albedo_tex", tex)
    m.set_shader_parameter("has_tex", tex != null)
    m.set_shader_parameter("albedo_col", col)
    m.set_shader_parameter("alpha_scissor", scissor)
    _toon_cache[key] = m
    return m

func toonify(root: Node, archive := "") -> int:
    # walk a freshly instanced model and swap each surface for the ramp shader
    if root == null or not toon_ready():
        return 0
    _shade_archive = archive
    var n := 0
    var stack: Array = [root]
    while not stack.is_empty():
        var node = stack.pop_back()
        for c in node.get_children():
            stack.append(c)
        if not (node is MeshInstance3D):
            continue
        var mi := node as MeshInstance3D
        if mi.mesh == null:
            continue
        for i in range(mi.mesh.get_surface_count()):
            # the ORIGINAL material is the one on the mesh; an override from a previous look is
            # replaced, not stacked, so F6 can re-shade a loaded scene
            var src: Material = mi.mesh.surface_get_material(i)
            if src == null:
                src = mi.get_active_material(i)
            if src == null or src is ShaderMaterial:
                continue
            mi.set_surface_override_material(i, _toon_material(src))
            n += 1
    return n

func set_toon(on: bool) -> void:
    toon_on = on
    save["toon"] = on
    print("gcrip toon: cel shading ", "on" if on else "off", " - reload the stage to see it")

func set_shade_mode(mode: String) -> void:
    if not SHADE_MODES.has(mode):
        return
    shade_mode = mode
    save["shade_mode"] = mode
    _toon_cache.clear()
    print("gcrip shade: ", mode, " - ", {
        "toon": "the game's own ramp, unlit",
        "hybrid": "the ramp as diffuse + physical specular / sheen / Fresnel where the class asks",
        "clay": "matte stop-motion clay: wrapped diffuse, warm terminator, fingerprint grain",
        "paper": "papercraft: fibre grain, rim-lit edges, light through the sheet",
        "pbr": "straight Burley / GGX, the comparison case",
    }[mode])

func toon_sun_colors() -> Array:
    # C0 / K0 come from the time-of-day palette every frame in the real game
    # (d_kankyo.cpp:1821, :1827). The Great Sea's Actor_K0 runs (255,222,163) at noon to
    # (158,158,155) at night; C0 is its shadow partner.
    var h := day_time() / UNITS_PER_HOUR
    var day_k := Color(1.0, 0.871, 0.639)
    var night_k := Color(0.62, 0.62, 0.608)
    var day_c := Color(0.42, 0.44, 0.52)
    var night_c := Color(0.20, 0.22, 0.34)
    var t := clampf((cos((h - 12.0) / 24.0 * TAU) + 1.0) * 0.5, 0.0, 1.0)
    return [night_c.lerp(day_c, t), night_k.lerp(day_k, t)]

func toon_input(event: InputEvent) -> void:
    # F6 flips cel shading so the two looks can be compared without relaunching
    if event is InputEventKey and event.pressed and not event.echo and (event as InputEventKey).keycode == KEY_F6:
        # F6 cycles the looks: toon -> hybrid -> clay -> paper -> pbr -> toon
        var i := SHADE_MODES.find(shade_mode)
        set_shade_mode(SHADE_MODES[(i + 1) % SHADE_MODES.size()])
        show_text("Look: %s  (F6 cycles)" % shade_mode)
        # re-apply to the scene that is already loaded.  Reloading the whole sea under F6 -
        # 1224 actors, SDFGI, SSIL and a 25 MB sky torn down and rebuilt in a frame - is what
        # crashed the engine in the first play session.
        var cs := get_tree().current_scene
        if cs and cs.has_method("_apply_toon"):
            cs.call("_apply_toon")

func toon_tick() -> void:
    if not toon_on or _toon_cache.is_empty():
        return
    var cs := toon_sun_colors()
    for k in _toon_cache:
        var m: ShaderMaterial = _toon_cache[k]
        m.set_shader_parameter("c0", Vector3(cs[0].r, cs[0].g, cs[0].b))
        m.set_shader_parameter("k0", Vector3(cs[1].r, cs[1].g, cs[1].b))
        m.set_shader_parameter("sun_dir", sun_direction)
        m.set_shader_parameter("nits", scene_nits)

func shade_report() -> Dictionary:
    # which classes the current stage's surfaces landed in - the --shade harness prints it
    var counts := {}
    for k in _toon_cache:
        var m: ShaderMaterial = _toon_cache[k]
        var look = m.get_shader_parameter("look")
        var met = m.get_shader_parameter("metallic")
        var key := "metal" if met != null and float(met) > 0.5 else ("lit" if look != null else "toon")
        counts[key] = int(counts.get(key, 0)) + 1
    return counts

func dungeon_slot(stage := "") -> int:
    var key := stage if stage != "" else current_stage_key().split("_r")[0]
    var info = dungeons.get(key)
    return int(info["slot"]) if info is Dictionary else 11   # 11 = STAGE_MISC

func dungeon_shows_keys() -> bool:
    var info = dungeons.get(current_stage_key().split("_r")[0])
    return info is Dictionary and bool(info.get("key_counter", false))

func _dungeon_block() -> Dictionary:
    var all: Dictionary = save.get("dungeon", {})
    var k := str(dungeon_slot())
    if not all.has(k):
        all[k] = {"keys": 0, "items": 0}
        save["dungeon"] = all
    return all[k]

func key_count() -> int:
    return int(_dungeon_block().get("keys", 0))

func add_key(n: int) -> void:
    # mKeyNum is a COUNT in the dungeon's own save block, clamped 0..99 by dMeter_keyMove
    var b := _dungeon_block()
    b["keys"] = clampi(int(b.get("keys", 0)) + n, 0, 99)
    print("gcrip dungeon: slot ", dungeon_slot(), " keys -> ", b["keys"])

func dungeon_item(bit: int) -> bool:
    return (int(_dungeon_block().get("items", 0)) & bit) != 0

func give_dungeon_item(bit: int) -> void:
    var b := _dungeon_block()
    b["items"] = int(b.get("items", 0)) | bit
    var nm: String = str({1: "Dungeon Map", 2: "Compass", 4: "Big Key"}.get(bit, "?"))
    print("gcrip dungeon: slot ", dungeon_slot(), " got the ", nm)

func random_salvage_point() -> int:
    # dSv_player_info_c::init: mRandomSalvagePoint = cM_rndF(3.0f) clamped to 0..2, rolled ONCE
    # per save file - which of a room's four candidate spots actually holds the chart's treasure
    var info: Dictionary = save.get("info", {})
    if not info.has("random_salvage_point"):
        info["random_salvage_point"] = randi() % 3
        save["info"] = info
        print("gcrip salvage: this file's salvage spot is candidate ",
            info["random_salvage_point"])
    return int(info["random_salvage_point"])

func ocean_bit(room: int, save_no: int) -> bool:
    return bool((save.get("ocean", {}) as Dictionary).get("%d/%d" % [room, save_no], false))

func set_ocean_bit(room: int, save_no: int) -> void:
    var o: Dictionary = save.get("ocean", {})
    o["%d/%d" % [room, save_no]] = true
    save["ocean"] = o

func collect_map_done(chart: int) -> bool:
    return bool((save.get("collect_map", {}) as Dictionary).get(str(chart), false))

func set_collect_map_done(chart: int) -> void:
    var m: Dictionary = save.get("collect_map", {})
    m[str(chart)] = true
    save["collect_map"] = m

func full_moon_night() -> bool:
    # proc_wait, d_a_salvage.cpp:332-340: !dKy_moon_type_chk() is day-of-week 0, and
    # dKyr_moon_arrival_check() is true past 277.5 or before 112.5 - the full moon's night
    var day := int(save.get("day", 0))
    var t := float(save.get("day_time", 0.0))
    return day % 7 == 0 and (t > 277.5 or t < 112.5)

func story_bits_tick() -> void:
    # a step whose trigger is a pure bit test: it fires the moment every bit it requires is set.
    # Ganon's Tower uses one - daObjVgnfd_c opens the last door once all four trials are clear.
    if event_running or cutscene_running() or dialog_open:
        return
    for step in story.get("steps", []):
        var trig = step.get("trigger", {})
        if not (trig is Dictionary) or str(trig.get("kind", "")) != "bits":
            continue
        var id := sfield(step, "id")
        if story_done(id) or not _story_bits_ok(step):
            continue
        if (step.get("requires_bits", []) as Array).is_empty():
            continue        # a bits trigger with no bits would fire immediately, for ever
        _mark_story_done(id)
        var ev := sfield(step, "event")
        print("gcrip story: bits complete -> ", id, " (event ", ev, ")")
        if ev != "" and events.has(ev) and run_event(ev):
            return
        story_event_done(id)
        return

func story_npc_tag_step(tag: String) -> Dictionary:
    # The step a "npc_tag" volume of this tag actor is waiting on in this stage, if any.  The
    # trigger watches an NPC, so the volume itself does the box test (actors/npc_tag.gd); all
    # it needs from here is which actor to watch, the ground window, and the story gate.
    if tag == "":
        return {}
    var here := current_stage_key()
    for step in story.get("steps", []):
        var nt = step.get("npc_tag")
        if not (nt is Dictionary):
            continue
        if str(nt.get("tag", "")) != tag:
            continue
        var st := sfield(step, "stage")
        if st != "" and st != here:
            continue
        if story_done(sfield(step, "id")) or not _story_bits_ok(step):
            continue
        return step
    return {}

func story_hit_steps() -> Array:
    # Every "hit" step whose object belongs in this stage and is still standing.  The decomp
    # builds the Ajav wall only when check_ev() (ENDLESS_NIGHT) is true and its own switch is
    # not set yet - which is exactly requires_bits plus the switch below.
    var out: Array = []
    var here := current_stage_key()
    for step in story.get("steps", []):
        var hit = step.get("hit")
        if not (hit is Dictionary):
            continue
        var st := sfield(step, "stage")
        if st != "" and st != here:
            continue
        if story_done(sfield(step, "id")) or not _story_bits_ok(step):
            continue
        var sw = hit.get("switch")
        var rm := 0
        if hit.get("room") != null:
            rm = int(hit["room"])
        if sw != null and is_switch(rm, int(sw)):
            continue
        out.append(step)
    return out

func story_npc_tick() -> void:
    # an NPC orders its own event: Aryll greets Link in his new clothes when he comes within
    # 200 units, Tetra starts the dock conversation the moment her story-state copy is placed
    if event_running or cutscene_running() or dialog_open:
        return
    var lk := player()
    if lk == null:
        return
    var here := current_stage_key()
    for step in story.get("steps", []):
        var near = step.get("near")
        if not (near is Dictionary):
            continue
        var id := str(step.get("id", ""))
        if story_done(id) or not _story_bits_ok(step):
            continue
        var st := str(step.get("stage", ""))
        if st != "" and st != here:
            continue
        var who := _find_actor(str(near.get("actor", "")))
        if who == null:
            continue
        var r := float(near.get("radius", 0.0))
        if r > 0.0 and who.global_position.distance_to(lk.global_position) > r:
            continue
        _mark_story_done(id)
        var ev := sfield(step, "event")
        print("gcrip story: ", near.get("actor", "?"), " orders ", id, " (event ", ev, ")")
        if ev != "" and events.has(ev) and run_event(ev):
            return
        story_event_done(id)
        return

func story_object_tick() -> void:
    # a placed object orders its own event when its OWN condition comes true: the courtyard warp
    # polls Link's XZ distance (daWarphr_c::check_warp), the throne-room blocks and the Hero's
    # statue watch their own state.  Unlike a TagEv this is a per-tick predicate, not a volume.
    if event_running or cutscene_running() or dialog_open:
        return
    var here := current_stage_key()
    for step in story.get("steps", []):
        var obj = step.get("object")
        if not (obj is Dictionary):
            continue
        var id := sfield(step, "id")
        if story_done(id) or not _story_bits_ok(step):
            continue
        var st := sfield(step, "stage")
        if st != "" and st != here:
            continue
        if not _story_object_ok(obj):
            continue
        _mark_story_done(id)
        var ev := sfield(step, "event")
        print("gcrip story: ", obj.get("actor", "?"), " orders ", id, " (event ", ev, ")")
        if ev != "" and events.has(ev) and run_event(ev):
            return
        story_event_done(id)
        return

func _story_object_ok(obj: Dictionary) -> bool:
    # every key the block carries must hold; a block with no test fires as soon as the object
    # is placed.  Missing object -> never: the step belongs to a placement this stage has not got.
    var pos := story_object_pos(str(obj.get("actor", "")))
    if pos == STORY_OBJ_NOWHERE:
        return false
    var lk := player()
    var near_r := float(obj.get("radius", 0.0))
    var far_r := float(obj.get("min_radius", 0.0))
    if near_r > 0.0 or far_r > 0.0:
        if lk == null:
            return false
        # "ship": the real test measures to the boat and only counts while Link is aboard
        var from: Vector3 = lk.global_position
        if bool(obj.get("ship", false)):
            var boat = lk.get("ship")
            if boat == null or not is_instance_valid(boat):
                return false
            from = boat.global_position
        var d := _story_object_dist(pos, from, bool(obj.get("xz", true)))
        if near_r > 0.0 and d > near_r:
            return false
        if far_r > 0.0 and d < far_r:
            return false
    var sw = obj.get("switch")
    if sw != null and not is_switch(int(obj.get("room", 0)), int(sw)):
        return false
    var item := str(obj.get("item", ""))
    if item != "" and not has_item(item):
        return false
    if bool(obj.get("swing", false)):
        # .call(): player() is typed Node3D, and swinging() lives on the player script
        if lk == null or not lk.has_method("swinging") or not bool(lk.call("swinging")):
            return false
    return true

func _story_object_dist(a: Vector3, b: Vector3, xz: bool) -> float:
    if xz:
        return Vector2(a.x - b.x, a.z - b.z).length()
    return a.distance_to(b)

func story_object_pos(actor: String) -> Vector3:
    # MtryB / YLzou / Ghrwp carry no behaviour script, so stage.gd never wraps them into a node:
    # the placement records in stage_data.json are the only thing that knows where they stand.
    # One object can be placed several times (Hyroom has three MtryB blocks) and in the game each
    # copy polls its own condition, so the copy nearest Link is the one that answers here.
    if actor == "":
        return STORY_OBJ_NOWHERE
    var found: Array[Vector3] = []
    var live := _find_actor(actor)
    if live != null:
        found.append(live.global_position)
    var keys: Array = []
    var cs := get_tree().current_scene
    if cs != null:
        keys.append(String(cs.name))
    var key := current_stage_key()
    if not keys.has(key):
        keys.append(key)
    for k in keys:
        var info: Dictionary = stage_data.get(k, {})
        for rec in info.get("actors", []):
            if str(rec.get("actor", "")) != actor:
                continue
            var pt = rec.get("pos")
            if pt is Array and (pt as Array).size() == 3:
                found.append(Vector3(float(pt[0]), float(pt[1]), float(pt[2])))
    if found.is_empty():
        return STORY_OBJ_NOWHERE
    var lk := player()
    if lk == null:
        return found[0]
    var best: Vector3 = found[0]
    for cand in found:
        if cand.distance_to(lk.global_position) < best.distance_to(lk.global_position):
            best = cand
    return best

func telescope_look(eye: Vector3, dir: Vector3) -> bool:
    # Link is looking down the Telescope: a story step whose "look" target is inside the scope
    # takes over (the opening's Quill watch, which is what sends the Helmaroc over the island)
    if event_running or cutscene_running():
        return false
    var here := current_stage_key()
    for step in story.get("steps", []):
        var look = step.get("look")
        if not (look is Dictionary):
            continue
        var id := str(step.get("id", ""))
        if story_done(id) or not _story_bits_ok(step):
            continue
        var st := str(step.get("stage", ""))
        if st != "" and st != here:
            continue
        var target := _find_actor(str(look.get("actor", "")))
        if target == null:
            continue
        var to: Vector3 = target.global_position + Vector3(0, float(look.get("y", 0.0)), 0) - eye
        if to.length() < 1.0:
            continue
        if rad_to_deg(dir.angle_to(to.normalized())) > float(look.get("half_angle", 45.0)):
            continue
        _mark_story_done(id)
        var also := str(look.get("also_done", ""))
        if also != "":
            _mark_story_done(also)
            story_event_done(also)      # the watch itself raises its bit (0x0310)
        var ev := sfield(step, "event")
        print("gcrip story: telescope -> ", id, " (event ", ev, ")")
        if ev != "" and events.has(ev) and run_event(ev):
            return true
        story_event_done(id)
        return true
    return false

# ---- conducting: the Earth / Wind temple duets (d_a_obj_mknjd.cpp)

# setTactZev's melody number is the save file's tact index (dComIfGs_isTact):
#   0 Wind's Requiem   1 Ballad of Gales   2 Command Melody
#   3 Earth God's Lyric   4 Wind God's Aria   5 Song of Passing
# A tablet demands 3 when prm_get_Type() is 0 and 4 when it is 1 - nothing else will do.
const CONDUCT_SONGS := ["Wind's Requiem", "Ballad of Gales", "Command Melody",
                        "Earth God's Lyric", "Wind God's Aria", "Song of Passing"]
const CONDUCT_RANGE := 800.0            # absXZ < 800.0f, for Link AND for the partner
const CONDUCT_SIDE := PI / 2.0          # rotDiff has to fall outside +/-0x4000
# dComIfGp_getCb1Player() is Medli on the Earth side and Makar on the Wind side; the
# placement data calls them Md1 and Cb1
const CONDUCT_PARTNERS := {"Edaichi": "Md1", "M_Dai": "Md1", "Ekaze": "Cb1", "kaze": "Cb1"}
const CONDUCT_FOLLOW_STOP := 300.0      # how close behind Link the partner tags along
const CONDUCT_FOLLOW_SPEED := 90.0      # per story tick (15 frames): a walk, so she lags
const CONDUCT_FOLLOW_WARP := 2000.0     # rooms apart: let her rejoin him off-screen

var conduct_escort := ""

func conduct_tablets() -> Array:
    # every MknjD placed in this stage, with the facing and the melody its params give it
    var out: Array = []
    var info: Dictionary = stage_data.get(current_stage_key(), {})
    for rec in info.get("actors", []):
        if not (rec is Dictionary) or str(rec.get("actor", "")) != "MknjD":
            continue
        var pos: Array = rec.get("pos", [])
        if pos.size() < 3:
            continue
        var params := int(rec.get("params", 0))
        var song := 3
        if ((params >> 16) & 1) == 1:
            song = 4                    # prm_get_Type: PRM_TYPE_S 0x10, PRM_TYPE_W 0x01
        var room := -1
        if rec.get("room") != null:
            room = int(rec["room"])
        out.append({
            "node": str(rec.get("node", "?")),
            "pos": Vector3(float(pos[0]), float(pos[1]), float(pos[2])),
            "angle": deg_to_rad(float(rec.get("rot_y_deg", 0.0))),
            "song": song,
            "room": room,
        })
    return out

func _conduct_side_ok(from: Vector3, tablet: Dictionary) -> bool:
    # cM_atan2s(tablet - body) - tablet.angle.y must land outside +/-0x4000, i.e. the body
    # stands on the side the tablet's face looks at rather than round behind it
    var pos: Vector3 = tablet["pos"]
    var d := pos - from
    return absf(wrapf(atan2(d.x, d.z) - float(tablet["angle"]), -PI, PI)) > CONDUCT_SIDE

func conduct_tablet(link: Node3D) -> Dictionary:
    # Act_c::Execute case 0: the nearest tablet that would accept Link's baton
    var best: Dictionary = {}
    if link == null:
        return best
    var best_d := CONDUCT_RANGE
    for t in conduct_tablets():
        var pos: Vector3 = t["pos"]
        var to := pos - link.global_position
        var xz := Vector2(to.x, to.z).length()
        if xz >= CONDUCT_RANGE or xz > best_d:
            continue
        if not _conduct_side_ok(link.global_position, t):
            continue
        best = t
        best_d = xz
    return best

func conduct_key(step: Dictionary, tablet: Dictionary) -> String:
    # one mined step covers BOTH inner tablets of a temple, so each tablet keeps its own
    # done key and the second one still works
    return "%s@%s" % [sfield(step, "id"), str(tablet.get("node", "?"))]

func conduct_step(tablet: Dictionary) -> Dictionary:
    # the conduct step of this stage that is still waiting on this particular tablet
    var here := current_stage_key()
    var fallback: Dictionary = {}
    for st in story.get("steps", []):
        var trig = st.get("trigger", {})
        if not (trig is Dictionary) or str(trig.get("kind", "")) != "conduct":
            continue
        var step: Dictionary = st
        if sfield(step, "stage") != here:
            continue
        if story_done(conduct_key(step, tablet)) or not _story_bits_ok(step):
            continue
        var srm := -1
        if step.get("room") != null:
            srm = int(step["room"])
        if srm == int(tablet.get("room", -1)):
            return step
        if fallback.is_empty():
            fallback = step
    return fallback

func conduct_pending() -> bool:
    for t in conduct_tablets():
        if not conduct_step(t).is_empty():
            return true
    return false

func conduct_play(link: Node3D, song: int) -> bool:
    # Link finished a melody with the baton up.  True when a tablet answered it - with its
    # DEMO on a good placement, or with its ERROR on a bad one.
    if link == null or event_running or cutscene_running():
        return false
    var t := conduct_tablet(link)
    if t.is_empty():
        return false
    var want := int(t["song"])
    if song != want:
        # setTactZev asks for one melody and one only; the tablet ignores every other
        print("gcrip conduct: ", t["node"], " ignores ", CONDUCT_SONGS[song],
              " - it wants ", CONDUCT_SONGS[want])
        return false
    var step := conduct_step(t)
    if step.is_empty():
        print("gcrip conduct: ", t["node"], " has nothing left to open")
        return false
    var ev := sfield(step, "event")
    # Act_c::Execute case 2: re-test the pair now that the CHECK event has started
    var pname := str(CONDUCT_PARTNERS.get(current_stage_key(), ""))
    var partner := _find_actor(pname)
    var bad := ""
    if partner == null:
        bad = "nobody is here to sing the other part"
    else:
        var gap := link.global_position - partner.global_position
        if Vector2(gap.x, gap.z).length() >= CONDUCT_RANGE:
            bad = "%s is too far from Link" % pname
        elif not _conduct_side_ok(partner.global_position, t):
            bad = "%s is on the wrong side of the tablet" % pname
    if bad != "":
        var err := ev.replace("_DEMO", "_ERROR")
        print("gcrip conduct: bad placement - ", bad, " (", err, ")")
        if err != ev and events.has(err) and run_event(err):
            return true
        show_text("The duet falls apart - " + bad + ".")
        return true
    _mark_story_done(conduct_key(step, t))
    print("gcrip conduct: ", CONDUCT_SONGS[song], " at ", t["node"], " -> ",
          sfield(step, "id"), " (event ", ev, ")")
    if ev != "" and events.has(ev) and run_event(ev):
        return true     # the runner raises the step's bits when the event finishes
    story_event_done(sfield(step, "id"))
    return true

func conduct_tick() -> void:
    # No mined step hands over the baton itself, so it joins the X rotation as soon as a
    # duet step's own bit test says Link has learned one of the melodies (0x2E04 / 0x2E02).
    if not has_item("windwaker"):
        for st in story.get("steps", []):
            var trig = st.get("trigger", {})
            if not (trig is Dictionary) or str(trig.get("kind", "")) != "conduct":
                continue
            if _story_bits_ok(st):
                give_item("windwaker")
                break
    conduct_partner_tick()

func _conduct_ground(node: Node3D, to: Vector3) -> void:
    var probe := to + Vector3(0, 150.0, 0)
    var q := PhysicsRayQueryParameters3D.create(probe, probe + Vector3(0, -800.0, 0), 1)
    var hit := node.get_world_3d().direct_space_state.intersect_ray(q)
    if hit:
        var land: Vector3 = hit["position"]
        to.y = land.y
    node.global_position = to

func conduct_partner_tick() -> void:
    # dComIfGp_getCb1Player(): Medli and Makar escort Link through these stages, and the
    # two-body test means nothing if the partner never moves.  This is the whole escort we
    # model: while a duet is pending she walks after him, slower than he walks, so bringing
    # her round to the right side of the tablet really does take a moment.
    if event_running or cutscene_running() or dialog_open:
        return
    var here := current_stage_key()
    var pname := str(CONDUCT_PARTNERS.get(here, ""))
    if pname == "":
        return
    var lk := player()
    var partner := _find_actor(pname)
    if lk == null or partner == null or not conduct_pending():
        return
    var to := lk.global_position - partner.global_position
    var xz := Vector2(to.x, to.z)
    if xz.length() <= CONDUCT_FOLLOW_STOP:
        return
    if conduct_escort != here:
        conduct_escort = here
        print("gcrip conduct: ", pname, " falls in behind Link in ", here)
    var dir := xz.normalized()
    var walk := Vector3(dir.x, 0.0, dir.y)
    if xz.length() > CONDUCT_FOLLOW_WARP:
        _conduct_ground(partner, lk.global_position - walk * CONDUCT_FOLLOW_STOP)
        return
    if absf(to.y) > 400.0:
        return          # a floor apart: do not walk her through the geometry
    _conduct_ground(partner, partner.global_position + walk * CONDUCT_FOLLOW_SPEED)

func conduct_pose(step: Dictionary, bad_partner := false) -> Dictionary:
    # Put Link 400 units out on the side the tablet's face looks at (which is the placement
    # case 0 accepts) and the partner at his shoulder - or, with bad_partner, round the far
    # side, which is exactly what case 2 answers with MKNJD_*_ERROR.
    var lk := player()
    if lk == null:
        return {}
    var srm := -1
    if step.get("room") != null:
        srm = int(step["room"])
    var pick: Dictionary = {}
    for t in conduct_tablets():
        if pick.is_empty():
            pick = t
        if int(t.get("room", -1)) == srm:
            pick = t
            break
    if pick.is_empty():
        return {}
    var a := float(pick["angle"])
    var u := Vector3(sin(a), 0.0, cos(a))
    var pos: Vector3 = pick["pos"]
    lk.global_position = pos + u * 400.0 + Vector3(0, 30.0, 0)
    lk.set("facing", wrapf(a + PI, -PI, PI))
    var partner := _find_actor(str(CONDUCT_PARTNERS.get(current_stage_key(), "")))
    if partner != null:
        var side: Vector3 = -u if bad_partner else u
        partner.global_position = pos + side * 300.0 + Vector3(0, 30.0, 0)
    return pick

func _conduct_tick() -> void:
    # --conduct: hand Link the baton, stand the pair at this stage's tablet, and conduct
    give_item("windwaker")
    var here := current_stage_key()
    var step: Dictionary = {}
    for st in story.get("steps", []):
        var trig = st.get("trigger", {})
        if not (trig is Dictionary) or str(trig.get("kind", "")) != "conduct":
            continue
        if sfield(st, "stage") == here:
            step = st
            break
    if step.is_empty():
        print("gcrip conduct: no duet step is mined for ", here)
        get_tree().quit()
        return
    for b in step.get("requires_bits", []):
        var bid := _bit_value(b)
        if bid != 0 and not event_bit(bid):
            set_event_bit(bid)      # the harness starts at the step, not at the whole game
    var t := conduct_pose(step, conduct_bad)
    if t.is_empty():
        print("gcrip conduct: no MknjD tablet is placed in ", here)
        get_tree().quit()
        return
    var lk := player()
    var pname := str(CONDUCT_PARTNERS.get(here, ""))
    var partner := _find_actor(pname)
    var ppos: String = str(partner.global_position.round()) if partner != null else "(absent)"
    print("gcrip conduct: ", sfield(step, "id"), " tablet ", t["node"], " wants ",
          CONDUCT_SONGS[int(t["song"])], "; Link ", lk.global_position.round(),
          "   ", pname, " ", ppos)
    if lk.has_method("conduct_pick"):
        lk.conduct_pick(int(t["song"]))
    if not conduct_play(lk, int(t["song"])):
        print("gcrip conduct: the tablet did not answer - step blocked")
        get_tree().quit()

func _find_actor(name: String) -> Node3D:
    if name == "":
        return null
    for grp in ["interact", "enemy"]:
        for n in get_tree().get_nodes_in_group(grp):
            if is_instance_valid(n) and str(n.get("actor")) == name:
                return n
    return null

func _npc_spawn_bits(actor: String) -> void:
    # some NPCs raise a flag simply by being placed (Sturgeon's type-1 variant sets 0x0502);
    # their own later lines are conditioned on it
    var info: Dictionary = npc_dialogue.get(actor, {})
    for b in info.get("spawn_bits", []):
        var id := _bit_value(b)
        if id != 0 and not event_bit(id):
            set_event_bit(id)

func _dlg_cond_ok(c: Dictionary) -> bool:
    for b in c.get("bits", []):
        if not event_bit(_bit_value(b)):
            return false
    for b in c.get("not_bits", []):
        if event_bit(_bit_value(b)):
            return false
    for it in c.get("needs", []):
        if not has_item(str(it)):
            return false
    for it in c.get("not_needs", []):
        if has_item(str(it)):
            return false
    var alts: Array = c.get("type_conds", [])
    if not alts.is_empty():
        # the NPC's "type" is a placement variant: any of the listed ones will do
        var any_ok := false
        for t in alts:
            if _dlg_cond_ok(t):
                any_ok = true
                break
        if not any_ok:
            return false
    return true

func _npc_rule_messages(actor: String, info: Dictionary) -> Array:
    # the mined story-conditional lines: once their event bits / items are in place they beat
    # the fresh-file conversation, so Grandma stops asking for Aryll after the pirates take her
    var said: Dictionary = save.get("npc_said", {})
    var best: Dictionary = {}
    var best_score := -1
    for rule in info.get("rules", []):
        var phase := str(rule.get("phase", ""))
        var key: String = actor + "#" + str(rule.get("key", ""))
        if phase == "first" and said.has(key) and not bool(rule.get("solo", false)):
            continue        # its "repeat" half takes over from here
        var pair := str(rule.get("pair_key", ""))
        if phase == "repeat" and pair != "" and not said.has(actor + "#" + pair):
            continue        # never played the first half of this pair
        if not _dlg_cond_ok(rule):
            continue
        var sc := int(rule.get("score", 0))
        if sc >= best_score:   # ties go to the later rule: the list runs in story order
            best_score = sc
            best = rule
    if best_score < 0:
        return []
    said[actor + "#" + str(best.get("key", ""))] = true
    save["npc_said"] = said
    var out: Array = []
    for id in best.get("ids", []):
        if messages.has(int(id)):
            out.append(int(id))
    return out

func npc_messages(actor: String) -> Array:
    # first conversation per NPC from the decomp sweep (data/ww_npc_dialogue.json)
    # "first" is a list of talk sessions (successive talks; the NPC remembers it was talked to)
    var info: Dictionary = npc_dialogue.get(actor, {})
    var by_story := _npc_rule_messages(actor, info)
    if not by_story.is_empty():
        return by_story
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
        dialog.closed.connect(func():
            dialog_open = false
            dialog_closed_frame = Engine.get_physics_frames())

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
        if PRESET_PADS.has(guid) and not cfg.get_value("prefer", guid, false):
            Input.add_joy_mapping(PRESET_PADS[guid], true)
            print("gcrip: pad ", Input.get_joy_name(id), " -> built-in DragonRise mapping (A=b2 B=b3 X=b1 Y=b0)")
        elif cfg.has_section_key("mappings", guid):
            Input.add_joy_mapping(cfg.get_value("mappings", guid), true)
            print("gcrip: pad ", Input.get_joy_name(id), " -> calibrated mapping from ", PAD_CFG)
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
    toon_input(event)
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
    if stage_data.has(dest_stage) and not playable(dest_stage):
        print("gcrip: refusing to warp to ", dest_stage, " - it has no spawn point")
        return
    if Time.get_ticks_msec() - last_warp_ms < 1500:
        return  # just arrived; don't bounce straight back through the door
    var path := "res://scenes/%s.tscn" % dest_stage
    if not ResourceLoader.exists(path):
        print("gcrip: stage not exported: ", dest_stage,
              "  (gcrip godot <ripdir> ", dest_stage, ")")
        return
    last_warp_ms = Time.get_ticks_msec()
    # a cutscene or text box must not outlive its stage (Link would stay frozen)
    if event_runner and is_instance_valid(event_runner) and event_runner.has_method("abort"):
        event_runner.abort()
    if cutscene and is_instance_valid(cutscene):
        cutscene.abort()
    event_running = false
    clear_event_cam()
    dialog_open = false
    save_game("warp")
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
        var p := Vector3(best["pos"][0], best["pos"][1] + 30.0, best["pos"][2])
        # NOTE: a raycast on this frame always misses - the scene was added this frame and the
        # physics server has not registered its bodies yet.  So the real check is the arrival
        # guard below, which runs once physics is live.  This one only helps on a re-entry.
        if not has_ground(p):
            for sp in info.get("spawns", []):
                var q := Vector3(sp["pos"][0], sp["pos"][1] + 30.0, sp["pos"][2])
                if has_ground(q):
                    p = q
                    break
        arrive_from = p
        arrive_frames = ARRIVE_GUARD_FRAMES
        arrive_phys = Engine.get_physics_frames()
        player.global_position = p
        player.velocity = Vector3.ZERO
        player.start_pos = player.global_position
        # face the way the PLYR entry says (into the room / away from the door) and put the
        # camera behind that
        # PLYR rot_y is the way Link faces on arrival (door spawns point into the room)
        var f := deg_to_rad(float(best.get("rot_y_deg", 0.0)))
        player.set_deferred("facing", f)   # after the Player's own _ready, which resets it
        if player.has_method("snap_camera_behind"):
            player.call_deferred("snap_camera_behind")
    var spawn_event := ""
    if best != null:
        var ev := int(best.get("event", 255))
        var table: Array = info.get("event_table", [])
        if ev >= 0 and ev < table.size():
            spawn_event = str(table[ev])
    if bool(pending.get("restore", false)):
        _restore_position()
    pending = {}
    if spawn_event != "" and events.has(spawn_event):
        await get_tree().physics_frame
        run_event(spawn_event)

const ARRIVE_GUARD_FRAMES := 45
var arrive_from := Vector3.ZERO   # where the spawn put Link, so a fall through it is obvious
var arrive_frames := 0
var arrive_phys := 0

func _arrival_guard() -> void:
    # For the first frames after a warp, watch for Link dropping through the world.  The check
    # cannot be done at placement time: the scene is added on that frame and the physics server
    # has not registered its collision yet, so every raycast comes back empty - which is exactly
    # how a door could drop you into a void even though the room has a floor.
    if arrive_frames <= 0:
        return
    # wait for physics to have stepped at least twice on the new scene, then check once
    if Engine.get_physics_frames() < arrive_phys + 2:
        return
    arrive_frames = 0
    var lk := player()
    if lk == null:
        return
    if scripted():
        print("gcrip arrive: guard at ", arrive_from.round(), " ground=", ground_under(arrive_from),
              " link=", lk.global_position.round(), " under=", ground_under(lk.global_position))
    if has_ground(arrive_from) or has_ground(lk.global_position):
        return          # the spawn does have a floor: nothing to rescue
    var info: Dictionary = stage_data.get(current_scene_key(), {})
    for sp in info.get("spawns", []):
        var q := Vector3(sp["pos"][0], sp["pos"][1] + 30.0, sp["pos"][2])
        if has_ground(q):
            print("gcrip: spawn had no floor under it - moving Link to a spawn that does")
            lk.global_position = q
            lk.velocity = Vector3.ZERO
            lk.start_pos = q
            arrive_from = q
            arrive_frames = 0
            return

func safe_respawn(fallback: Vector3) -> Vector3:
    # Link fell out of the world.  Putting him back exactly where he started loops for ever if
    # THAT is the spot with the hole (Pfigure's figureG doorway), so prefer a spawn with a floor.
    if has_ground(fallback):
        return fallback
    var info: Dictionary = stage_data.get(current_scene_key(), {})
    for sp in info.get("spawns", []):
        var q := Vector3(sp["pos"][0], sp["pos"][1] + 30.0, sp["pos"][2])
        if has_ground(q):
            print("gcrip: fell through the spawn floor - respawning at a spawn that has one")
            return q
    return fallback

func current_scene_key() -> String:
    var cs := get_tree().current_scene
    return String(cs.name) if cs else ""

func has_ground(p: Vector3) -> bool:
    return ground_under(p) != ""

func ground_under(p: Vector3) -> String:
    var cs := get_tree().current_scene as Node3D
    if cs == null:
        return "?"
    var space := cs.get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(p + Vector3(0, 50.0, 0), p - Vector3(0, 6000.0, 0), 1 | 2)
    var hit := space.intersect_ray(q)
    if hit.is_empty():
        return ""
    return "%s@%.0f" % [hit.collider.name if hit.collider else "?", hit.position.y]
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
var tbox_no := -1
var opened := false
var mesh: Node3D = null
var facing := 0.0

func setup(rot_z: int, mesh_node: Node3D, rot_y_deg: float, params := 0) -> void:
    item_id = (rot_z >> 8) & 0xFF
    tbox_no = (params >> 7) & 0x1F   # d_a_tbox: which chest bit this one owns in the save
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
    Game.story_chest_opened(item_id)
    Game.story_item_collected(item_id, "")
    if tbox_no >= 0:
        Game.story_timer_beaten(tbox_no)
"""

_ACTOR_PICKUP_GD = """extends Node3D
# gcrip: a placed quest pickup - the Deku Leaf on the Ojtree poles (d_a_deku_item.cpp) and the
# boss-item stand in a cleared boss room (d_a_boss_item.cpp). Unlike the d_a_item collectibles
# these are one-off story items, and they only exist while their own mined step is reachable
# and unfinished: daDekuItem_c::_create fails on both its collected bit and !isEventBit(0x1801),
# so before the Deku Tree has spoken the leaf is not in the room at all.
# Touching the 50-radius / 100-tall cylinder is the whole interaction
# (d_a_deku_item.cpp:174-208 mode_getdemo -> fopAcM_createItemForTrBoxDemo).

const GET_R := 50.0
const GET_H := 100.0
const LINK_R := 25.0                 # Link's own body radius, so a brush past counts
const SPIN := 799 * PI / 32768.0     # the same 799 s16/frame idle spin as d_a_item

var actor := ""
var params := 0
var mesh: Node3D = null
var step: Dictionary = {}
var item_no := -1
var taken := false

func setup(a: String, p: int, mesh_node: Node3D) -> void:
    actor = a
    params = p
    mesh = mesh_node
    step = Game.story_item_step(actor)
    for n in step.get("item_nos", []):
        item_no = int(n)
        break
    # a collected pickup stays collected: the story step remembers the ones the graph names,
    # the per-scene flag (like the chests' tbox bits) the ones it does not
    var key := "pickup:%s:%s" % [get_tree().current_scene.name, name]
    set_meta("save_key", key)
    if Game.save.get("flags", {}).has(key) or not Game.story_pickup_ok(step):
        queue_free()
        return
    add_to_group("pickup")     # so --control can answer "is the leaf there yet?"

func _physics_process(_delta: float) -> void:
    if taken:
        return
    if mesh:
        mesh.rotation.y += SPIN
    var link := Game.player()
    if link == null or Game.event_running or Game.cutscene_running():
        return
    var d: Vector3 = link.global_position - global_position
    if d.y < -GET_H or d.y > GET_H:
        return
    if Vector2(d.x, d.z).length() > GET_R + LINK_R:
        return
    _collect(link)

func _collect(link: Node3D) -> void:
    taken = true
    if not Game.save.has("flags"):
        Game.save["flags"] = {}
    Game.save["flags"][get_meta("save_key")] = true
    Game.burst(global_position + Vector3(0, 60, 0), Color(1.0, 0.95, 0.6))
    var pick = step.get("pickup", {})
    var heart: int = int(pick.get("heart", 0)) if pick is Dictionary else 0
    if heart > 0:
        # a Heart Container: one more container, then the refill the boss item comes with
        link.set("hearts_max", int(link.get("hearts_max")) + heart)
        link.call("heal", heart)
    if item_no >= 0:
        Game.show_message(101 + item_no)   # the same item-get text table the chests use
    # the step hands the item itself over (its item_key) and raises the bits it sets
    Game.story_item_collected(item_no, actor)
    queue_free()
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
# near its spawn; others stand still. Talk with A from the actor's own dAttention_c TALK
# distance (300 for Grandma, 400 for Sturgeon): plays the message
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
var actor := ""

func setup(actor_name: String, _p: int, mesh_node: Node3D, rot_y_deg: float) -> void:
    actor = actor_name
    mesh = mesh_node
    home = global_position
    facing = deg_to_rad(rot_y_deg)
    home_facing = facing
    swimmer = actor == "NpcSo"
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

func talk_range() -> float:
    # dAttention_c distances[TALK] for this actor, mined into ww_npc_dialogue.json.  A flat 150
    # put half the villagers out of reach: Grandma really answers from 300 units away, Rose from
    # 350, Sturgeon from 400.
    var info: Dictionary = Game.npc_dialogue.get(actor, {})
    var td = info.get("talk_dist")
    if td is Dictionary and td.get("xz_max") != null:
        return float(td["xz_max"])
    return 200.0

func interact_prompt(link: Node3D) -> String:
    var to: Vector3 = link.global_position - global_position
    if absf(to.y) > 300.0:
        return ""            # distances[TALK].dy: no talking to someone a floor away
    return "Talk" if Vector2(to.x, to.z).length() < talk_range() else ""

func interact(link: Node3D) -> void:
    var to_link := link.global_position - global_position
    facing = atan2(to_link.x, to_link.z)
    # the mined opening graph gets first refusal: talking to this actor may BE a story step
    if Game.story_talk(actor):
        return
    # first meeting: the NPC's own event (e.g. Ji1_StartSpeak) plays before the lines
    for suffix in ["_StartSpeak", "_Start", "_TALK", "_Talk", "_Speak"]:
        var ev: String = actor + suffix
        var played: Dictionary = Game.save.get("talk_events", {})
        if Game.events.has(ev) and not played.has(ev):
            played[ev] = true
            Game.save["talk_events"] = played
            if Game.run_event(ev) and Game.event_runner:
                Game.event_runner.finished.connect(_talk)
                return
            break
    _talk()

func event_talk(on: bool) -> void:
    talking = on
    if anim:
        if on and talk_clip != "":
            anim.play(talk_clip, 0.2)
        elif not on and wait_clip != "":
            anim.play(wait_clip, 0.3)

func _talk() -> void:
    talking = true
    if anim and talk_clip != "":
        anim.play(talk_clip, 0.2)
    # ask NOW: the conditional rules read the story bits and the items Link is carrying at
    # this moment, and they mark themselves said.  Choosing at spawn froze the answer to
    # whatever was true when the room loaded.
    messages = Game.npc_messages(actor)
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
        Game.burst(global_position + Vector3(0, 50, 0), Color(0.502, 0.125, 0.392))
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
var mode := "stages"

func _ready() -> void:
    layer = 45
    process_mode = Node.PROCESS_MODE_ALWAYS
    _fill()

func _fill() -> void:
    list.clear()
    keys = []
    if mode == "stages":
        var names: Dictionary = Game.stage_names
        for k in Game.stage_data.keys():
            if Game.playable(k):
                keys.append(k)
        keys.sort_custom(func(a, b): return str(names.get(a, a)).to_lower() < str(names.get(b, b)).to_lower())
        for k in keys:
            var n: String = str(names.get(k, ""))
            list.add_item((n + "   (" + k + ")") if n != "" else k)
        title.text = "Where to?   %d stages   -   Enter / A: go   Tab: events / story / game   Esc: back" % keys.size()
    elif mode == "events":
        keys = Game.events.keys()
        for k in keys:
            var ev: Dictionary = Game.events[k]
            var cast: Array = []
            for sf in ev.get("actors", []):
                cast.append(str(sf.get("name", "")))
            list.add_item("%s   [%s]" % [k, ", ".join(cast)])
        title.text = "Cutscenes here   %d events   -   Enter / A: play   Tab: story   Esc / Start: back" % keys.size()
    elif mode == "story":
        var cs := get_tree().current_scene
        var stage := String(cs.name) if cs else ""
        keys = Game.story_states(stage)
        var room := -1
        var ri := stage.rfind("_r")
        if ri >= 0 and stage.substr(ri + 2).is_valid_int():
            room = int(stage.substr(ri + 2))
        var live := Game.story_layer(stage, room)
        for rule in keys:
            var bits: Array = []
            for t in rule.get("tests", []):
                bits.append(("" if bool(t[1]) else "not ") + "0x%04X" % int(t[0]))
            var lay := int(rule.get("layer_day", 0))
            list.add_item("layer %d   <- %s%s" % [lay, ", ".join(bits), "   (live)" if lay == live else ""])
        list.add_item("layer %d   <- fresh file (no story bits)   %s" % [
            int(Game.layers.get("default_day", 0)),
            "(live)" if live == int(Game.layers.get("default_day", 0)) else ""])
        keys.append({"tests": [], "reset": true})
        title.text = "Story state of %s   -   Enter / A: apply + reload   Tab: game   Esc: back" % stage
    else:
        keys = ["save", "new"]
        list.add_item("Save game now   (autosaves on every door and every 30 s)")
        list.add_item("New game   (erases the save file)")
        var when := str(Game.save.get("saved_at", "never"))
        title.text = "Game   -   last save: %s   -   hearts %d/%d   rupees %d   -   Tab: stages" % [
            when, int(Game.save.get("hearts", 0)), int(Game.save.get("hearts_max", 0)), int(Game.save.get("rupees", 0))]
    if list.item_count > 0:
        list.select(0)
        list.grab_focus()

func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("pause") or event.is_action_pressed("ui_cancel"):
        Game.close_menu()
        get_viewport().set_input_as_handled()
    elif event.is_action_pressed("item_next"):
        mode = {"stages": "events", "events": "story", "story": "game", "game": "stages"}[mode]
        _fill()
        get_viewport().set_input_as_handled()
    elif event.is_action_pressed("action_a") or event.is_action_pressed("ui_accept"):
        var sel := list.get_selected_items()
        if sel.size() > 0:
            if mode == "story":
                var rule: Dictionary = keys[sel[0]]
                Game.close_menu()
                if bool(rule.get("reset", false)):
                    for r2 in Game.story_states(String(get_tree().current_scene.name)):
                        for t in r2.get("tests", []):
                            Game.clear_event_bit(int(t[0]))
                    Game.reload_stage()
                else:
                    Game.apply_story_state(rule)
                return
            var key := str(keys[sel[0]])
            Game.close_menu()
            if mode == "stages":
                Game.go_to_stage(key)
            elif mode == "events":
                Game.run_event(key)
            elif key == "save":
                Game.save_game("menu")
                Game.show_text("Game saved.")
            else:
                Game.new_game()
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

_TAG_ISLAND_GD = """extends Node3D
# gcrip: TagIsl (d_a_tag_island.cpp) - the volume that plays an island's arrival cutscene the
# first time Link reaches it.  Not a TagEv: its own param layout, its own distance test, and a
# per-type save flag that the demo raises itself so it only ever fires once.
#
# Polled rather than an Area3D: checkArea() is a cylinder test the actor runs every frame, and
# the real one's radius is scale.x * 10000 - a 32000-unit cylinder around Dragon Roost is not
# something the physics server needs to own.

var params := 0
var event_no := 0
var swbit := 0xFF
var type := 0
var radius := 10000.0
var half_h := 10000.0
var table: Array = []
var room := 0
var fired := false

# getArrivalFlag(): the bit each type raises when its demo starts (d_a_tag_island.cpp:85-97)
const ARRIVAL_FLAG := {1: 0x0902, 2: 0x0A20, 3: 0x0A02, 4: 0x1F04, 5: 0x2E04, 6: 0x2E02, 7: 0x3E10}
# makeEvId(): the on-foot variant of each arrival, looked up by NAME (:60-82)
const ON_FOOT := {1: "ARRIVAL_DRG2", 2: "ARRIVAL_FST2", 3: "ARRIVAL_BRK2", 4: "ARRIVAL_TWN2",
                  5: "ARRIVAL_GND2", 6: "ARRIVAL_WND2", 7: "PUROLO_RETURN2"}
# otherCheck(): two islands also wait on a story bit (:100-112)
const OTHER_BIT := {5: 0x1608, 6: 0x1604}

func setup(p: int, r: int, tbl: Array, sc: Array) -> void:
    params = p
    room = r
    table = tbl
    event_no = (p >> 24) & 0xFF
    swbit = (p >> 8) & 0xFF
    type = p & 0xFF
    radius = maxf(float(sc[0]) * 10000.0, 100.0)
    half_h = maxf(float(sc[1]) * 10000.0, 100.0)

func arrival_flag() -> int:
    return int(ARRIVAL_FLAG.get(type, 0))

func event_name() -> String:
    var base := str(table[event_no]) if event_no < table.size() else ""
    var lk := Game.player()
    var aboard: bool = lk != null and lk.get("ship") != null and is_instance_valid(lk.get("ship"))
    if not aboard and ON_FOOT.has(type) and Game.events.has(str(ON_FOOT[type])):
        return str(ON_FOOT[type])
    return base

func arrival_terms() -> bool:
    # arrivalTerms() + otherCheck(), d_a_tag_island.cpp:100-131
    var flag := arrival_flag()
    if flag != 0 and Game.event_bit(flag):
        return false            # already arrived here once
    if OTHER_BIT.has(type) and not Game.event_bit(int(OTHER_BIT[type])):
        return false
    match type:
        4:
            if not Game.night_stop():
                return false
        7:
            if not Game.night_stop() or not Game.has_item("bomb"):
                return false
    return true

func check_area(lk: Node3D) -> bool:
    var d := lk.global_position - global_position
    var dxz := Vector2(d.x, d.z).length()
    return dxz < radius and absf(d.y) <= half_h

func _physics_process(_delta: float) -> void:
    if fired or Game.event_running or Game.cutscene_running() or Game.dialog_open:
        return
    if Engine.get_physics_frames() % 8 != 0:
        return
    var lk := Game.player()
    if lk == null or not check_area(lk):
        return
    if not arrival_terms():
        return
    var ev := event_name()
    if ev == "" or not Game.events.has(ev):
        return
    fired = true
    var flag := arrival_flag()
    if flag != 0:
        Game.set_event_bit(flag)    # demoInitProc(): raised as the demo STARTS (:134-137)
    print("gcrip island: type ", type, " arrival -> ", ev, " (flag 0x%04X)" % flag)
    if swbit != 0xFF:
        Game.set_switch(room, swbit)
    Game.run_event(ev)
"""

_SKYDOME_SHADER = """shader_type spatial;
render_mode unshaded, cull_front, depth_draw_never;
// gcrip: the visible sky - a WW-style gradient with a sun disc at the game's own sun.  It is a
// skybox (the vertex trick pins it to the far plane), so it hides the HDR environment behind it
// while the HDR keeps lighting and reflecting.  The sun here is the DirectionalLight's direction,
// so the painted sun and the cast shadows always agree, and both track the clock.

uniform vec3 zenith : source_color = vec3(0.20, 0.45, 0.75);
uniform vec3 horizon : source_color = vec3(0.75, 0.85, 0.92);
uniform vec3 ground : source_color = vec3(0.30, 0.34, 0.40);
uniform vec3 sun_travel = vec3(0.0, -1.0, 0.0);   // direction the light travels
uniform vec3 sun_color : source_color = vec3(1.0, 0.96, 0.86);
uniform float sun_size = 0.007;    // angular radius, cos space
uniform float nits = 8000.0;

varying vec3 dir;

void vertex() {
    dir = normalize(VERTEX);
    vec4 clip = PROJECTION_MATRIX * MODELVIEW_MATRIX * vec4(VERTEX, 1.0);
    POSITION = clip.xyww;          // z = w -> farthest depth, always behind the scene
}

void fragment() {
    float y = dir.y;
    vec3 sky = y > 0.0
        ? mix(horizon, zenith, pow(clamp(y, 0.0, 1.0), 0.5))
        : mix(horizon, ground, clamp(-y * 4.0, 0.0, 1.0));
    vec3 sun_pos = -normalize(sun_travel);
    float d = dot(dir, sun_pos);
    float disc = smoothstep(1.0 - sun_size, 1.0 - sun_size * 0.25, d);
    float glow = pow(max(d, 0.0), 6.0) * 0.25 + pow(max(d, 0.0), 64.0) * 0.6;
    ALBEDO = vec3(0.0);
    EMISSION = (sky + sun_color * (disc * 4.0 + glow)) * nits;
}
"""

_OCEAN_SHADER = """shader_type spatial;
render_mode cull_disabled, depth_draw_opaque, unshaded;
// gcrip: the Great Sea surface.  The wave sum is daSea_packet_c's, with the four wave rows
// pushed from the SAME const the CPU sea_height() reads, so the boat floats on what you see.
//   y = 1 + sum_i amp_i * scale * cos(k_i * (dx_i*x + dz_i*z) - phase_i(t) + off_i)
// The fragment is the game/film middle ground: the cel ramp still lights the water body
// (the real TEV had no Fresnel at all), but the surface now behaves like water -
//   depth fade   the beach shows through the shallows (hint_depth_texture thickness)
//   absorption   Beer-Lambert: turquoise shallows deepening to the sea colour
//   Fresnel      Schlick, F0=0.02 (IOR 1.333): sky reflection, mirror-like at grazing
//   sun glint    gloss falls with distance - sharp sparkle near, wide sheet at the horizon
//   foam         animated shoreline band + whitecaps on crests, scaled by wave_scale

uniform vec4 wave_a = vec4(2.5, 13600.0, 0.0, 200.0);     // amp, wavelength, phase s16, period
uniform vec4 wave_b = vec4(2.5, 11200.0, 4000.0, 190.0);
uniform vec4 wave_c = vec4(2.5, 8800.0, 8000.0, 210.0);
uniform vec4 wave_d = vec4(2.5, 6400.0, 12000.0, 180.0);
uniform vec4 dir_ab = vec4(0.98, 0.20, 0.20, 0.98);        // (dx,dz) of a, (dx,dz) of b
uniform vec4 dir_cd = vec4(-0.98, 0.20, 0.20, -0.98);
uniform float wave_scale = 30.0;     // the room's wave_max, eased (sea_cur_scale)
uniform float t_frames = 0.0;        // physics frames, the clock sea_height() uses
uniform vec3 sea_day : source_color = vec3(0.16, 0.42, 0.62);
uniform vec3 sea_night : source_color = vec3(0.05, 0.12, 0.24);
uniform vec3 shallow_col : source_color = vec3(0.32, 0.64, 0.66);  // absorption start
uniform float night = 0.0;
uniform vec3 sun_dir = vec3(0.55, -0.72, 0.42);
uniform sampler2D toon_ramp : filter_linear;
uniform vec3 c0 : source_color = vec3(0.42, 0.44, 0.52);
uniform vec3 k0 : source_color = vec3(1.0, 0.94, 0.82);
uniform float nits = 1.0;   // physical units: unshaded output is luminance
// depth-fade distances in world units (100 units ~ 1 m)
// per-channel Beer-Lambert extinction, per world unit (100 units ~ 1 m).  Red dies in
// ~100 units, green ~250, blue ~670 - the turquoise-to-deep-blue gradient comes free.
uniform vec3 absorb_rgb = vec3(0.010, 0.004, 0.0015);
uniform float foam_dist = 90.0;      // shoreline foam band thickness
uniform float fresnel_max = 0.45;    // ceiling on the sky mirror (the game had none at all)
// the sky the water reflects; matches the dome palette (day values, dimmed by `night`)
uniform vec3 sky_zenith : source_color = vec3(0.20, 0.45, 0.75);
uniform vec3 sky_horizon : source_color = vec3(0.70, 0.82, 0.92);
uniform vec3 sun_col : source_color = vec3(1.0, 0.96, 0.86);
uniform sampler2D depth_tex : hint_depth_texture, filter_linear;

varying vec3 w_normal;
varying vec3 w_pos;
varying float v_crest;   // 0..1, how near this vertex is to the wave-sum crest

float wave(vec4 w, vec2 d, vec2 xz, out vec2 grad) {
    float k = 6.28 / w.y;
    float phase = 6.2831853 * (mod(t_frames, w.w) / w.w - 0.5);
    float arg = k * dot(d, xz) - phase + w.z * 6.2831853 / 65536.0;
    float a = w.x * wave_scale;
    grad = -a * sin(arg) * k * d;
    return a * cos(arg);
}

void vertex() {
    vec3 wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    vec2 xz = wp.xz;
    vec2 g, ga, gb, gc, gd;
    float y = 1.0;
    y += wave(wave_a, dir_ab.xy, xz, ga);
    y += wave(wave_b, dir_ab.zw, xz, gb);
    y += wave(wave_c, dir_cd.xy, xz, gc);
    y += wave(wave_d, dir_cd.zw, xz, gd);
    g = ga + gb + gc + gd;
    VERTEX.y = y - (MODEL_MATRIX * vec4(0.0, 0.0, 0.0, 1.0)).y;
    w_normal = normalize(vec3(-g.x, 1.0, -g.y));
    w_pos = vec3(wp.x, y, wp.z);
    v_crest = clamp((y - 1.0) / max(10.0 * wave_scale, 1.0) * 0.5 + 0.5, 0.0, 1.0);
    NORMAL = (inverse(MODEL_MATRIX) * vec4(w_normal, 0.0)).xyz;
}

// cheap animated value noise for the foam edge
float vhash(vec2 q) { return fract(sin(dot(q, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 q) {
    vec2 i = floor(q);
    vec2 f = fract(q);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(vhash(i), vhash(i + vec2(1.0, 0.0)), f.x),
               mix(vhash(i + vec2(0.0, 1.0)), vhash(i + vec2(1.0, 1.0)), f.x), f.y);
}

void fragment() {
    vec3 n = normalize(w_normal);
    if (!FRONT_FACING) { n = -n; }
    // the cel light factor: the ramp is still the diffuse model, as in the real TEV
    float d = clamp(dot(n, -normalize(sun_dir)) * 0.5 + 0.5, 0.0, 1.0);
    float toon = texture(toon_ramp, vec2(d, 0.5)).r;
    vec3 lit = mix(c0, k0, toon);

    // water thickness along the eye ray: scene depth minus our own depth
    float sd = texture(depth_tex, SCREEN_UV).r;
    vec4 vp = INV_PROJECTION_MATRIX * vec4(SCREEN_UV * 2.0 - 1.0, sd, 1.0);
    float scene_d = -vp.z / vp.w;
    float thick = max(scene_d + VERTEX.z, 0.0);   // VERTEX.z is -view depth
    // The sea plane runs UNDER the whole island at y ~ 1, and the beach sits at y ~ 1..7:
    // near-coplanar, so the two z-fight and the sea shimmers across the sand as the grid
    // re-snaps every 800 units.  A transparent surface writes no depth, so nothing else
    // resolves it - drop any water thinner than a plank.  This is also the correct answer
    // physically: there is no water there.
    if (thick < 6.0) {
        discard;
    }
    vec3 transmit = exp(-thick * absorb_rgb);          // per-channel Beer-Lambert
    float shallow = 1.0 - dot(transmit, vec3(0.30, 0.45, 0.25));  // 0 waterline, 1 deep

    // absorption: red dies first, green next, blue last - shallows turn turquoise, then
    // the sea colour takes over
    vec3 deep = mix(sea_day, sea_night, night);
    vec3 body = mix(deep, shallow_col * mix(1.0, 0.25, night), transmit) * lit;

    // Schlick Fresnel against the sky, F0 = 0.02 (IOR 1.333)
    vec3 wv = normalize(CAMERA_POSITION_WORLD - w_pos);
    float cosv = clamp(dot(wv, n), 0.0, 1.0);
    float fres = 0.02 + 0.98 * pow(1.0 - cosv, 5.0);
    vec3 r = reflect(-wv, n);
    float ry = clamp(r.y, 0.0, 1.0);
    // the palette is pushed from the stage and already carries the hour
    vec3 sky = mix(sky_horizon, sky_zenith, pow(ry, 0.5));

    // ROUGHNESS WITH DISTANCE.  A mesh vertex every 800 units cannot carry the ripple that
    // is actually out there, so far water reads as a mirror and Fresnel drives it to a
    // white sheet at the horizon.  Real distant water is rough: the reflection averages
    // over a wide cone of sky AND water, and the specular flattens.  This is the difference
    // between sea and tinfoil.
    float dist = -VERTEX.z;
    float rough = clamp(dist / 35000.0, 0.0, 1.0);
    vec3 deep_ref = mix(sea_day, sea_night, night);
    sky = mix(sky, mix(sky, deep_ref, 0.88), rough);
    // Wind Waker's sea has no Fresnel at all, and its water stays a saturated blue right to
    // the horizon.  Keeping a real Fresnel but capping it is the middle ground: the sheen
    // reads as water up close and never turns the far sea into a white mirror.
    fres = min(fres, fresnel_max) * (1.0 - 0.85 * rough);

    // the sun glint: tight sparkle near the camera, a broad sheet at the horizon
    float gloss = mix(900.0, 90.0, rough);
    float spec = pow(max(dot(r, -normalize(sun_dir)), 0.0), gloss) * (1.0 - night * 0.85);

    // foam: the shoreline band, edge broken by animated noise, plus whitecaps on crests
    vec2 fuv = w_pos.xz * 0.012;
    float fn = vnoise(fuv + vec2(t_frames * 0.010, t_frames * -0.007)) * 0.65
             + vnoise(fuv * 4.7 - vec2(t_frames * 0.016, 0.0)) * 0.35;
    float shore = 1.0 - smoothstep(foam_dist * 0.15, foam_dist, thick);
    float foam = shore * smoothstep(0.28, 0.62, fn * 0.7 + shore * 0.5);
    float caps = smoothstep(0.86, 0.99, v_crest) * clamp(wave_scale / 30.0, 0.0, 1.0);
    foam = clamp(foam + caps * smoothstep(0.45, 0.75, fn), 0.0, 1.0);

    vec3 col = mix(body, sky, fres);
    col += sun_col * spec * (0.05 + fres) * 12.0;
    col = mix(col, vec3(0.94, 0.97, 1.0) * lit, foam);
    ALBEDO = col * nits;

    // transparency: shallows show the beach, deep water is opaque, grazing angles and foam
    // close it up.  Underside (swimming) is a steady translucent tint.
    float a = mix(0.06, 0.94, shallow);
    a = clamp(a + fres * 0.85 + foam, 0.0, 1.0);
    if (!FRONT_FACING) { a = 0.65; }
    ALPHA = a;
}
"""

_FX_SHADER = """shader_type spatial;
render_mode unshaded, blend_mix, depth_draw_never, cull_disabled, billboard_keep_scale, particle_trails;
// gcrip: the JPA TEV preset that 634 of 1091 Wind Waker effects use -
//   out = mix(envColor, prmColor, texture)
// The particle textures are greyscale MASKS (1785 of 1874); the mask is a mix factor between
// two authored colours, not a tint.  Alpha comes from the texture's own alpha times the
// per-particle envelope the CPU side feeds through COLOR.a.

uniform sampler2D mask_tex : source_color, filter_linear;
uniform vec4 prm_color : source_color = vec4(1.0);
uniform vec4 env_color : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform bool additive = false;
uniform float nits = 1.0;   // physical units: unshaded output is luminance

void fragment() {
    vec4 t = texture(mask_tex, UV);
    vec3 rgb = mix(env_color.rgb, prm_color.rgb, t.r);
    float a = t.a * COLOR.a * prm_color.a;
    if (additive) {
        ALBEDO = rgb * a * nits;
        ALPHA = a;
    } else {
        ALBEDO = rgb * nits;
        ALPHA = a;
    }
}
"""

_TOON_SHADER = """shader_type spatial;
render_mode unshaded, cull_back, depth_draw_opaque;
// gcrip: Wind Waker's cel shading, as the game actually builds it.
//   lit = C0 * (1 - toon) + K0 * toon      (TEV stage 0)
//   out = albedo * lit                     (TEV stage 1)
// `toon` is a RAMP LOOKUP indexed by the lit value, not a dot product - the ramp is the
// game's own toon.bti, flat 0 to index 119, a rise to 137, then flat 255.  Unshaded because
// the ramp IS the lighting model; Godot's own light loop would fight it.

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap;
uniform vec4 albedo_col : source_color = vec4(1.0);
uniform bool has_tex = true;
uniform sampler2D toon_ramp : filter_linear;
uniform vec3 sun_dir = vec3(0.55, -0.72, 0.42);
uniform vec3 c0 : source_color = vec3(0.42, 0.44, 0.52);   // shadow / TEV register 0
uniform vec3 k0 : source_color = vec3(1.0, 0.94, 0.82);    // lit / konst 0
uniform float alpha_scissor = 0.0;
// physical light units: an unshaded colour is in NITS.  The stage sets this to the luminance a
// lit diffuse white would have under the current sun, so the toon look matches the exposure.
uniform float nits = 1.0;

varying vec3 world_normal;

void vertex() {
    world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
    // the lit value the ramp is indexed by: a half-Lambert, so back faces sit at the ramp's
    // flat foot rather than clamping to zero
    // a double-sided surface (cull_disabled variant) shows its back face to the camera:
    // flip the normal or the ramp lights it as if it faced away.  No-op when culling is on.
    vec3 wn = normalize(world_normal);
    if (!FRONT_FACING) { wn = -wn; }
    float d = clamp(dot(wn, -normalize(sun_dir)) * 0.5 + 0.5, 0.0, 1.0);
    float toon = texture(toon_ramp, vec2(d, 0.5)).r;
    vec3 lit = mix(c0, k0, toon);
    vec4 base = has_tex ? texture(albedo_tex, UV) * albedo_col : albedo_col;
    if (alpha_scissor > 0.0 && base.a < alpha_scissor) {
        discard;
    }
    ALBEDO = base.rgb * lit * nits;
    // gcrip:alpha
    // The line above is a marker the exporter swaps: the blended variant writes ALPHA there,
    // this one deliberately does not.
    //
    // Assigning ALPHA at all puts a Godot material in the TRANSPARENT queue: no depth write,
    // sorted back-to-front by bounding-box centre.  Writing it unconditionally therefore made
    // every cel-shaded surface in the game transparent, and the whole world only looked right
    // because the ocean happened to be opaque and filled the depth buffer first.  The moment
    // the sea became transparent too it sorted nearest (it follows the camera) and painted
    // over everything below the horizon.  Wind Waker's materials are opaque or alpha-CUTOUT;
    // the cutout is the discard above, and needs no blending.
}
"""

_FLAME_FLICKER_GD = """extends Light3D
# gcrip: a flame wanders around its nominal output - two incommensurate sines, so it never
# visibly repeats.  Works on a spot or an omni.

var _t := 0.0
var _base := -1.0

func _process(delta: float) -> void:
    if _base < 0.0:
        _base = light_intensity_lumens
    _t += delta
    light_intensity_lumens = _base * (1.0 + 0.08 * sin(_t * 9.3) + 0.05 * sin(_t * 23.1 + 1.7))
"""

_HIT_SWITCH_GD = """extends StaticBody3D
# gcrip: an object that reacts to ONE kind of attack and raises a switch.  Not a breakable -
# nothing is destroyed; the switch is the whole point.  See ww_story_labyrinths.json.

var actor := ""
var params := 0
var room := 0
var swbit := 0xFF
var needs := "any"       # which attack kind this accepts
var thrown := false

# what each actor's collision accepts, from its own attack-type mask
const ACCEPTS := {
    "Qdghd": "fire_arrow", "Ykzyg": "ice_arrow", "MhmrSW0": "hammer",
    "bonbori": "fire", "SW_HIT0": "any",
}
const ITEM_FOR := {
    "fire_arrow": "the Fire Arrow", "ice_arrow": "the Ice Arrow",
    "hammer": "the Skull Hammer", "fire": "a flame",
}

var lamp: OmniLight3D = null
var _flicker_t := 0.0

# photometric numbers: an open flame is ~1900 K and a wall torch ~600-1200 lm
const FLAME_KELVIN := 1900.0
const FLAME_LUMENS := 900.0

func setup_switch(actor_name: String, p: int, r: int) -> void:
    actor = actor_name
    params = p
    room = r
    needs = str(ACCEPTS.get(actor_name, "any"))
    if actor_name == "bonbori":
        # a lamp is a light source.  It starts lit unless it is a puzzle lamp waiting on a
        # switch (swbit != 0xFF with the switch off) - those light when struck with fire.
        lamp = OmniLight3D.new()
        lamp.light_temperature = FLAME_KELVIN
        lamp.light_intensity_lumens = FLAME_LUMENS
        lamp.omni_range = 900.0
        lamp.omni_attenuation = 1.0        # inverse-square in physical units
        lamp.shadow_enabled = false        # 780 shadowed lamps is not a budget anyone has
        lamp.position = Vector3(0, 120.0, 0)
        add_child(lamp)
    match actor_name:
        "Qdghd", "Ykzyg":
            swbit = (p >> 8) & 0xFF
        "MhmrSW0":
            swbit = (p >> 8) & 0xFF
        _:
            swbit = p & 0xFF
    if swbit != 0xFF and Game.is_switch(room, swbit):
        thrown = true
    if lamp:
        # d_a_ep.cpp: type = params & 0x3F (0x3F reads as 0); types 0 and 3 burn from the
        # start, the others are the puzzle torches that wait to be lit
        var ep_type := p & 0x3F
        if ep_type == 0x3F:
            ep_type = 0
        var lit_at_start: bool = ep_type == 0 or ep_type == 3
        lamp.visible = thrown or lit_at_start
    add_to_group("hit_switch")
    collision_layer = 8          # the layer weapons sweep
    collision_mask = 0
    var shape := CollisionShape3D.new()
    var box := BoxShape3D.new()
    box.size = Vector3(120.0, 160.0, 120.0)
    shape.shape = box
    shape.position.y = 80.0
    add_child(shape)

func take_hit(_damage: int, _from: Vector3, kind := "sword") -> void:
    if thrown:
        return
    if needs != "any" and kind != needs:
        # the real collision simply does not accept the attack; say what it wants
        var want: String = str(ITEM_FOR.get(needs, needs))
        if Game.scripted():
            print("gcrip hit_switch: ", actor, " ignores ", kind, " - it wants ", want)
        return
    thrown = true
    if swbit != 0xFF:
        Game.set_switch(room, swbit)
    if lamp:
        lamp.visible = true
    print("gcrip hit_switch: ", actor, " struck with ", kind, " -> switch ", swbit,
        " in room ", room)

func _process(delta: float) -> void:
    # a flame does not hold still: a slow wander around the nominal output
    if lamp == null or not lamp.visible:
        return
    _flicker_t += delta
    var f := 1.0 + 0.08 * sin(_flicker_t * 9.3) + 0.05 * sin(_flicker_t * 23.1 + 1.7)
    lamp.light_intensity_lumens = FLAME_LUMENS * f
    Game.story_hit_switch(actor, room, swbit)
"""

_DOOR_GD = """extends StaticBody3D
# gcrip: a placed door (d_door.cpp + d_a_door10/12/kddoor).  159 door10, 52 door12 and their
# aliases are placed across the game; until now they were scenery and every doorway was open.
#
# The lock is params bits 8-11, and THE TWO FAMILIES DISAGREE about what the numbers mean:
#   door10 (door10/11/20/21/Zenshut/keyshut/K_Zshut): 4 and 5 = small key, 1 = Big Key,
#                                                     2 = "clear the room"
#   door12 (door12/12M/12B/13/13M/13B/keyS12/ZenS12): 1 = small key, 3 = Big Key,
#                                                     2 = "clear the room"
# Earth and Wind Temple contain no type-3 door12 at all - their Big Key doors are ordinary
# door12 placements promoted at runtime when arg1 is 9 or 0xC (d_a_door12.cpp:576-578), and
# arg1 lives in rot.z >> 8.
#
# A small-key door spends one key; a Big Key door spends NOTHING - dDoor_key2_c::keyInit's
# `if (!mbIsBossDoor) setItemKeyNumCount(-1)` is the only decrement in the game.

enum Lock { NONE, SMALL_KEY, BIG_KEY, ROOM_CLEAR }

var actor := ""
var node_name := ""    # the placement this came from, so the fallback pass can skip duplicates
var params := 0
var swbit := 0xFF
var swbit2 := 0xFF
var dtype := 0
var front_room := 0x3F
var back_room := 0x3F
var arg1 := 0
var lock: int = Lock.NONE
var opened := false
var warp: Area3D = null      # the exit volume this door stands in front of, if it gates one
var slab: CollisionShape3D = null   # the physical barrier, for doors with no model

const DOOR10 := ["door10", "door11", "door20", "door21", "Zenshut", "keyshut", "K_Zshut"]
const DOOR12 := ["door12", "door12M", "door12B", "door13", "door13M", "door13B",
                 "keyS12", "ZenS12"]

var door_rot_y := 0.0

func setup_door(actor_name: String, p: int, rot: Array, rot_y_deg := 0.0) -> void:
    actor = actor_name
    door_rot_y = rot_y_deg
    params = p
    swbit = p & 0xFF
    dtype = (p >> 8) & 0xF
    swbit2 = (p >> 20) & 0xFF
    var rx := int(rot[0])
    front_room = rx & 0x3F
    back_room = (rx >> 6) & 0x3F
    arg1 = (int(rot[2]) >> 8) & 0xFF
    if DOOR12.has(actor):
        # arg1 9 / 0xC promotes an ordinary door12 to the Big Key door (ET and WT use this)
        if arg1 == 9 or arg1 == 0xC:
            dtype = 3
        match dtype:
            1: lock = Lock.SMALL_KEY
            3: lock = Lock.BIG_KEY
            2: lock = Lock.ROOM_CLEAR
    elif DOOR10.has(actor):
        match dtype:
            4, 5: lock = Lock.SMALL_KEY
            1: lock = Lock.BIG_KEY
            2: lock = Lock.ROOM_CLEAR
    if lock != Lock.NONE and swbit != 0xFF and Game.is_switch(front_room, swbit):
        opened = true      # this door was already unlocked on a previous visit
    add_to_group("door")
    _find_warp()
    if lock != Lock.NONE and not opened:
        add_to_group("interact")
        # A dungeon's doors are room-to-room INSIDE one scene, so most gate no warp at all -
        # and a door placed from the record has no model either.  Without a slab a "locked"
        # door would stop nothing, so give it one and drop it when the door opens.
        if warp == null:
            slab = CollisionShape3D.new()
            var box := BoxShape3D.new()
            box.size = Vector3(300.0, 360.0, 40.0)
            slab.shape = box
            slab.position.y = 180.0
            slab.rotation.y = deg_to_rad(door_rot_y)
            add_child(slab)
            collision_layer = 1

func _find_warp() -> void:
    # the exit volume is generated from the SCLS table, not from this placement, so pair them
    # by proximity - the door slab sits about 70 units in front of its warp box
    var cs := get_tree().current_scene
    if cs == null:
        return
    var best := 400.0
    for n in cs.get_children():
        if not (n is Area3D) or not n.name.begins_with("Warp"):
            continue
        var d: float = (n as Area3D).global_position.distance_to(global_position)
        if d < best:
            best = d
            warp = n
    if warp and lock != Lock.NONE and not opened:
        warp.set("locked", true)

func _unlock(spend: bool) -> void:
    opened = true
    if spend:
        Game.add_key(-1)
    if swbit != 0xFF:
        Game.set_switch(front_room, swbit)   # stays unlocked for good
    if warp and is_instance_valid(warp):
        warp.set("locked", false)
    if slab and is_instance_valid(slab):
        slab.queue_free()      # the way is open
        slab = null
    remove_from_group("interact")
    print("gcrip door: ", actor, " type ", dtype, " opened",
        " (spent a small key)" if spend else "")

func interact_prompt(link: Node3D) -> String:
    if opened or lock == Lock.NONE:
        return ""
    if link.global_position.distance_to(global_position) > 140.0:
        return ""
    match lock:
        Lock.SMALL_KEY:
            return "Open (1 key)" if Game.key_count() > 0 else "Locked"
        Lock.BIG_KEY:
            return "Open" if Game.dungeon_item(Game.DUNGEON_BIG_KEY) else "Locked"
        Lock.ROOM_CLEAR:
            return "Barred"
    return ""

func interact(_link: Node3D) -> void:
    if opened:
        return
    match lock:
        Lock.SMALL_KEY:
            if Game.key_count() > 0:
                _unlock(true)
            else:
                Game.show_text("It won't open. It needs a small key.")
        Lock.BIG_KEY:
            if Game.dungeon_item(Game.DUNGEON_BIG_KEY):
                _unlock(false)     # a Big Key door spends nothing
            else:
                Game.show_text("A huge keyhole... this needs the Big Key.")
        Lock.ROOM_CLEAR:
            Game.show_text("The bars are shut tight.")

func _physics_process(_delta: float) -> void:
    # type 2 lifts its bars once the front room has no live enemies, and then raises its own
    # switch (d_a_door10.cpp:132-147 / d_a_door12.cpp:155)
    if opened or lock != Lock.ROOM_CLEAR:
        return
    if Engine.get_physics_frames() % 15 != 0:
        return
    if Game.room_live_enemies(front_room) == 0:
        _unlock(false)
"""

_SALVAGE_GD = """extends Node3D
# gcrip: a salvage point (d_a_salvage.cpp).  489 of them cover the Great Sea in six kinds.
# The crane tip has to be inside the ring in XZ and well below the water; a type-1 point gives
# up its buried item, anything else answers with an empty crane - and sometimes an Octorok.

var params := 0
var rot_z := 0
var room := 0
var kind := 0
var save_no := 0
var item_no := 0
var type := 0
var cmap_no := 0
var switch_no := 0
var ring := 700.0
var depth := 1000.0
var taken := false

# checkArea, d_a_salvage.cpp:443 - rerolled whenever the hook leaves a ring
const DEPTHS := [1000.0, 1500.0, 2000.0]

func setup(p: int, rz: int, r: int, sc: Array) -> void:
    params = p
    rot_z = rz
    room = r
    kind = (p >> 28) & 0xF
    save_no = (p >> 20) & 0xFF
    item_no = (p >> 4) & 0xFF
    type = p & 0x0F
    cmap_no = rz & 0x03
    switch_no = rz & 0xFF
    # d_salvage.cpp:124-137
    var sx := float(sc[0])
    ring = sx * (700.0 if kind == 0 else (500.0 if kind == 5 else 400.0))
    depth = DEPTHS[randi() % 3]

func available() -> bool:
    # dSalvage_control_c::entry, d_salvage.cpp:88-114 - one case per kind
    if taken:
        return false
    match kind:
        0:
            if Game.collect_map_done(save_no):
                return false
            return cmap_no == Game.random_salvage_point()
        2:
            if not Game.is_switch(room, switch_no):
                return false
            return save_no == 31 or not Game.ocean_bit(room, save_no)
        3:
            return save_no == 31 or not Game.ocean_bit(room, save_no)
        4:
            if save_no != 31 and Game.ocean_bit(room, save_no):
                return false
            return Game.is_night()        # marked used while it is day
        5:
            return true                   # the invisible decoys are always live
        6:
            if save_no < Game.SALVAGE_FM_BITS.size() \
                    and Game.event_bit(int(Game.SALVAGE_FM_BITS[save_no])):
                return false
            return Game.full_moon_night()
    return false

func in_reach(tip: Vector3, water_y: float) -> bool:
    var d := tip - global_position
    if Vector2(d.x, d.z).length() >= ring:
        return false
    return tip.y < water_y - depth

func dredge() -> Dictionary:
    # end_salvage, d_a_salvage.cpp:503-530
    taken = true
    var hit: bool = type == 1 and kind != 5
    var out := {"hit": hit, "kind": kind, "item": item_no if hit else -1, "octorok": false}
    if not hit:
        out["octorok"] = kind == 5 or type == 2
        depth = DEPTHS[randi() % 3]
        taken = false                      # a miss does not consume the point
        return out
    match kind:
        0:
            Game.set_collect_map_done(save_no)
            Game.set_event_bit(0x3E02)
        3, 4:
            if save_no != 31:
                Game.set_ocean_bit(room, save_no)
        6:
            if save_no < Game.SALVAGE_FM_BITS.size():
                Game.set_event_bit(int(Game.SALVAGE_FM_BITS[save_no]))
    Game.story_item_collected(item_no, "")
    return out
"""

_CONTROL_GD = 'extends Node\n# gcrip: a debug control channel.  Started only by --control[=<port>] and bound to 127.0.0.1,\n# it accepts one JSON object per line and answers with one JSON object per line, so an outside\n# tool (the gcrip MCP server) can drive a running game instead of the game running a canned\n# script.  Never start this in a build you hand to anyone.\n\nconst DEFAULT_PORT := 8787\n\nvar server := TCPServer.new()\nvar peers: Array[StreamPeerTCP] = []\nvar buffers: Array[String] = []\nvar port := DEFAULT_PORT\nvar held: Dictionary = {}          # action -> frames left to hold\n\nfunc start(p: int) -> bool:\n    port = p\n    var err := server.listen(port, "127.0.0.1")\n    if err != OK:\n        push_error("gcrip control: cannot listen on 127.0.0.1:%d (%d)" % [port, err])\n        return false\n    print("gcrip control: listening on 127.0.0.1:", port)\n    return true\n\nfunc _process(_delta: float) -> void:\n    while server.is_connection_available():\n        var peer := server.take_connection()\n        peers.append(peer)\n        buffers.append("")\n        print("gcrip control: client connected")\n    var i := 0\n    while i < peers.size():\n        var peer: StreamPeerTCP = peers[i]\n        peer.poll()\n        if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:\n            peers.remove_at(i)\n            buffers.remove_at(i)\n            continue\n        var n := peer.get_available_bytes()\n        if n > 0:\n            buffers[i] += peer.get_utf8_string(n)\n        while buffers[i].find("\\n") >= 0:\n            var cut := buffers[i].find("\\n")\n            var line := buffers[i].substr(0, cut).strip_edges()\n            buffers[i] = buffers[i].substr(cut + 1)\n            if line != "":\n                var reply := _handle(line)\n                peer.put_data((JSON.stringify(reply) + "\\n").to_utf8_buffer())\n        i += 1\n\nfunc _physics_process(_delta: float) -> void:\n    # a held button has to span whole PHYSICS frames: the player polls\n    # is_action_just_pressed there, and _process can run many times between two ticks\n    for a in held.keys():\n        held[a] -= 1\n        if held[a] <= 0:\n            Input.action_release(a)\n            held.erase(a)\n\nfunc _handle(line: String) -> Dictionary:\n    var msg = JSON.parse_string(line)\n    if not (msg is Dictionary):\n        return {"ok": false, "error": "not a JSON object"}\n    var cmd := str(msg.get("cmd", ""))\n    match cmd:\n        "state":\n            return {"ok": true, "state": _state()}\n        "stages":\n            var out: Array = []\n            for k in Game.stage_data.keys():\n                if Game.playable(k):\n                    out.append(k)\n            out.sort()\n            return {"ok": true, "stages": out, "names": Game.stage_names}\n        "warp":\n            var st := str(msg.get("stage", ""))\n            if not Game.stage_data.has(st):\n                return {"ok": false, "error": "no such stage: " + st}\n            Game.last_warp_ms = -100000\n            Game.warp(st, int(msg.get("room", 0)), int(msg.get("spawn", 0)))\n            return {"ok": true}\n        "place":\n            var lk := Game.player()\n            if lk == null:\n                return {"ok": false, "error": "no player"}\n            lk.global_position = Vector3(\n                float(msg.get("x", lk.global_position.x)),\n                float(msg.get("y", lk.global_position.y)),\n                float(msg.get("z", lk.global_position.z)))\n            lk.velocity = Vector3.ZERO\n            if msg.has("facing_deg"):\n                lk.set("facing", deg_to_rad(float(msg["facing_deg"])))\n            return {"ok": true, "state": _state()}\n        "input":\n            # hold an input action for N frames, the way a player would tap or hold it\n            var action := str(msg.get("action", ""))\n            if action == "":\n                return {"ok": false, "error": "no action"}\n            if not InputMap.has_action(action):\n                return {"ok": false, "error": "no such action: " + action,\n                        "actions": InputMap.get_actions()}\n            Input.action_press(action, float(msg.get("strength", 1.0)))\n            held[action] = maxi(int(msg.get("frames", 2)), 1)\n            return {"ok": true}\n        "stick":\n            # the analog stick, as a held vector (x right, y forward)\n            Game.control_stick = Vector2(float(msg.get("x", 0.0)), float(msg.get("y", 0.0)))\n            Game.control_stick_frames = int(msg.get("frames", 30))\n            return {"ok": true}\n        "actors":\n            var out2: Array = []\n            for grp in ["interact", "enemy", "pickup"]:\n                for nd in get_tree().get_nodes_in_group(grp):\n                    if is_instance_valid(nd):\n                        var nm = nd.get("actor")\n                        out2.append({"actor": str(nm) if nm != null else "",\n                                     "node": String(nd.name), "group": grp,\n                                     "pos": _v(nd.global_position)})\n            return {"ok": true, "actors": out2}\n        "talk":\n            var who := str(msg.get("actor", ""))\n            var target := Game._find_actor(who)\n            var lk2 := Game.player()\n            if target == null or lk2 == null:\n                return {"ok": false, "error": "no " + who + " here"}\n            lk2.global_position = target.global_position + Vector3(0, 5, 120)\n            target.interact(lk2)\n            return {"ok": true, "state": _state()}\n        "event":\n            var ev := str(msg.get("name", ""))\n            if not Game.events.has(ev):\n                return {"ok": false, "error": "no event " + ev + " in this stage",\n                        "events": Game.events.keys()}\n            return {"ok": Game.run_event(ev)}\n        "dialog":\n            if Game.dialog and Game.dialog_open:\n                Game.dialog.advance()\n            return {"ok": true, "open": Game.dialog_open}\n        "defeat":\n            var who := str(msg.get("actor", ""))\n            if who == "room":\n                Game.story_room_cleared(int(msg.get("room", 0)))\n            else:\n                Game.story_enemy_defeated(who, bool(msg.get("boss", false)))\n            return {"ok": true, "story_done": (Game.save.get("story_done", {}) as Dictionary).keys(),\n                    "boss_dead": Game.save.get("boss_dead", {})}\n        "story_place":\n            # move a named actor (npc_tag: put Medli inside the TagMd box) or place a\n            # breakable story object at a point (hit: the Ajav wall has no placement yet)\n            var pwho := str(msg.get("actor", ""))\n            var plk := Game.player()\n            var at: Vector3 = plk.global_position if plk else Vector3.ZERO\n            if msg.has("x"):\n                at = Vector3(float(msg["x"]), float(msg.get("y", at.y)), float(msg["z"]))\n            if bool(msg.get("hit", false)):\n                var hscene := get_tree().current_scene\n                if hscene == null or not hscene.has_method("spawn_hit_object"):\n                    return {"ok": false, "error": "this scene places no hit objects"}\n                for step in Game.story_hit_steps():\n                    var hb: Dictionary = step.get("hit", {})\n                    if pwho != "" and str(hb.get("actor", "")) != pwho:\n                        continue\n                    var nd = hscene.spawn_hit_object(step, at,\n                        float(msg.get("facing_deg", 0.0)))\n                    return {"ok": true, "node": String(nd.name), "at": _v(at),\n                            "events": hb.get("events", [])}\n                return {"ok": false, "error": "no story hit step is waiting here"}\n            var pt := Game._find_actor(pwho)\n            if pt == null:\n                return {"ok": false, "error": "no " + pwho + " here"}\n            pt.global_position = at\n            return {"ok": true, "at": _v(at), "ground": Game.ground_height(at),\n                    "story_done": (Game.save.get("story_done", {}) as Dictionary).keys(),\n                    "hit_log": Game.hit_log}\n\n        "reg":\n            var rid := int(msg.get("id", 0))\n            if msg.has("value"):\n                Game.set_event_reg(rid, int(msg["value"]))\n            return {"ok": true, "value": Game.event_reg(rid)}\n        "bit":\n            var id := int(msg.get("id", 0))\n            if msg.has("set"):\n                if bool(msg["set"]):\n                    Game.set_event_bit(id)\n                return {"ok": true, "value": Game.event_bit(id)}\n            return {"ok": true, "value": Game.event_bit(id)}\n        "item":\n            var nm := str(msg.get("name", ""))\n            if bool(msg.get("give", false)):\n                Game.give_item(nm)\n            return {"ok": true, "has": Game.has_item(nm), "items": Game.save.get("items", {})}\n        "screenshot":\n            var img := get_viewport().get_texture().get_image()\n            if img == null:\n                return {"ok": false, "error": "no viewport image (running headless?)"}\n            var path := str(msg.get("path", "user://control_shot.png"))\n            img.save_png(path)\n            return {"ok": true, "path": ProjectSettings.globalize_path(path)}\n        "eye":\n            # a free camera, for looking at the world from where the follow cam cannot go\n            var dcam := get_tree().root.get_node_or_null("GcripDebugCam") as Camera3D\n            if bool(msg.get("off", false)):\n                if dcam:\n                    dcam.queue_free()\n                var pcam := get_viewport().get_camera_3d()\n                return {"ok": true, "free": false}\n            if dcam == null:\n                dcam = Camera3D.new()\n                dcam.name = "GcripDebugCam"\n                dcam.far = 800000.0\n                get_tree().root.add_child(dcam)\n            var epos := Vector3(float(msg.get("x", 0.0)), float(msg.get("y", 0.0)),\n                float(msg.get("z", 0.0)))\n            var lk4 := Game.player()\n            var look := lk4.global_position if lk4 else Vector3.ZERO\n            if msg.has("lx"):\n                look = Vector3(float(msg["lx"]), float(msg.get("ly", 0.0)),\n                    float(msg["lz"]))\n            dcam.global_position = epos\n            if epos.distance_to(look) > 0.01:\n                dcam.look_at(look, Vector3.UP)\n            dcam.make_current()\n            return {"ok": true, "free": true, "eye": _v(epos), "look": _v(look)}\n        "vis":\n            # what is actually being DRAWN.  A screenshot cannot tell you which node\n            # stopped rendering; polling this while the world changes can.\n            var vcs := get_tree().current_scene\n            if vcs == null:\n                return {"ok": false, "error": "no scene"}\n            var shown := 0\n            var hidden_names: Array = []\n            for nd in vcs.find_children("*", "MeshInstance3D", true, false):\n                var m3 := nd as MeshInstance3D\n                if m3.is_visible_in_tree():\n                    shown += 1\n                elif hidden_names.size() < 60:\n                    hidden_names.append(String(m3.name))\n            var tops: Array = []\n            for ch in vcs.get_children():\n                if ch is Node3D and not (ch as Node3D).visible:\n                    tops.append(String(ch.name))\n            return {"ok": true, "visible_meshes": shown,\n                "hidden_sample": hidden_names, "hidden_top_level": tops}\n        "clock":\n            if msg.has("hour"):\n                Game.set_day_time(float(msg["hour"]) * Game.UNITS_PER_HOUR)\n            return {"ok": true, "hour": Game.day_time() / Game.UNITS_PER_HOUR}\n        "ground":\n            var lk3 := Game.player()\n            var at: Vector3 = lk3.global_position if lk3 else Vector3.ZERO\n            if msg.has("x"):\n                at = Vector3(float(msg["x"]), float(msg.get("y", 0.0)), float(msg["z"]))\n            return {"ok": true, "under": Game.ground_under(at), "at": _v(at)}\n        "quit":\n            get_tree().quit()\n            return {"ok": true}\n    return {"ok": false, "error": "unknown cmd: " + cmd,\n            "commands": ["state", "stages", "warp", "place", "input", "stick", "actors",\n                         "talk", "event", "dialog", "bit", "item", "defeat", "screenshot",\n                         "story_place",\n                         "ground", "clock", "eye", "vis",\n                         "quit"]}\n\nfunc _v(p: Vector3) -> Array:\n    return [snappedf(p.x, 0.1), snappedf(p.y, 0.1), snappedf(p.z, 0.1)]\n\nfunc _state() -> Dictionary:\n    var cs := get_tree().current_scene\n    var lk := Game.player()\n    var st := {\n        "scene": String(cs.name) if cs else "",\n        "stage": Game.current_stage_key(),\n        "event_running": Game.event_running,\n        "cutscene": Game.cutscene_running(),\n        "dialog_open": Game.dialog_open,\n        "hearts": Game.save.get("hearts", 0),\n        "items": Game.save.get("items", {}),\n        "story_done": (Game.save.get("story_done", {}) as Dictionary).keys(),\n    }\n    if lk:\n        st["pos"] = _v(lk.global_position)\n        st["facing_deg"] = snappedf(rad_to_deg(float(lk.get("facing"))), 0.1)\n        st["state"] = int(lk.get("state"))\n        st["ground"] = Game.ground_under(lk.global_position)\n        st["sea"] = {"scale": snappedf(Game.sea_cur_scale, 0.01),\n            "target": snappedf(Game.sea_wave_target(lk.global_position.x, lk.global_position.z), 0.01),\n            "height": snappedf(Game.sea_height(lk.global_position.x, lk.global_position.z), 0.1),\n            "wave_max": Game.sea_wave_max}\n        var pt = lk.get("prompt_target")\n        st["prompt_target"] = (str(pt.get("actor")) if pt != null and is_instance_valid(pt)\n            else "")\n    return st\n'

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

func advance() -> void:
    page += 1
    _render()

func _unhandled_input(event: InputEvent) -> void:
    if not visible:
        return
    if event.is_action_pressed("action_a") or event.is_action_pressed("action_b"):
        advance()
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
    # placed quest pickups (they gate their own existence on a story bit)
    "itemDek": "res://actors/pickup.gd", "Bitem": "res://actors/pickup.gd",
    "Kui": "res://actors/kui.gd",
    # generic data-driven enemies (enemies.json)
    "mo2": "res://actors/enemy.gd", "Puti": "res://actors/enemy.gd", "Tn": "res://actors/enemy.gd",
    "Stal": "res://actors/enemy.gd", "amos2": "res://actors/enemy.gd", "keeth": "res://actors/enemy.gd",
    "Fkeeth": "res://actors/enemy.gd", "Bb": "res://actors/enemy.gd", "p_hat": "res://actors/enemy.gd",
    "Oq": "res://actors/enemy.gd", "wiz_r": "res://actors/enemy.gd",
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
    # breakable: takes take_hit() and orders one event per damage stage
    "Ajav": "res://actors/hit_object.gd",
    # doors: the lock lives in params bits 8-11 (actors/door.gd)
    "door10": "res://actors/door.gd", "door11": "res://actors/door.gd",
    "door20": "res://actors/door.gd", "door21": "res://actors/door.gd",
    "Zenshut": "res://actors/door.gd", "keyshut": "res://actors/door.gd",
    "K_Zshut": "res://actors/door.gd", "door12": "res://actors/door.gd",
    "door12M": "res://actors/door.gd", "door12B": "res://actors/door.gd",
    "door13": "res://actors/door.gd", "door13M": "res://actors/door.gd",
    "door13B": "res://actors/door.gd", "keyS12": "res://actors/door.gd",
    "ZenS12": "res://actors/door.gd",
}
const CHEST_PREFIXES := ["takara", "tkr", "Tkr"]

var _bgm_tick := 0
var _variant_cache: Dictionary = {}
var _variant_seen: Dictionary = {}

func _ready() -> void:
    # the sea snaps to this room's wave_max in _spawn_ocean, which runs before the deferred
    # _start_bgm that used to set it - so it read an EMPTY table, fell back to the open-sea
    # 30, and put +-300 units of swell over the island for the first half-minute of play
    var _info: Dictionary = Game.stage_data.get(name, {})
    Game.sea_wave_max = _info.get("wave_max", {})
    _tag_liquids()
    _wrap_actors()
    _spawn_ships()
    _spawn_tags()
    _spawn_warp_objects()
    _spawn_npc_tags()
    _spawn_hit_objects()
    _start_bgm.call_deferred()

func _variant_keep(info: Dictionary, actor: String) -> int:
    # which params type of this actor to keep among the copies that survive the layer filter
    if not _variant_cache.has(actor):
        var wanted := int(FRESH_TYPE.get(actor, -1))
        var types: Array = []
        for rec in info.get("actors", []):
            if str(rec.get("actor", "")) != actor:
                continue
            var lay := int(rec.get("layer", -1))
            var rm: int = int(rec["room"]) if rec.get("room") != null else -1
            if lay >= 0 and lay != Game.story_layer(name, rm):
                continue
            types.append(int(rec.get("params", 0)) & 0xFF)
        if types.size() <= 1:
            _variant_cache[actor] = -1              # only one copy: always keep it
        elif types.has(wanted):
            _variant_cache[actor] = wanted
        else:
            _variant_cache[actor] = types[0]        # no fresh-file copy here: keep the first
    return int(_variant_cache[actor])

func _drop_variant(info: Dictionary, rec: Dictionary, actor: String) -> bool:
    if not FRESH_TYPE.has(actor):
        return false
    var keep := _variant_keep(info, actor)
    if keep < 0:
        return false
    if (int(rec.get("params", 0)) & 0xFF) != keep:
        return true
    if _variant_seen.has(actor):
        return true                                  # one of each, even if types tie
    _variant_seen[actor] = true
    return false

# daWarpf_c's flower has no ACTR record of its own - the boss spawns it where it died, which
# is also where the boss item drops, so that placement is the flower's anchor.
const WARP_ANCHORS := ["Bitem"]
const WARP_RADIUS := 200.0     # daWarpf_c::m_warp_size[STAGE_TOTG]

func _spawn_warp_objects() -> void:
    # placed warp objects: the in-dungeon lifts (Ywarp00) and the boss room's warp flower.
    # Each orders a stage event and then changes stage; which event it orders is read from
    # the save when Link steps in (Game.warp_branch).
    var objs: Array = Game.warp_objects(name)
    if objs.is_empty():
        return
    var info: Dictionary = Game.stage_data.get(name, {})
    var n := 0
    for obj in objs:
        var found = _warp_pos(info, obj)
        if not (found is Vector3):
            print("gcrip warp: no position for ", str(obj.get("actor", "?")), " in ", name)
            continue
        var pos: Vector3 = found
        var node := Area3D.new()
        node.set_script(load("res://actors/warp_object.gd"))
        node.name = "Warp_%s_%d" % [str(obj.get("actor", "W")), n]
        add_child(node)
        node.global_position = pos
        node.setup(obj, WARP_RADIUS)
        n += 1
        # report the branch the save picks right now, so booting into the stage is enough to
        # check the save-state choice without walking Link into the object
        var br: Dictionary = Game.warp_branch(obj)
        var raw = br.get("dest", {})
        var dest: Dictionary = raw if raw is Dictionary else {}
        var branches: Array = obj.get("branches", [])
        print("gcrip warp: ", str(obj.get("actor", "?")), " at ", pos.round(),
              " room ", int(obj.get("room", -1)), " -> ", str(br.get("event", "-")),
              " -> ", str(dest.get("stage", "-")), " room ", int(dest.get("room", 0)),
              " spawn ", int(dest.get("spawn", 0)), "  (", branches.size(), " branches)")
    if n > 0:
        print("gcrip: ", n, " warp objects in ", name)

func _warp_pos(info: Dictionary, obj: Dictionary):
    # prefer the stage's own ACTR record for this actor (the mined coordinates are rounded);
    # then the mined position; then the boss-item anchor, for objects the game spawns
    var actor := str(obj.get("actor", ""))
    var room := int(obj.get("room", -1))
    var mined = obj.get("pos")
    var have_mined: bool = mined is Vector3
    var want: Vector3 = mined if have_mined else Vector3.ZERO
    var best := Vector3.ZERO
    var best_d := INF
    var found := false
    for rec in info.get("actors", []):
        if str(rec.get("actor", "")) != actor:
            continue
        if room >= 0 and rec.get("room") != null and int(rec["room"]) != room:
            continue
        var p := Vector3(float(rec["pos"][0]), float(rec["pos"][1]), float(rec["pos"][2]))
        var d: float = p.distance_to(want) if have_mined else 0.0
        if not found or d < best_d:
            best = p
            best_d = d
            found = true
        if not have_mined:
            break
    if found and (not have_mined or best_d < 200.0):
        return best
    if have_mined:
        return want
    for rec in info.get("actors", []):
        if not WARP_ANCHORS.has(str(rec.get("actor", ""))):
            continue
        if room >= 0 and rec.get("room") != null and int(rec["room"]) != room:
            continue
        return Vector3(float(rec["pos"][0]), float(rec["pos"][1]), float(rec["pos"][2]))
    return null

func _spawn_tags() -> void:
    var info: Dictionary = Game.stage_data.get(name, {})
    var table: Array = info.get("event_table", [])
    var n := 0
    for rec in info.get("tags", []):
        if str(rec.get("actor", "")) != "TagEv":
            continue
        var tag := Area3D.new()
        tag.set_script(load("res://actors/tag_event.gd"))
        tag.name = "TagEv_%d" % n
        add_child(tag)
        tag.global_position = Vector3(rec["pos"][0], rec["pos"][1], rec["pos"][2])
        var rot: Array = rec.get("rot", [0, 0, 0])
        tag.setup(int(rec["params"]), int(rot[2]), int(rec.get("room", 0) if rec.get("room") != null else 0), table, rec.get("scale", [1, 1, 1]))
        n += 1
    if n > 0:
        print("gcrip: ", n, " event tags in ", name)
    # island arrivals are their own actor (TagIsl, d_a_tag_island.cpp) with their own rules
    var k := 0
    for rec in info.get("tags", []):
        if str(rec.get("actor", "")) != "TagIsl":
            continue
        var lay := int(rec.get("layer", -1))
        var rm: int = int(rec["room"]) if rec.get("room") != null else 0
        if lay >= 0 and lay != Game.story_layer(name, rm):
            continue                # Windfall's night-only arrival lives on layers 2/3
        var isl := Node3D.new()
        isl.set_script(load("res://actors/tag_island.gd"))
        isl.name = "TagIsl_%d" % k
        add_child(isl)
        isl.global_position = Vector3(rec["pos"][0], rec["pos"][1], rec["pos"][2])
        isl.setup(int(rec["params"]), rm, table, rec.get("scale", [1, 1, 1]))
        k += 1
    if k > 0:
        print("gcrip: ", k, " island arrival tags in ", name)
    _spawn_salvage()
    _spawn_missing_doors()
    _spawn_hit_switches()
    _spawn_flame_lights()
    _apply_toon()

# ---- flames that are light sources but not switches ----------------------------------
const FLAME_LIGHTS := {
    # kelvin, lumens, range, kind
    "Lamp":    [1900.0, 250.0, 700.0, "sconce"],
    "Fire":    [2000.0, 1500.0, 1400.0, "omni"],
    "Zenfire": [2000.0, 1500.0, 1400.0, "omni"],
    "Yfire00": [2000.0, 1500.0, 1400.0, "omni"],
}

func _spawn_flame_lights() -> void:
    var info: Dictionary = Game.stage_data.get(name, {})
    var n := 0
    var sconce: Texture2D = null
    if ResourceLoader.exists("res://ies/wall_torch.png"):
        sconce = load("res://ies/wall_torch.png")
    for lst in ["actors", "logic"]:
        for rec in info.get(lst, []):
            var act := str(rec.get("actor", ""))
            if not FLAME_LIGHTS.has(act):
                continue
            var lay := int(rec.get("layer", -1))
            var rm: int = int(rec["room"]) if rec.get("room") != null else 0
            if lay >= 0 and lay != Game.story_layer(name, rm):
                continue
            var spec: Array = FLAME_LIGHTS[act]
            var light: Light3D
            if str(spec[3]) == "sconce" and sconce != null:
                # a wall lamp throws out from the wall; the invented sconce IES shapes it
                var sp := SpotLight3D.new()
                sp.spot_angle = 80.0
                sp.spot_range = float(spec[2])
                sp.light_projector = sconce
                light = sp
            else:
                var om := OmniLight3D.new()
                om.omni_range = float(spec[2])
                om.omni_attenuation = 1.0
                light = om
            light.light_temperature = float(spec[0])
            light.light_intensity_lumens = float(spec[1])
            light.shadow_enabled = false
            light.name = "Flame_%s_%d" % [act, n]
            add_child(light)
            var pos: Array = rec["pos"]
            light.global_position = Vector3(pos[0], pos[1] + 100.0, pos[2])
            if light is SpotLight3D:
                # face away from the wall: the placement's yaw is the fixture's facing
                light.rotation.y = deg_to_rad(float(rec.get("rot_y_deg", 0.0)))
                light.rotation.x = deg_to_rad(-25.0)
            light.set_script(load("res://actors/flame_flicker.gd"))
            n += 1
    if n > 0:
        print("gcrip light: ", n, " flame lights in ", name)
    _stream_init()
    _spawn_ocean()
    _build_bridges()
    _setup_lighting()

# ---- physical lighting --------------------------------------------------------------------
var sun: DirectionalLight3D = null
var env_node: WorldEnvironment = null
var outdoors := true
var hdri_slots: Dictionary = {}   # slot -> {file, sun_elev_deg, sun_to_sky}
var dome: MeshInstance3D = null
var dome_mat: ShaderMaterial = null
var current_slot := ""

# the WW-ish palette for the visible sky, by slot: [zenith, horizon, ground, sun]
const SKY_PALETTE := {
    "day":    [Color(0.20, 0.45, 0.78), Color(0.74, 0.85, 0.93), Color(0.32, 0.36, 0.42), Color(1.0, 0.97, 0.88)],
    "sunset": [Color(0.16, 0.20, 0.42), Color(0.98, 0.55, 0.28), Color(0.30, 0.24, 0.26), Color(1.0, 0.66, 0.36)],
    "night":  [Color(0.02, 0.03, 0.10), Color(0.09, 0.12, 0.24), Color(0.04, 0.05, 0.10), Color(0.75, 0.82, 1.0)],
}

func _setup_lighting() -> void:
    sun = get_node_or_null("Sun")
    env_node = get_node_or_null("Env")
    if sun == null or env_node == null:
        return
    var info = Game.dungeons.get(String(name).split("_r")[0])
    var kind := str(info.get("type", "")) if info is Dictionary else ""
    outdoors = kind in ["SEA", "OUTDOORS", "", "FF1"] or String(name).begins_with("sea")
    var env: Environment = env_node.environment
    if env == null:
        return
    if not Game.physical:
        # simple mode: a plain sun and sky, always visible.  Indoors, a soft ambient fill and a
        # dim key so the dungeon is not pitch black.
        if not outdoors:
            sun.light_energy = 0.25
            sun.shadow_enabled = false
            env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
            env.ambient_light_color = Color(0.42, 0.44, 0.5)
            env.ambient_light_energy = 0.6
            env.background_mode = Environment.BG_COLOR
            env.background_color = Color(0.03, 0.03, 0.05)
        _light_tick()
        print("gcrip light: simple ", "outdoor" if outdoors else "indoor", " rig in ", name)
        return
    env.sdfgi_enabled = Game.gi_on and outdoors
    # the HDR lights the world (ambient + reflection); a stylised sky dome hides it as the
    # background, and the visible sun is the game's own, tracked by the clock
    var mf := FileAccess.open("res://sky.json", FileAccess.READ)
    if mf:
        var meta = JSON.parse_string(mf.get_as_text())
        if meta is Dictionary:
            hdri_slots = meta.get("slots", {})
    if outdoors and not hdri_slots.is_empty():
        _build_skydome()
    if not outdoors:
        # a dungeon has no sky: a fill so the lit looks are not pitch black, and the sky's
        # ambient kept out of the room.  Physical units: these are lux / nits, not 0..1.
        sun.light_intensity_lux = 400.0
        sun.shadow_enabled = false
        env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
        env.ambient_light_color = Color(0.35, 0.36, 0.42)
        env.ambient_light_energy = 120.0
        Game.scene_nits = 400.0 / PI + 120.0
        env.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
        env.background_mode = Environment.BG_COLOR
        env.background_color = Color(0.02, 0.02, 0.03)
    _light_tick()
    print("gcrip light: ", "outdoor" if outdoors else "indoor", " rig in ", name,
        " (", kind, ")")

func _slot_for_hour(h: float) -> String:
    if h < 5.5 or h >= 19.0:
        return "night"
    if h < 7.5 or h >= 17.0:
        return "sunset"
    return "day"

func _build_skydome() -> void:
    dome_mat = ShaderMaterial.new()
    dome_mat.shader = load("res://skydome.gdshader")
    var sphere := SphereMesh.new()
    sphere.radius = 1000.0
    sphere.height = 2000.0
    sphere.radial_segments = 32
    sphere.rings = 16
    sphere.material = dome_mat
    dome = MeshInstance3D.new()
    dome.name = "SkyDome"
    dome.mesh = sphere
    # the camera lives hundreds of thousands of units from the origin; a dome left at the
    # origin is frustum-culled and never drawn, which is why the HDR showed through.  It has to
    # WRAP the camera, so it is recentred on the camera every frame and never culled.
    dome.extra_cull_margin = 1.0e9
    dome.ignore_occlusion_culling = true
    dome.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
    add_child(dome)
    _dome_follow()
    print("gcrip light: sky dome up; HDR slots ", hdri_slots.keys())

func _dome_follow() -> void:
    if dome == null:
        return
    var cam := get_viewport().get_camera_3d()
    var lk := Game.player()
    var c: Vector3 = cam.global_position if cam else (lk.global_position if lk else Vector3.ZERO)
    dome.global_position = c

func _apply_slot(slot: String) -> void:
    if slot == current_slot or not (env_node and env_node.environment):
        return
    current_slot = slot
    var env: Environment = env_node.environment
    # the HDR for this slot lights and reflects (hidden behind the dome)
    if hdri_slots.has(slot):
        var f := "res://" + str(hdri_slots[slot].get("file", ""))
        if ResourceLoader.exists(f):
            var pano := PanoramaSkyMaterial.new()
            pano.panorama = load(f)
            pano.energy_multiplier = 8000.0 if slot == "day" else (3000.0 if slot == "sunset" else 300.0)
            env.sky.sky_material = pano
    if dome_mat and SKY_PALETTE.has(slot):
        var pal: Array = SKY_PALETTE[slot]
        dome_mat.set_shader_parameter("zenith", pal[0])
        dome_mat.set_shader_parameter("horizon", pal[1])
        dome_mat.set_shader_parameter("ground", pal[2])
        dome_mat.set_shader_parameter("sun_color", pal[3])

func _light_tick() -> void:
    if sun == null or not outdoors:
        return
    if not Game.physical:
        # the sun's arc from the clock, in ordinary energy - bright by day, off at night, warm
        # near the horizon.  scene_nits stays 1, so the toon look reads correctly.
        var hh := Game.day_time() / Game.UNITS_PER_HOUR
        var tt := clampf((hh - 6.0) / 12.0, 0.0, 1.0)
        var ee := sin(tt * PI)
        var elv := ee * deg_to_rad(70.0)
        var azm := lerpf(deg_to_rad(-100.0), deg_to_rad(100.0), tt)
        var night2 := hh < 5.5 or hh > 18.5
        if night2:
            elv = deg_to_rad(-15.0)
        var dr := Vector3(cos(elv) * sin(azm), -sin(elv), cos(elv) * cos(azm)).normalized()
        sun.global_transform = Transform3D(Basis.looking_at(dr, Vector3.UP), Vector3(0, 10000, 0))
        sun.light_energy = 0.15 if night2 else lerpf(0.5, 1.25, ee)
        sun.light_temperature = lerpf(3200.0, 6000.0, ee)
        Game.sun_direction = dr
        Game.scene_nits = 1.0
        # the visible sky follows the same clock - day blue, sunset amber, night dark.
        # The ocean's night factor and reflection palette ride along, so the sea and the
        # sky can never disagree about the hour.
        night_mix = 1.0 - smoothstep(5.0, 6.5, hh) * (1.0 - smoothstep(17.5, 19.0, hh))
        var sunset_mix := smoothstep(5.0, 6.5, hh) - smoothstep(7.5, 9.0, hh)
        sunset_mix += smoothstep(16.0, 17.5, hh) - smoothstep(18.5, 19.5, hh)
        sunset_mix = clampf(sunset_mix, 0.0, 1.0)
        var zen := Color(0.28, 0.5, 0.78).lerp(Color(0.30, 0.30, 0.52), sunset_mix)
        zen = zen.lerp(Color(0.03, 0.045, 0.10), night_mix)
        var hor := Color(0.7, 0.82, 0.92).lerp(Color(0.98, 0.62, 0.35), sunset_mix)
        hor = hor.lerp(Color(0.10, 0.12, 0.20), night_mix)
        sky_zen_col = zen
        sky_hor_col = hor
        if env_node and env_node.environment and env_node.environment.sky:
            var skm = env_node.environment.sky.sky_material
            if skm is ProceduralSkyMaterial:
                skm.sky_top_color = zen
                skm.sky_horizon_color = hor
                skm.ground_horizon_color = hor
                skm.ground_bottom_color = Color(0.42, 0.45, 0.4).lerp(
                    Color(0.05, 0.06, 0.08), night_mix)
        return
    # the sun's arc from the clock: 06:00 on the eastern horizon, noon overhead, 18:00 west;
    # a warm colour temperature near the horizon and white at noon.  Same direction is pushed
    # into the toon / ocean shaders so every look agrees about where the light is.
    var h := Game.day_time() / Game.UNITS_PER_HOUR
    var t := clampf((h - 6.0) / 12.0, 0.0, 1.0)          # 0 at sunrise, 1 at sunset
    var elev := sin(t * PI) * deg_to_rad(70.0)            # peaks at 70 deg
    var azim := lerpf(deg_to_rad(-100.0), deg_to_rad(100.0), t)
    var night := h < 5.5 or h > 18.5
    if night:
        elev = deg_to_rad(-20.0)
    var dir := Vector3(cos(elev) * sin(azim), -sin(elev), cos(elev) * cos(azim)).normalized()
    sun.global_transform = Transform3D(Basis.looking_at(dir, Vector3.UP), Vector3(0, 10000, 0))
    var low := clampf(1.0 - sin(t * PI), 0.0, 1.0)        # 1 at the horizon, 0 at noon
    sun.light_temperature = lerpf(5800.0, 2600.0, pow(low, 1.5))
    sun.light_intensity_lux = 0.0 if night else lerpf(100000.0, 8000.0, pow(low, 2.0))
    if night:
        sun.light_intensity_lux = 150.0              # moonlight
        sun.light_temperature = 7500.0
    Game.sun_direction = dir
    # what a lit white reads as right now; the sky adds roughly a fifth on top of the sun
    Game.scene_nits = maxf(sun.light_intensity_lux, 150.0) * 1.2 / PI
    if not hdri_slots.is_empty():
        _apply_slot(_slot_for_hour(h))
    if dome_mat:
        dome_mat.set_shader_parameter("sun_travel", dir)
        dome_mat.set_shader_parameter("nits", Game.scene_nits)



# ---- the ocean surface (daSea_packet_c) --------------------------------------------------
const OCEAN_CELL := 800.0        # the game's heightfield cell
const OCEAN_CELLS := 64          # 65 x 65 vertices, window +-25600
const OCEAN_SKIRT := 450000.0    # the flat quads beyond the heightfield
# the same rule the exporter applies when it writes the player's water_level: the Great Sea's
# water is the y = 0 plane, every other stage has none (proper per-stage water volumes come
# with the dzb liquid surfaces later)
var water_level: float = -1.0e9     # set in _spawn_ocean: `name` is empty at init time
var ocean: MeshInstance3D = null
var night_mix := 0.0                          # 0 day .. 1 night, smooth (simple mode)
var sky_zen_col := Color(0.28, 0.5, 0.78)     # what the visible sky shows right now
var sky_hor_col := Color(0.7, 0.82, 0.92)
var ocean_mat: ShaderMaterial = null
var ocean_skirt: MeshInstance3D = null

func _spawn_ocean() -> void:
    if String(name).to_lower().begins_with("sea"):
        water_level = 0.0
    if water_level < -1.0e8 or not ResourceLoader.exists("res://ocean.gdshader"):
        return
    ocean_mat = ShaderMaterial.new()
    ocean_mat.shader = load("res://ocean.gdshader")
    # the four rows of Game.SEA_WAVES, so the surface and the buoyancy share one truth
    var w: Array = Game.SEA_WAVES
    ocean_mat.set_shader_parameter("wave_a", Vector4(w[0][0], w[0][1], w[0][2], w[0][5]))
    ocean_mat.set_shader_parameter("wave_b", Vector4(w[1][0], w[1][1], w[1][2], w[1][5]))
    ocean_mat.set_shader_parameter("wave_c", Vector4(w[2][0], w[2][1], w[2][2], w[2][5]))
    ocean_mat.set_shader_parameter("wave_d", Vector4(w[3][0], w[3][1], w[3][2], w[3][5]))
    ocean_mat.set_shader_parameter("dir_ab", Vector4(w[0][3], w[0][4], w[1][3], w[1][4]))
    ocean_mat.set_shader_parameter("dir_cd", Vector4(w[2][3], w[2][4], w[3][3], w[3][4]))
    if Game.toon_ready():
        ocean_mat.set_shader_parameter("toon_ramp", Game.toon_ramp)
    # SNAP to this room's swell instead of easing down from the open-sea 30.  The ease is
    # for sailing from open water into a harbour; on load there is nothing to ease from, and
    # 30 means +-300 units of swell - which is why the water sat at Link's feet on an island
    # whose wave_max is 0 for the first half-minute of play.
    var lk0 := Game.player()
    var at0: Vector3 = lk0.global_position if lk0 else global_position
    Game.sea_cur_scale = Game.sea_wave_target(at0.x, at0.z)
    var plane := PlaneMesh.new()
    plane.size = Vector2(OCEAN_CELL * OCEAN_CELLS, OCEAN_CELL * OCEAN_CELLS)
    plane.subdivide_width = OCEAN_CELLS - 1
    plane.subdivide_depth = OCEAN_CELLS - 1
    plane.material = ocean_mat
    ocean = MeshInstance3D.new()
    ocean.name = "Ocean"
    ocean.mesh = plane
    ocean.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
    add_child(ocean)
    # the skirt: one huge flat quad under everything, so the horizon is never empty.
    # Its vertices sit at the far edge where the wave sum averages to ~1.0 anyway.
    var far := PlaneMesh.new()
    far.size = Vector2(OCEAN_SKIRT * 2.0, OCEAN_SKIRT * 2.0)
    far.subdivide_width = 7
    far.subdivide_depth = 7
    far.material = ocean_mat
    ocean_skirt = MeshInstance3D.new()
    ocean_skirt.name = "OceanSkirt"
    ocean_skirt.mesh = far
    ocean_skirt.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
    add_child(ocean_skirt)
    ocean_skirt.position = Vector3(0, water_level - 2.0, 0)
    _ocean_tick()
    _hide_baked_sea()
    print("gcrip: ocean surface in ", name, " (", OCEAN_CELLS + 1, "x", OCEAN_CELLS + 1,
        " cells of ", OCEAN_CELL, ")")

func _build_bridges() -> void:
    # The `bridge` actor is placed from its ACTR record, but that record is overwritten at
    # create: the span comes from the stage PATH (d_a_bridge.cpp:1450-1479).  The exporter
    # resolved each span to its two ends and a plank count; the plank model is already in
    # the scene as the stub sitting at the anchor, so clone that and hide the stubs.
    # keyed by the SCENE name like every other stage system: sea_r44 is its own export with
    # its own recentred origin, and the full sea's coordinates are 400k units away
    var info: Dictionary = Game.stage_data.get(name, {})
    var spans: Array = info.get("bridges", [])
    if spans.is_empty():
        return
    var lvl := get_node_or_null("Level")
    if lvl == null:
        return
    var template: Mesh = null
    var stubs: Array = []
    for mi in lvl.find_children("bridge*", "MeshInstance3D", true, false):
        var m: MeshInstance3D = mi
        if m.mesh != null and template == null:
            template = m.mesh
        stubs.append(m)
    if template == null:
        return
    for m in stubs:
        (m as MeshInstance3D).visible = false
    var root := Node3D.new()
    root.name = "Bridges"
    add_child(root)
    var built := 0
    for sp in spans:
        var a := Vector3(float(sp["a"][0]), float(sp["a"][1]), float(sp["a"][2]))
        var b := Vector3(float(sp["b"][0]), float(sp["b"][1]), float(sp["b"][2]))
        var n := int(sp.get("planks", 0))
        if n < 2:
            continue
        var span := b - a
        var flat := Vector3(span.x, 0.0, span.z).length()
        # the rope sags: a catenary is a cosh, but over a span this shallow the parabola
        # through both ends is within a unit of it and costs nothing
        var sag: float = clampf(flat * 0.055, 12.0, 90.0)
        for i in range(n + 1):
            var t := float(i) / float(n)
            var pos := a.lerp(b, t)
            pos.y -= sag * 4.0 * t * (1.0 - t)
            var pl := MeshInstance3D.new()
            pl.mesh = template
            pl.name = "Plank%d" % i
            root.add_child(pl)
            # orient from the curve's TANGENT, not euler angles: `rotation` applies Y then
            # X, so after the yaw the pitch would tilt the plank sideways across the span
            var tangent := (span - Vector3.UP * (sag * 4.0 * (1.0 - 2.0 * t))).normalized()
            pl.global_transform = Transform3D(Basis.looking_at(tangent, Vector3.UP), pos)
            var body := StaticBody3D.new()
            var cs := CollisionShape3D.new()
            var box := BoxShape3D.new()
            box.size = Vector3(200.0, 12.0, 60.0)
            cs.shape = box
            body.add_child(cs)
            pl.add_child(body)
        built += 1
    if built > 0:
        Game.toonify(root, "")
        print("gcrip: built ", built, " rope bridge span(s) in ", name)

func _hide_baked_sea() -> void:
    # the stage bakes its own sea: a giant flat quad in the room's water colour plus shore
    # overlay sheets around each island (SC_01_mizu*).  Authored for TEV alpha tricks we do
    # not reproduce, they render opaque - the black sea at distance, the white wash at the
    # beach.  The ocean shader is the sea now, so hide any baked water sheet at sea level.
    # Ponds well above the waterline (the forest pool at y=768) are left alone.
    var lvl := get_node_or_null("Level")
    if lvl == null or ocean == null:
        return
    var hidden := 0
    for mi in lvl.find_children("*", "MeshInstance3D", true, false):
        var m: MeshInstance3D = mi
        if m.mesh == null or m.mesh.get_surface_count() == 0:
            continue
        var all_water := true
        for i in range(m.mesh.get_surface_count()):
            var mat := m.mesh.surface_get_material(i)
            var nm := (mat.resource_name if mat else "").to_lower()
            if not ("mizu" in nm or "nami" in nm):
                all_water = false
                break
        if not all_water:
            continue
        var bb := m.global_transform * m.get_aabb()
        if bb.position.y > water_level + 60.0 or bb.end.y < water_level - 60.0:
            continue
        m.visible = false
        hidden += 1
    if hidden > 0:
        print("gcrip: hid ", hidden, " baked sea sheets in ", name)

func _ocean_tick() -> void:
    if ocean == null or ocean_mat == null:
        return
    var cam := get_viewport().get_camera_3d()
    var centre: Vector3 = cam.global_position if cam else Vector3.ZERO
    var lk := Game.player()
    if lk:
        centre = lk.global_position
    # snap the window to the 800-unit lattice, as the game does, so vertices never swim
    ocean.position = Vector3(
        floor(centre.x / OCEAN_CELL) * OCEAN_CELL, water_level,
        floor(centre.z / OCEAN_CELL) * OCEAN_CELL)
    ocean_mat.set_shader_parameter("t_frames", float(Engine.get_physics_frames()))
    # drive the ease from here.  sea_height() is the only other caller, and on land nothing
    # calls it - so the scale stayed at the open-sea 30 and Outset (wave_max 0) got 300-unit
    # swell washing over its beach.  The visible sheet and the buoyancy read one scalar.
    ocean_mat.set_shader_parameter("wave_scale", Game.sea_wave_scale(centre.x, centre.z))
    var nm := night_mix
    var zc := sky_zen_col
    var hc := sky_hor_col
    if Game.physical:
        nm = 1.0 if Game.is_night() else 0.0
        if Game.is_night():
            zc = zc * 0.12
            hc = hc * 0.15
    ocean_mat.set_shader_parameter("night", nm)
    ocean_mat.set_shader_parameter("sky_zenith", Vector3(zc.r, zc.g, zc.b))
    ocean_mat.set_shader_parameter("sky_horizon", Vector3(hc.r, hc.g, hc.b))
    ocean_mat.set_shader_parameter("sun_dir", Game.sun_direction)
    ocean_mat.set_shader_parameter("nits", Game.scene_nits)
    var cs := Game.toon_sun_colors()
    ocean_mat.set_shader_parameter("c0", Vector3(cs[0].r, cs[0].g, cs[0].b))
    ocean_mat.set_shader_parameter("k0", Vector3(cs[1].r, cs[1].g, cs[1].b))

# ---- room streaming (RTBL) --------------------------------------------------------------
var room_sets: Array = []
var room_nodes: Dictionary = {}     # room number -> [nodes that belong to it]
var resident := {}                  # room -> true
var stream_room := -999

func _stream_init() -> void:
    var info: Dictionary = Game.stage_data.get(name, {})
    room_sets = info.get("room_sets", [])
    if room_sets.size() < 2:
        return          # nothing to stream: one resident set, or no table at all
    var level := get_node_or_null("Level")
    if level == null:
        return
    # the level glTF names each room's subtree "RoomN" / "RoomN/model..."
    for child in level.get_children():
        var nm := String(child.name)
        if not nm.begins_with("Room"):
            continue
        var digits := ""
        for i in range(4, nm.length()):
            if nm[i] < "0" or nm[i] > "9":
                break
            digits += nm[i]
        if digits == "":
            continue
        var rn := int(digits)
        if not room_nodes.has(rn):
            room_nodes[rn] = []
        room_nodes[rn].append(child)
    # a single-room scene (sea_r44, sea_r11) still carries the whole sea RTBL, but it holds
    # only ONE room's geometry and is recentred to the origin - so the grid room lookup returns
    # the wrong number and hides the only room there is, leaving Link on invisible collision.
    # Streaming is only for the full sea scene, which has many rooms.
    if room_nodes.size() <= 1:
        room_nodes.clear()
        room_sets = []
        return
    print("gcrip: RTBL streaming in ", name, " - ", room_sets.size(), " sets over ",
        room_nodes.size(), " rooms")
    _stream_update(true)

const STREAM_CONFIRM := 4      # checks (of 20 frames each) a new room must win to take effect
var _stream_pending := -1
var _stream_hold := 0

func _stream_update(force := false) -> void:
    if room_nodes.is_empty():
        return
    var lk := Game.player()
    if lk == null:
        return
    var here := Game.sea_room_at(lk.global_position) if name.begins_with("sea") else 0
    if here == stream_room and not force:
        _stream_pending = -1
        _stream_hold = 0
        return
    # HYSTERESIS.  sea_room_at is a hard grid lookup, so a player sitting on a room boundary
    # - or a boat bobbing across one - flips between two rooms every few frames, and each
    # flip shows and hides whole island subtrees.  That is the "buildings glitching in and
    # out" in the distance.  A room has to win several checks in a row before we act on it.
    if not force:
        if here != _stream_pending:
            _stream_pending = here
            _stream_hold = 1
            return
        _stream_hold += 1
        if _stream_hold < STREAM_CONFIRM:
            return
    _stream_pending = -1
    _stream_hold = 0
    stream_room = here
    var want := {}
    if here >= 0 and here < room_sets.size():
        var entry: Dictionary = room_sets[here]
        for r in entry.get("rooms", []):
            want[int(r)] = true
    else:
        want[here] = true
    if want == resident and not force:
        return
    resident = want
    var on := 0
    for rn in room_nodes:
        var vis: bool = want.has(int(rn))
        if vis:
            on += 1
        for n in room_nodes[rn]:
            if n is Node3D:
                (n as Node3D).visible = vis
    if Game.scripted():
        print("gcrip stream: room ", here, " -> resident ", want.keys(), " (", on, " of ",
            room_nodes.size(), " room subtrees drawn)")


func _apply_toon() -> void:
    # shading: every surface in this stage goes through the chosen look.  Actors are walked
    # with their archive name so the material table can recognise a sword or a sail.
    var n := Game.toonify(get_node_or_null("Level"), "")
    for a in get_children():
        if not (a is Node3D) or not String(a.name).begins_with("A_"):
            continue
        var arc := str(a.get_meta("archive")) if a.has_meta("archive") else ""
        n += Game.toonify(a, arc)
    if n > 0:
        print("gcrip: cel shading on ", n, " surfaces in ", name)

const HIT_SWITCHES := ["Qdghd", "Ykzyg", "MhmrSW0", "bonbori", "SW_HIT0"]

func _spawn_hit_switches() -> void:
    # these are model-less or unmodelled, so they come from the placement lists directly
    var info: Dictionary = Game.stage_data.get(name, {})
    var n := 0
    for lst in ["logic", "actors"]:
        for rec in info.get(lst, []):
            var act := str(rec.get("actor", ""))
            if not HIT_SWITCHES.has(act):
                continue
            var lay := int(rec.get("layer", -1))
            var rm: int = int(rec["room"]) if rec.get("room") != null else 0
            if lay >= 0 and lay != Game.story_layer(name, rm):
                continue
            var sw := StaticBody3D.new()
            sw.set_script(load("res://actors/hit_switch.gd"))
            sw.name = "HitSw_%s_%d" % [act, n]
            add_child(sw)
            sw.global_position = Vector3(rec["pos"][0], rec["pos"][1], rec["pos"][2])
            sw.setup_switch(act, int(rec["params"]), rm)
            n += 1
    if n > 0:
        print("gcrip: ", n, " hit switches in ", name)

# Only doors whose MESH resolved get wrapped by _wrap_actors, and several locked kinds
# (keyshut, keyS12, ZenS12, doorSH) have no model in the exported level - which would leave
# every small-key door in the game permanently open.  Place those from the record.
func _spawn_missing_doors() -> void:
    var info: Dictionary = Game.stage_data.get(name, {})
    var have: Dictionary = {}
    for d in get_tree().get_nodes_in_group("door"):
        have[str(d.get("node_name"))] = true
    var n := 0
    for rec in info.get("actors", []):
        var act := str(rec.get("actor", ""))
        if not SCRIPTS.has(act) or SCRIPTS[act] != "res://actors/door.gd":
            continue
        var nn: String = str(rec.get("node", "")).replace(".", "_").replace(":", "_")
        if have.has(nn):
            continue
        var lay := int(rec.get("layer", -1))
        var rm: int = int(rec["room"]) if rec.get("room") != null else -1
        if lay >= 0 and lay != Game.story_layer(name, rm):
            continue
        var dn := StaticBody3D.new()
        dn.set_script(load("res://actors/door.gd"))
        dn.name = "Door_%s_%d" % [act, n]
        add_child(dn)
        dn.global_position = Vector3(rec["pos"][0], rec["pos"][1], rec["pos"][2])
        dn.set("node_name", nn)
        dn.setup_door(act, int(rec["params"]), rec.get("rot", [0, 0, 0]),
            float(rec.get("rot_y_deg", 0.0)))
        n += 1
    if n > 0:
        print("gcrip: ", n, " doors with no model placed from the record in ", name)

const SALVAGE_NAMES := ["Salvage", "Salvag2", "SalvagN", "SwSlvg", "SalvFM", "SalvagE"]

func _spawn_salvage() -> void:
    # model-less points: they come through the exporter's "logic" list, not "actors"
    var info: Dictionary = Game.stage_data.get(name, {})
    var n := 0
    for rec in info.get("logic", []):
        if not SALVAGE_NAMES.has(str(rec.get("actor", ""))):
            continue
        var rot: Array = rec.get("rot", [0, 0, 0])
        var sp := Node3D.new()
        sp.set_script(load("res://actors/salvage.gd"))
        sp.name = "Salvage_%d" % n
        add_child(sp)
        sp.global_position = Vector3(rec["pos"][0], rec["pos"][1], rec["pos"][2])
        sp.add_to_group("salvage")
        sp.setup(int(rec["params"]), int(rot[2]),
            int(rec["room"]) if rec.get("room") != null else 0,
            rec.get("scale", [1, 1, 1]))
        n += 1
    if n > 0:
        print("gcrip: ", n, " salvage points in ", name)

# tag volumes that watch a named NPC instead of Link (actors/npc_tag.gd).  These live in
# the same "tags" list as TagEv, but they are their own pass: TagEv is a player trigger and
# must keep firing on body_entered, while these never touch the physics server at all.
const NPC_TAGS := ["TagMd"]

func _spawn_npc_tags() -> void:
    var info: Dictionary = Game.stage_data.get(name, {})
    var table: Array = info.get("event_table", [])
    var m := 0
    for rec in info.get("tags", []):
        var act := str(rec.get("actor", ""))
        if not NPC_TAGS.has(act):
            continue
        var rm: int = int(rec["room"]) if rec.get("room") != null else 0
        var rot: Array = rec.get("rot", [0, 0, 0])
        var vol := Area3D.new()
        vol.set_script(load("res://actors/npc_tag.gd"))
        vol.name = "%s_%d" % [act, m]
        add_child(vol)
        vol.global_position = Vector3(rec["pos"][0], rec["pos"][1], rec["pos"][2])
        vol.setup(int(rec["params"]), int(rot[2]), rm, table, rec.get("scale", [1, 1, 1]), act)
        m += 1
    if m > 0:
        print("gcrip: ", m, " NPC tag volumes in ", name)

func _spawn_hit_objects() -> void:
    # Objects the player breaks by hitting them.  They come from the mined story step rather
    # than from this stage's actor list, because the one the graph has - the Ajav rock wall
    # over Jabun's cave - never reached the rip: no ACTR record, no baked model.  A step
    # whose hit block has no pos is reported and skipped (see _STORY_HIT in godot.py); the
    # moment a placement does show up, SCRIPTS wraps it in _wrap_actors instead and this
    # loop skips it.
    var n := 0
    var info: Dictionary = Game.stage_data.get(name, {})
    for step in Game.story_hit_steps():
        var hit: Dictionary = step.get("hit", {})
        var who := str(hit.get("actor", ""))
        if who != "" and Game._find_actor(who) != null:
            continue
        var pos = hit.get("pos")
        var rot_y := float(hit.get("rot_y_deg", 0.0))
        if not (pos is Array) or (pos as Array).size() < 3:
            # model-less actors come through as "logic" records; the wall is one of them, on
            # the story layers of the endless night.  Placement coordinates are world space,
            # the scene is recentred, hence the offset
            for rec in info.get("logic", []):
                if str(rec.get("actor", "")) != who:
                    continue
                var lay := int(rec.get("layer", -1))
                var rm := int(rec.get("room", -1))
                if lay >= 0 and lay != Game.story_layer(name, rm):
                    continue
                if hit.get("room") != null and rm != int(hit["room"]):
                    continue
                var rp: Array = rec.get("pos", [])
                if rp.size() >= 3:
                    pos = [float(rp[0]) - Game.world_offset.x, float(rp[1]) - Game.world_offset.y,
                        float(rp[2]) - Game.world_offset.z]
                    rot_y = float(rec.get("rot_y_deg", rot_y))
                    if hit.get("params") == null:
                        hit = hit.duplicate()
                        hit["params"] = int(rec.get("params", 0))
                        step = step.duplicate()
                        step["hit"] = hit
                    break
        if not (pos is Array) or (pos as Array).size() < 3:
            print("gcrip hit: ", Game.sfield(step, "id"), " (", who,
                ") is not placed on this stage's current story layer - nothing spawned")
            continue
        spawn_hit_object(step, Vector3(float(pos[0]), float(pos[1]), float(pos[2])), rot_y)
        n += 1
    if n > 0:
        print("gcrip: ", n, " breakable story objects in ", name)

func spawn_hit_object(step: Dictionary, pos: Vector3, rot_y_deg: float) -> Node3D:
    # also the debug channel way in (control.gd "story_place" with hit: true), so the
    # mechanic can be exercised before the Ajav placement is recovered
    var hit: Dictionary = step.get("hit", {})
    var node := StaticBody3D.new()
    node.set_script(load("res://actors/hit_object.gd"))
    node.name = "Hit_%s" % str(hit.get("actor", "obj"))
    add_child(node)
    node.global_position = pos
    node.setup_hit(str(hit.get("actor", "")), int(hit.get("params", 0)), null, rot_y_deg, step)
    return node

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
    Game.load_events(name)
    if Game.events.has("StartCamera"):
        # the stage's arrival camera (e.g. Orca's house); two frames so the player is placed
        await get_tree().physics_frame
        await get_tree().physics_frame
        Game.run_event("StartCamera")

func _process(_delta: float) -> void:
    _dome_follow()
    _ocean_tick()
    if Engine.get_process_frames() % 30 == 0:
        _light_tick()
    if not room_nodes.is_empty() and Engine.get_process_frames() % 20 == 0:
        _stream_update()
    if name != "sea":
        return
    _bgm_tick += 1
    if _bgm_tick % 60 == 0:  # crossing into another island's room changes the theme
        Game.play_bgm("sea", _room_hint())

# Some villagers are placed several times in ONE room (layer -1) as story variants that the
# actor itself picks between by event bits - Grandma is in LinkRM four times. Until those
# actors read the bits, keep the fresh-file variant, but NEVER hide every copy: if no
# instance carries the wanted type we keep the first one (that bug emptied Outset's lookout,
# where both Ls1 instances are types 3 and 0 and the table wanted 4).
const FRESH_TYPE := {"Ba1": 0, "Ls1": 4, "Aj1": 0, "Ob1": 0, "Yw1": 0, "Ym1": 0, "Ym2": 2, "Ko1": 2, "Ko2": 0}

func _wrap_actors() -> void:
    var level := get_node_or_null("Level")
    var info: Dictionary = Game.stage_data.get(name, {})
    if level == null:
        return
    var n := 0
    var hidden := 0
    for rec in info.get("actors", []):
        var actor: String = rec["actor"]
        # story layers: -1 is always placed, otherwise only the layer the save's state selects
        var lay := int(rec.get("layer", -1))
        var rm: int = int(rec["room"]) if rec.get("room") != null else -1   # stage.dzs loads with -1
        if lay >= 0 and lay != Game.story_layer(name, rm):
            var off := level.find_child(str(rec["node"]).replace(".", "_"), true, false)
            if off and off is Node3D:
                (off as Node3D).visible = false
            hidden += 1
            continue
        if _drop_variant(info, rec, actor):
            var ghost := level.find_child(str(rec["node"]).replace(".", "_"), true, false)
            if ghost and ghost is Node3D:
                (ghost as Node3D).visible = false
            continue
        var script_path := ""
        if SCRIPTS.has(actor):
            script_path = SCRIPTS[actor]
        elif Game.enemies.has(actor):
            # anything with a mined enemy profile wraps itself, so a newly mined boss starts
            # existing the moment its ww_enemies_*.json lands; SCRIPTS above is only for actors
            # that need a SPECIALISED script (bokoblin.gd, pig.gd, ...)
            script_path = "res://actors/enemy.gd"
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
        node.set_meta("archive", str(rec.get("model", "")).get_file().get_basename())
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
            if am.has("head") and ResourceLoader.exists(str(am["head"])):
                _attach_head(rig, str(am["head"]))
        var params: int = int(rec["params"])
        var rot_y: float = float(rec.get("rot_y_deg", 0.0))
        var rot: Array = rec.get("rot", [0, 0, 0])
        if script_path.ends_with("carriable.gd"):
            node.setup(actor, params, mesh)
        elif script_path.ends_with("item.gd"):
            node.setup(params, mesh, true)
        elif script_path.ends_with("sign.gd"):
            node.setup(params, mesh, rot_y)
        elif script_path.ends_with("door.gd"):
            node.set("node_name", node_name)
            node.setup_door(actor, params, rec.get("rot", [0, 0, 0]), rot_y)
        elif script_path.ends_with("chest.gd"):
            node.setup(int(rot[2]), mesh, rot_y, params)
        elif script_path.ends_with("pickup.gd"):
            node.setup(actor, params, mesh)
        elif script_path.ends_with("npc.gd") or script_path.ends_with("enemy.gd"):
            node.setup(actor, params, mesh, rot_y)
            if script_path.ends_with("enemy.gd"):
                node.set("room", int(rec.get("room", 0)))
        elif script_path.ends_with("hit_object.gd"):
            # a real placement for a breakable story object: hand it the step it belongs to
            var hstep: Dictionary = {}
            for st2 in Game.story_hit_steps():
                var hb: Dictionary = st2.get("hit", {})
                if str(hb.get("actor", "")) == actor:
                    hstep = st2
                    break
            node.setup_hit(actor, params, mesh, rot_y, hstep)
        else:
            node.setup(params, mesh, rot_y)
        n += 1
        Game._npc_spawn_bits(actor)
    print("gcrip: ", n, " actors wrapped in ", name, " (", hidden, " on other story layers)")


func _attach_head(rig: Node3D, head_path: String) -> void:
    # the head model rides the body's "head" bone (J3D joint names survive the glTF export)
    var head: Node3D = load(head_path).instantiate()
    var skel: Skeleton3D = null
    for n in rig.find_children("*", "Skeleton3D", true, false):
        skel = n
        break
    if skel != null and skel.find_bone("head") >= 0:
        var att := BoneAttachment3D.new()
        att.bone_name = "head"
        skel.add_child(att)
        att.add_child(head)
        # the head models are authored in the head joint's own frame: identity on the bone
        head.transform = Transform3D()
    else:
        rig.add_child(head)

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

_SHIP_GD = 'extends CharacterBody3D\n# gcrip: the King of Red Lions (d_a_ship.cpp). Tiller / yaw, wind-driven sail speed,\n# paddling, buoyancy spring on the wave heightfield, four-probe wave tilt, hull circles.\n# Units per frame at 30 Hz; s16 angles kept as floats where the decomp uses them.\n\nconst S16 := PI / 32768.0\nconst TILLER_MAX := 0x2000\nconst TILLER_SPEED := 700.0\nconst WIND_INC_SPEED := 55.0\nconst PADDLE_SPEED := 10.0\nconst BURST_CAP := 80.0\nconst HULL_R := 250.0\nconst SEAT := Vector3(0.0, 15.0, -35.0)\nconst LEDGE_L := Vector3(57.0, 35.0, -35.0)\nconst LEDGE_R := Vector3(-57.0, 35.0, -35.0)\nconst JUMP_MIN_FWD := 16.5\nconst JUMP_MIN_WIND := 11.0\nconst FLY_GRAVITY := -2.5\nconst FLY_PITCH := -0x800 * PI / 32768.0\n\nenum Mode { WAIT, PADDLE, STEER }\nvar mode: int = Mode.WAIT\nvar rider: Node3D = null\nvar yaw := 0.0              # radians, atan2(x, z) convention like Link\'s facing\nvar tiller := 0.0           # s16 units\nvar speed_f := 0.0\nvar burst_target := 1.0e9\nvar sail_on := false\nvar braking := false\nvar vy := 0.0\nvar bob := 0.0\nvar pitch := 0.0            # s16 units (positive = nose down)\nvar roll := 0.0\nvar pitch_vel := 0.0\nvar roll_vel := 0.0\nvar noise_a := 0.0\nvar noise_b := 0.0\nvar heel := 0.0\nvar heel_vel := 0.0\nvar prev_yaw := 0.0\nvar landing := 0\nvar model: Node3D = null\nvar sail_mesh: MeshInstance3D = null\nvar sail_raise := 0.0          # 0 stowed .. 1 up\nvar wake_l: CPUParticles3D = null\nvar wake_r: CPUParticles3D = null\nvar flying := false\nvar fly_vy := 0.0\nvar jump_ok := false\nvar fly_pitch := 0.0\n\nfunc setup(rot_y_deg: float) -> void:\n    yaw = deg_to_rad(rot_y_deg)\n    prev_yaw = yaw\n    collision_layer = 0\n    collision_mask = 1\n    var shape := CollisionShape3D.new()\n    var cyl := CylinderShape3D.new()\n    cyl.radius = HULL_R\n    cyl.height = 150.0\n    shape.shape = cyl\n    shape.position.y = 150.0   # wall circles only: keep the hull clear of the seabed\n    add_child(shape)\n    motion_mode = CharacterBody3D.MOTION_MODE_FLOATING\n    add_to_group("interact")\n    model = Node3D.new()\n    add_child(model)\n    for part in ["ship", "ship_head"]:\n        var path := "res://items/%s.glb" % part\n        if ResourceLoader.exists(path):\n            model.add_child(load(path).instantiate())\n    _build_sail()\n    _build_wake()\n    global_position.y = Game.sea_height(global_position.x, global_position.z)\n    _update_transform()\n\nfunc _build_sail() -> void:\n    # the game\'s sail is a cloth grid actor (d_a_grid) with no model: a red triangle on the mast\n    var im := ImmediateMesh.new()\n    var mat := StandardMaterial3D.new()\n    mat.albedo_color = Color(0.75, 0.12, 0.1)\n    mat.cull_mode = BaseMaterial3D.CULL_DISABLED\n    mat.shading_mode = BaseMaterial3D.SHADING_MODE_PER_PIXEL\n    im.surface_begin(Mesh.PRIMITIVE_TRIANGLES, mat)\n    # mast foot (0, 60, 40), mast top (0, 340, 40), boom end (0, 80, -170): a lateen sail\n    var a := Vector3(0, 70.0, 40.0)\n    var b := Vector3(0, 330.0, 40.0)\n    var c := Vector3(0, 90.0, -180.0)\n    for tri in [[a, b, c], [a, c, b]]:\n        var n: Vector3 = (tri[1] - tri[0]).cross(tri[2] - tri[0]).normalized()\n        for v in tri:\n            im.surface_set_normal(n)\n            im.surface_add_vertex(v)\n    im.surface_end()\n    sail_mesh = MeshInstance3D.new()\n    sail_mesh.mesh = im\n    sail_mesh.scale = Vector3(1.0, 0.01, 1.0)\n    sail_mesh.visible = false\n    add_child(sail_mesh)\n    var mast := MeshInstance3D.new()\n    var cyl := CylinderMesh.new()\n    cyl.top_radius = 4.0\n    cyl.bottom_radius = 6.0\n    cyl.height = 290.0\n    mast.mesh = cyl\n    var mm := StandardMaterial3D.new()\n    mm.albedo_color = Color(0.45, 0.3, 0.15)\n    mast.material_override = mm\n    mast.position = Vector3(0, 200.0, 40.0)\n    add_child(mast)\n\nfunc _build_wake() -> void:\n    for side in [-1.0, 1.0]:\n        var p := CPUParticles3D.new()\n        p.amount = 40\n        p.lifetime = 0.9\n        p.emitting = false\n        p.position = Vector3(-80.0 * side, -40.0, 140.0)\n        p.direction = Vector3(side * 0.5, 1.0, -0.3)\n        p.spread = 25.0\n        p.initial_velocity_min = 120.0\n        p.initial_velocity_max = 220.0\n        p.gravity = Vector3(0, -300.0, 0)\n        p.scale_amount_min = 6.0\n        p.scale_amount_max = 14.0\n        var qm := QuadMesh.new()\n        qm.size = Vector2(1.0, 1.0)\n        p.mesh = qm\n        var pm := StandardMaterial3D.new()\n        pm.albedo_color = Color(0.9, 0.95, 1.0, 0.7)\n        pm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA\n        pm.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED\n        pm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED\n        p.material_override = pm\n        add_child(p)\n        if side < 0.0:\n            wake_l = p\n        else:\n            wake_r = p\n\nfunc forward() -> Vector3:\n    return Vector3(sin(yaw), 0.0, cos(yaw))\n\nfunc right() -> Vector3:\n    return forward().cross(Vector3.UP)\n\n# --- Link-side interaction API ---\nfunc interact_prompt(link: Node3D) -> String:\n    if rider != null or mode != Mode.WAIT:\n        return ""\n    return "Ride" if link.global_position.distance_to(global_position) < 420.0 else ""\n\nfunc interact(link: Node3D) -> void:\n    if rider == null and link.has_method("board"):\n        link.board(self)\n\nfunc set_rider(link: Node3D) -> void:\n    rider = link\n    mode = Mode.PADDLE\n    sail_on = false\n\nfunc clear_rider() -> void:\n    rider = null\n    mode = Mode.WAIT\n    sail_on = false\n\nfunc try_jump() -> bool:\n    # procSteerMove: R with the sail up, enough way on and wind -> hop (FLY | JUMP)\n    if not jump_ok or flying:\n        return false\n    flying = true\n    fly_vy = clampf(_wind_speed(), 15.0, 40.0)\n    tiller *= 0.5\n    return true\n\nfunc toggle_sail() -> void:\n    if sail_on:\n        sail_on = false\n        mode = Mode.PADDLE\n        return\n    sail_on = true\n    mode = Mode.STEER\n    # raising the sail: instant burst to 2x the wind speed (cap 80), decays to the wind speed\n    var ws := _wind_speed()\n    speed_f = maxf(speed_f, minf(ws * 2.0, BURST_CAP))\n    burst_target = ws\n\nfunc seat_point() -> Vector3:\n    return global_transform * SEAT\n\nfunc ledge_point(left: bool) -> Vector3:\n    return global_transform * (LEDGE_L if left else LEDGE_R)\n\n# --- cLib helpers ---\nstatic func add_calc(v: float, target: float, scale: float, max_step: float, min_step: float) -> float:\n    var step := (target - v) * scale\n    step = clampf(step, -max_step, max_step)\n    if absf(step) < min_step:\n        step = signf(target - v) * minf(min_step, absf(target - v))\n    return v + step\n\nstatic func add_calc_angle(v: float, target: float, scale: float, max_step: float, min_step: float) -> float:\n    var diff := target - v\n    var step := clampf(diff / scale, -max_step, max_step)\n    if absf(step) <= min_step:\n        step = signf(diff) * minf(min_step, absf(diff))\n    return v + step\n\nfunc _wind_speed() -> float:\n    var w: Vector3 = Game.wind_vec()\n    var pow01: float = minf(1.0, Game.wind_power / 0.5)\n    var a := absf(wrapf(atan2(w.x, w.z) - yaw, -PI, PI)) / S16   # 0..0x8000\n    var f: float\n    if a < 0x4000:\n        f = 1.0 - a / 65536.0\n    elif a <= 0x6000:\n        f = 0.75 - (a - 0x4000) * 5.493164e-5\n    else:\n        f = maxf(0.0, 0.3 - (a - 0x6000) * 3.2967e-4)\n    return pow01 * f * WIND_INC_SPEED\n\nfunc _decrement(target: float) -> void:\n    speed_f = add_calc(speed_f, target, 0.05, 0.1, 0.015)\n\nfunc _first_decrement(target: float) -> void:\n    speed_f = add_calc(speed_f, target, 0.1, 5.0, 1.0)\n\nfunc _physics_process(_delta: float) -> void:\n    var stick_fwd := 0.0\n    var stick_right := 0.0\n    if rider and is_instance_valid(rider):\n        var s: Vector2 = rider.stick()   # raw pad: x right, y forward (the ship ignores the camera)\n        if s.length() > 0.1:\n            stick_fwd = clampf(s.y, -1.0, 1.0)\n            stick_right = clampf(s.x, -1.0, 1.0)\n    else:\n        mode = Mode.WAIT\n    # tiller and yaw (setSelfMove / setMoveAngle)\n    var tiller_target := stick_right * TILLER_MAX if mode != Mode.WAIT else 0.0\n    tiller = add_calc_angle(tiller, tiller_target, 4.0, TILLER_SPEED, 0x100)\n    var turn_rate := clampf(4.0 - absf(speed_f) / 55.0 * 3.0, 0.1, 3.6)\n    if landing > 0:\n        landing -= 1\n        turn_rate += (3.6 - turn_rate) * minf(landing, 15) / 15.0\n    prev_yaw = yaw\n    if not flying:\n        yaw -= turn_rate * (tiller / 64.0) * S16\n    # forward speed\n    match mode:\n        Mode.WAIT:\n            speed_f = add_calc(speed_f, 0.0, 0.1, 1.0, 0.05)\n        Mode.PADDLE:\n            if braking and speed_f >= 3.0:\n                speed_f = add_calc(speed_f, 0.0, 0.1, 1.0, 0.1)\n            else:\n                _decrement(maxf(stick_fwd, 0.0) * PADDLE_SPEED)\n        Mode.STEER:\n            var ws := _wind_speed()\n            if burst_target < speed_f:\n                _first_decrement(burst_target)\n                if speed_f - burst_target < 3.0:\n                    burst_target = 1.0e9\n            elif not sail_on or ws <= 0.0:\n                _decrement(stick_fwd * PADDLE_SPEED)\n            elif speed_f >= ws:\n                _decrement(ws)\n            else:\n                speed_f = add_calc(speed_f, ws, 0.1, 0.5, 0.1)\n    jump_ok = sail_on and mode == Mode.STEER and not flying and speed_f > JUMP_MIN_FWD and _wind_speed() >= JUMP_MIN_WIND\n    # sail raise / lower animation and the wake\n    sail_raise = move_toward(sail_raise, 1.0 if sail_on else 0.0, 0.1)\n    if sail_mesh:\n        sail_mesh.visible = sail_raise > 0.02\n        sail_mesh.scale = Vector3(1.0, maxf(sail_raise, 0.01), 1.0)\n    var wake_on: bool = absf(speed_f) > 11.0 and not flying\n    if wake_l:\n        wake_l.emitting = wake_on\n        wake_r.emitting = wake_on\n    # hull against the islands\n    var before := global_position\n    velocity = forward() * speed_f * 30.0\n    move_and_slide()\n    global_position.y = before.y   # the water, not the collider, owns the height\n    if is_on_wall():\n        var n := get_wall_normal()\n        if n.dot(forward()) < cos(0x5000 * S16):   # normal > 112.5 deg off the heading: head-on\n            _first_decrement(0.0)\n    var water_y: float = Game.sea_height(global_position.x, global_position.z)\n    if flying:\n        # airborne: gravity -2.5, no steering, nose lifts toward -0x800; land on the water\n        fly_vy += FLY_GRAVITY\n        global_position.y += fly_vy\n        fly_pitch = lerpf(fly_pitch, FLY_PITCH, 0.1)\n        if fly_vy < 0.0 and global_position.y <= water_y:\n            global_position.y = water_y\n            flying = false\n            vy = maxf(fly_vy, -15.0) * 0.5\n            speed_f *= 0.85\n            landing = 30\n            fly_pitch = 0.0\n        _update_transform(pitch * S16 + fly_pitch, (roll + heel) * S16)\n        return\n    # follow the water (setYPos): proportional pull + buoyancy spring, bob, clamp\n    var r := minf(1.0, absf(speed_f) / 55.0)\n    var y := global_position.y\n    y += r * (water_y - y) * 0.1\n    vy += (water_y - y) * 0.05\n    vy = clampf(vy, -20.0, 20.0)\n    y += vy\n    bob += (1000.0 + randf() * 1000.0 + 500.0 * r) * S16\n    y += r * 0.25 * sin(bob) + 0.6\n    vy = add_calc(vy, 0.0, 0.05, 1.0, 0.05)\n    y = clampf(y, water_y - 60.0, water_y + 40.0)\n    global_position.y = y\n    # wave tilt (setWaveAngle): four probes, second-order follow\n    var xf := global_transform\n    var front := Game.sea_height((xf * Vector3(0, 0, 180)).x, (xf * Vector3(0, 0, 180)).z)\n    var back := Game.sea_height((xf * Vector3(0, 0, -190)).x, (xf * Vector3(0, 0, -190)).z)\n    var rgt := Game.sea_height((xf * Vector3(-80, 0, 0)).x, (xf * Vector3(-80, 0, 0)).z)\n    var lft := Game.sea_height((xf * Vector3(80, 0, 0)).x, (xf * Vector3(80, 0, 0)).z)\n    var pitch_t := atan2(-(front - back), 370.0) / S16\n    var roll_t := atan2(-(rgt - lft), 160.0) / S16\n    pitch_vel += (pitch_t - pitch) * 0.045\n    pitch += pitch_vel\n    pitch_vel = add_calc_angle(pitch_vel, 0.0, 0x14, 0x1000, 4)\n    roll_vel += (roll_t - roll) * 0.045\n    roll += roll_vel\n    roll_vel = add_calc_angle(roll_vel, 0.0, 0x14, 0x1000, 4)\n    noise_a += (0.5 * r + 1.0) * (800.0 + randf() * 800.0) * S16\n    noise_b += (0.5 * r + 1.0) * (600.0 + randf() * 600.0) * S16\n    var pitch_noise := r * 100.0 * sin(noise_a) + 30.0\n    var roll_noise := r * 115.0 * sin(noise_b) + 35.0\n    # steering heel spring\n    var heel_t := clampf(wrapf(yaw - prev_yaw, -PI, PI) / S16 * 7.0, -0x600, 0x600)\n    heel_vel += 0.05 * (heel_t - heel)\n    heel += heel_vel\n    heel_vel = add_calc_angle(heel_vel, 0.0, 0x14, 0x1000, 4)\n    _update_transform((pitch + pitch_noise) * S16, (roll + roll_noise + heel) * S16)\n    if before.distance_to(global_position) > 1.0e6:\n        global_position = before\n\nfunc _update_transform(p := 0.0, r := 0.0) -> void:\n    rotation = Vector3(p, yaw, r)\n'

_EVENT_GD = 'extends Node\n# gcrip: runs one event_list.dat event (d_event_manager.cpp semantics, simplified).\n# Every staff (cast member) walks its cut list; a cut starts when its start flags are set\n# (or, with start flag -1, when the previous cut of that staff ended) and sets its end flag\n# when its action completes. The event ends when every staff is out of cuts (or 60 s).\n\nsignal finished\n\nconst TIMEOUT := 30 * 15   # a stuck script must not lock the game for a minute\nconst LINK_EVENT_WALK := 8.0\n\nvar ev: Dictionary = {}\nvar flags: Dictionary = {}\nvar staffs: Array = []\nvar frames := 0\nvar stalled := 0            # frames since any staff last advanced\nvar link: Node3D = null\nvar fade_dir := 1   # alternate FADE cuts: out, then in\n\nfunc start(event: Dictionary) -> void:\n    ev = event\n    link = Game.player()\n    for sf in ev.get("actors", []):\n        staffs.append({"data": sf, "idx": 0, "cur": null, "node": _find_node(sf)})\n    Game.event_running = true\n    if link and link.has_method("event_begin"):\n        link.event_begin()\n\nfunc _find_node(sf: Dictionary) -> Node:\n    var nm: String = sf.get("name", "")\n    if nm == "Link":\n        return link\n    if sf.get("type", "") != "NORMAL":\n        return null\n    for grp in ["interact", "enemy"]:\n        for n in get_tree().get_nodes_in_group(grp):\n            if is_instance_valid(n) and str(n.get("actor")) == nm:\n                return n\n    return null\n\nfunc _set_flag(flag: int) -> void:\n    if flag >= 0:\n        flags[flag] = true\n\nfunc _ready_to_start(st: Dictionary, cut: Dictionary) -> bool:\n    var sfl: Array = cut.get("start_flags", [-1, -1, -1])\n    if int(sfl[0]) == -1:\n        return true   # follows the previous cut of this staff\n    for f in sfl:\n        if int(f) >= 0 and not flags.has(int(f)):\n            return false\n    return true\n\nfunc _physics_process(_delta: float) -> void:\n    frames += 1\n    var alive := false\n    var moved := false\n    for st in staffs:\n        var acts: Array = st["data"].get("actions", [])\n        if st["cur"] == null:\n            if st["idx"] >= acts.size():\n                continue\n            var cut: Dictionary = acts[st["idx"]]\n            if not _ready_to_start(st, cut) and stalled < 90:\n                alive = true\n                continue\n            if not _ready_to_start(st, cut):\n                # nothing has moved for 3 s: a start flag this cut waits on is never produced\n                # (our runner does not implement every actor action), so let it through\n                print("gcrip event: unblocking ", st["data"].get("name", "?"), " cut ",\n                      cut.get("name", "?"), " in ", ev.get("name", "?"))\n            st["cur"] = {"cut": cut, "t": 0, "dialog_seen": false, "from_eye": Vector3.ZERO,\n                         "from_center": Vector3.ZERO, "from_fov": 60.0}\n            _begin(st, st["cur"])\n        var cur: Dictionary = st["cur"]\n        alive = true\n        if _tick(st, cur):\n            _set_flag(int(cur["cut"].get("end_flag", -1)))\n            st["cur"] = null\n            st["idx"] += 1\n            moved = true\n    stalled = 0 if moved else stalled + 1\n    if Game.scripted() and frames % 60 == 0:\n        var report := []\n        for st in staffs:\n            var acts2: Array = st["data"].get("actions", [])\n            var cn: String = "-" if st["cur"] == null else str(st["cur"]["cut"].get("name", "?"))\n            report.append("%s[%d/%d]%s" % [st["data"].get("name", "?"), st["idx"], acts2.size(), cn])\n        print("gcrip event ", ev.get("name", "?"), " f", frames, ": ", " ".join(report), "  link=", link.global_position.round() if link else "?", " walking=", str(link.get("ev_walking")) if link else "?")\n    if not alive or frames > TIMEOUT:\n        _finish()\n\nfunc _prop(cut: Dictionary, key: String, default = null):\n    var props: Dictionary = cut.get("properties", {})\n    if props.has(key):\n        return props[key]["value"]\n    return default\n\nfunc _num(v, dflt: float) -> float:\n    # a cut property is often authored as a one-element list, and int([30]) throws\n    if v is Array:\n        return _num(v[0], dflt) if (v as Array).size() > 0 else dflt\n    if v is float or v is int or v is bool:\n        return float(v)\n    if v is String and (v as String).is_valid_float():\n        return float(v)\n    return dflt\n\nfunc _vec(v) -> Vector3:\n    if v is Array and v.size() >= 3:\n        var p := Vector3(float(v[0]), float(v[1]), float(v[2]))\n        if v[0] is Array:\n            p = Vector3(float(v[0][0]), float(v[0][1]), float(v[0][2]))\n        return p - Game.world_offset\n    return Vector3.ZERO\n\nfunc _begin(st: Dictionary, cur: Dictionary) -> void:\n    var cut: Dictionary = cur["cut"]\n    var kind: String = st["data"].get("type", "")\n    var name: String = cut.get("name", "")\n    var node: Node = st["node"]\n    match kind:\n        "CAMERA":\n            cur["from_eye"] = Game.event_cam_eye()\n            cur["from_center"] = Game.event_cam_center()\n            cur["from_fov"] = Game.event_cam_fov()\n            match name:\n                "FIXEDPOS":\n                    var c: Vector3 = (link.global_position + Vector3(0, 100.0, 0)) if link else cur["from_center"]\n                    Game.set_event_cam(_vec(_prop(cut, "Eye")), c, _num(_prop(cut, "Fovy", 60.0), 60.0))\n                "FIXEDFRM":\n                    Game.set_event_cam(_vec(_prop(cut, "Eye")), _vec(_prop(cut, "Center")), _num(_prop(cut, "Fovy", 60.0), 60.0))\n                "PAUSE", "CHECK", "RESTOREPOS", "STYLE":\n                    Game.set_event_cam(cur["from_eye"], cur["from_center"], cur["from_fov"])\n                "TALK", "TURNTOACTOR":\n                    var who := _talker()\n                    if who and link:\n                        var a: Vector3 = link.global_position + Vector3(0, 100.0, 0)\n                        var b: Vector3 = who.global_position + Vector3(0, 100.0, 0)\n                        var mid := (a + b) * 0.5\n                        var side := (b - a).cross(Vector3.UP).normalized()\n                        if side.length() < 0.5:\n                            side = Vector3.RIGHT\n                        Game.set_event_cam(mid + side * 300.0 + Vector3(0, 60.0, 0), mid, 50.0)\n                    else:\n                        Game.set_event_cam(cur["from_eye"], cur["from_center"], cur["from_fov"])\n                "GETITEM", "USEITEM0":\n                    if link:\n                        var c2: Vector3 = link.global_position + Vector3(0, 110.0, 0)\n                        var fwd: Vector3 = link.forward()\n                        Game.set_event_cam(c2 + fwd * 260.0 + Vector3(0, 40.0, 0), c2, 55.0)\n        "DIRECTOR":\n            if name == "FADE":\n                var t := int(_num(_prop(cut, "Timer", 30), 30.0))\n                Game.fade(1.0 if fade_dir > 0 else 0.0, maxi(t, 1))\n                fade_dir = -fade_dir\n        "SOUND":\n            if name == "BGMSTOP" and Game.bgm_player:\n                Game.bgm_player.stop()\n        "PACKAGE":\n            if name == "PLAY":\n                var file := str(_prop(cut, "FileName", ""))\n                var off = _prop(cut, "OffsetPos")\n                var ang := _num(_prop(cut, "OffsetAngY", 0.0), 0.0)\n                var opos := Vector3.ZERO\n                if off is Array and off.size() >= 3 and not (off[0] is Array):\n                    opos = Vector3(float(off[0]), float(off[1]), float(off[2]))\n                elif off is Array and off.size() >= 1 and off[0] is Array:\n                    opos = Vector3(float(off[0][0]), float(off[0][1]), float(off[0][2]))\n                Game.play_cutscene(file.get_basename(), opos, ang)\n        "NORMAL":\n            if node == link and link:\n                _begin_link(cur, name, cut)\n            else:\n                _begin_actor(node, cur, name, cut)\n\nfunc _talker() -> Node3D:\n    for st in staffs:\n        if st["data"].get("type", "") == "NORMAL" and st["node"] != null and st["node"] != link:\n            return st["node"]\n    return null\n\nfunc _begin_link(cur: Dictionary, name: String, cut: Dictionary) -> void:\n    if name.begins_with("002") or name.contains("walk"):\n        var pos = _prop(cut, "pos")\n        if pos != null:\n            if Game.scripted():\n                print("gcrip event: walk ", link.global_position.round(), " -> ", _vec(pos).round())\n            link.event_walk_to(_vec(pos))\n        else:\n            link.event_clip("walk")\n    elif name.contains("talk"):\n        link.event_clip("talka")\n    elif name.contains("get_item"):\n        var item := int(_num(_prop(cut, "prm0", -1), -1.0))\n        link.event_clip("wait")\n        if item >= 0 and Game.messages.has(101 + item):\n            Game.show_message(101 + item)\n    elif name.contains("dash"):\n        link.event_clip("dash")\n    elif name.contains("jump"):\n        link.event_clip("mjmp")\n    else:\n        link.event_clip("wait")\n\nfunc _begin_actor(node: Node, cur: Dictionary, name: String, cut: Dictionary) -> void:\n    var msg = _prop(cut, "MsgNo")\n    if msg == null:\n        msg = _prop(cut, "msg_no")\n    if msg != null and (name.begins_with("MES_SET") or name.contains("TALK") or name.contains("MSG")):\n        if node and node.has_method("event_talk"):\n            node.event_talk(true)\n        Game.show_message(int(_num(msg, -1.0)))\n    elif name == "SETANM" and node and node.has_method("play_clip"):\n        var anm = _prop(cut, "AnmName")\n        if anm != null:\n            node.play_clip(str(anm))\n\nfunc _tick(st: Dictionary, cur: Dictionary) -> bool:\n    cur["t"] += 1\n    var cut: Dictionary = cur["cut"]\n    var kind: String = st["data"].get("type", "")\n    var name: String = cut.get("name", "")\n    var timer := int(_num(_prop(cut, "Timer", 0), 0.0))\n    match kind:\n        "TIMEKEEPER":\n            return cur["t"] >= timer\n        "CAMERA":\n            if name == "UNITRANS":\n                var k := clampf(float(cur["t"]) / maxf(float(timer), 1.0), 0.0, 1.0)\n                Game.set_event_cam(cur["from_eye"].lerp(_vec(_prop(cut, "Eye")), k),\n                                   cur["from_center"].lerp(_vec(_prop(cut, "Center")), k),\n                                   lerpf(cur["from_fov"], _num(_prop(cut, "Fovy", cur["from_fov"]), cur["from_fov"]), k))\n                return cur["t"] >= timer\n            if name == "PAUSE" and int(_num(_prop(cut, "WaitAnyKey", 0), 0.0)) == 1:\n                return Input.is_action_just_pressed("action_a") or Game.scripted()\n            return cur["t"] >= timer\n        "DIRECTOR":\n            return cur["t"] >= (timer if name == "FADE" else 0)\n        "NORMAL":\n            if kind == "PACKAGE":\n                return not Game.cutscene_running()\n            if _waits_dialog(name, cut):\n                if Game.dialog_open:\n                    cur["dialog_seen"] = true\n                    return false\n                if cur["dialog_seen"] or cur["t"] > 2:\n                    var node: Node = st["node"]\n                    if node and node != link and node.has_method("event_talk"):\n                        node.event_talk(false)\n                    return true\n                return false\n            if st["node"] == link and link and (name.begins_with("002") or name.contains("walk")):\n                return link.event_reached() or cur["t"] > 600\n            return cur["t"] >= timer\n        _:\n            return cur["t"] >= timer\n\nfunc _waits_dialog(name: String, cut: Dictionary) -> bool:\n    if name.contains("get_item"):\n        return true\n    var props: Dictionary = cut.get("properties", {})\n    return (props.has("MsgNo") or props.has("msg_no")) and (name.begins_with("MES_SET") or name.contains("TALK") or name.contains("MSG"))\n\nfunc abort() -> void:\n    # stage change under a running event: drop the camera / fade / Link control cleanly\n    if Game.event_running:\n        _finish()\n\nfunc _exit_tree() -> void:\n    if Game.event_running and Game.event_runner == self and not Game.cutscene_running():\n        Game.event_running = false\n        Game.clear_event_cam()\n        Game.fade(0.0, 1)\n\nfunc _finish() -> void:\n    # a .stb the event started can outlive the event script: it owns the flag until it ends\n    Game.event_running = Game.cutscene_running()\n    if not Game.cutscene_running():\n        # a .stb it launched is still running: that scene raises the bits when IT ends\n        Game.story_event_done(str(ev.get("name", "")))\n    Game.clear_event_cam()\n    Game.fade(0.0, 15)\n    if link and is_instance_valid(link) and link.has_method("event_end"):\n        link.event_end()\n    finished.emit()\n    queue_free()\n'

_ROPE_GD = 'extends Node3D\n# gcrip: Grappling Hook rope (d_a_himo2.cpp). Free flight 20 u/f for 40 frames, lobbed by a\n# pitch bias; locked flight to a grapple post at 30 u/f homing; a hooked rope hands Link the\n# pendulum (player.gd ROPE states). Returns at 50 u/f x a ramp after a miss.\n\nconst FLY_SPEED := 20.0\nconst FLY_FRAMES := 40\nconst LOCK_SPEED := 30.0\nconst LOCK_TURN := 0x800 * PI / 32768.0\nconst LOCK_ARRIVE := 50.0\nconst LOCK_FRAMES := 70\nconst PITCH_BIAS_PER_UNIT := -5.0        # s16 per unit of distance\nconst PITCH_BIAS_MIN := -3000.0\nconst S16 := PI / 32768.0\n\nenum State { FLY_FREE, FLY_LOCK, RETURN, HOOKED }\nvar state: int = State.FLY_FREE\nvar player: Node3D = null\nvar post: Node3D = null\nvar target := Vector3.ZERO\nvar yaw := 0.0\nvar pitch := 0.0          # positive = down\nvar t := 0\nvar ramp := 0.0\nvar line: MeshInstance3D = null\nvar tip: Node3D = null\n\nstatic func fwd(y: float, p: float) -> Vector3:\n    return Vector3(sin(y) * cos(p), -sin(p), cos(y) * cos(p))\n\nfunc launch(link: Node3D, from: Vector3, aim_yaw: float, aim_pitch: float, post_node: Node3D) -> void:\n    player = link\n    post = post_node\n    global_position = from\n    yaw = aim_yaw\n    pitch = aim_pitch\n    if post and is_instance_valid(post):\n        state = State.FLY_LOCK\n        target = post.hook_point()\n    else:\n        state = State.FLY_FREE\n        var d := from.distance_to(from + fwd(yaw, pitch) * 800.0)\n        pitch += maxf(PITCH_BIAS_PER_UNIT * d, PITCH_BIAS_MIN) * S16\n    line = MeshInstance3D.new()\n    var cyl := CylinderMesh.new()\n    cyl.top_radius = 1.8\n    cyl.bottom_radius = 1.8\n    cyl.height = 1.0\n    line.mesh = cyl\n    var mat := StandardMaterial3D.new()\n    mat.albedo_color = Color(0.55, 0.42, 0.25)\n    line.material_override = mat\n    line.top_level = true\n    add_child(line)\n    var scene := load("res://items/ropeend.glb") if ResourceLoader.exists("res://items/ropeend.glb") else null\n    if scene:\n        tip = scene.instantiate()\n        add_child(tip)\n\nfunc root() -> Vector3:\n    if player and is_instance_valid(player) and player.has_method("rope_hand"):\n        return player.rope_hand()\n    return global_position\n\nfunc _physics_process(_delta: float) -> void:\n    t += 1\n    match state:\n        State.FLY_FREE:\n            var old := global_position\n            var next := old + fwd(yaw, pitch) * FLY_SPEED\n            var space := get_world_3d().direct_space_state\n            var q := PhysicsRayQueryParameters3D.create(old, next, 1 | 8)\n            q.collide_with_areas = true\n            var hit := space.intersect_ray(q)\n            if hit:\n                var c = hit.collider\n                if c and c.has_method("take_hit"):\n                    c.take_hit(1, old)\n                global_position = hit.position\n                _start_return()\n            else:\n                global_position = next\n                if t >= FLY_FRAMES:\n                    _start_return()\n        State.FLY_LOCK:\n            var to := target - global_position\n            if to.length() < LOCK_ARRIVE or t > LOCK_FRAMES:\n                global_position = target\n                state = State.HOOKED\n                if player and is_instance_valid(player) and player.has_method("rope_hooked"):\n                    player.rope_hooked(self, target)\n            else:\n                var want_yaw := atan2(to.x, to.z)\n                var want_pitch := atan2(-to.y, Vector2(to.x, to.z).length())\n                yaw += clampf(wrapf(want_yaw - yaw, -PI, PI), -LOCK_TURN, LOCK_TURN)\n                pitch += clampf(want_pitch - pitch, -LOCK_TURN, LOCK_TURN)\n                global_position += fwd(yaw, pitch) * LOCK_SPEED\n        State.RETURN:\n            ramp += 0.01\n            var to := root() - global_position\n            var step := 400.0 * ramp\n            if to.length() <= maxf(step, 5.0):\n                if player and is_instance_valid(player) and player.has_method("rope_done"):\n                    player.rope_done()\n                queue_free()\n                return\n            global_position += to.normalized() * step\n        State.HOOKED:\n            pass\n    _draw(root())\n\nfunc _start_return() -> void:\n    state = State.RETURN\n    ramp = 0.0\n\nfunc release() -> void:\n    # Link let go: the rope comes back to the hand\n    _start_return()\n\nfunc _draw(r: Vector3) -> void:\n    if line == null:\n        return\n    var a := r\n    var b := global_position\n    var d := b - a\n    var l := d.length()\n    if l < 1.0:\n        line.visible = false\n        return\n    line.visible = true\n    line.global_position = (a + b) * 0.5\n    line.look_at(b, Vector3.UP if absf(d.normalized().y) < 0.99 else Vector3.FORWARD)\n    line.rotate_object_local(Vector3.RIGHT, PI / 2.0)\n    line.scale = Vector3(1.0, l, 1.0)\n'

_KUI_GD = 'extends Node3D\n# gcrip: grapple post (d_a_kui). Marks where the grappling hook can catch: the hook point is\n# the top of the post\'s mesh. Group "grapple_post"; hook_point() for the rope\'s target search.\n\nvar params := 0\nvar mesh: Node3D = null\nvar top := 170.0\n\nfunc setup(p: int, mesh_node: Node3D, _rot_y: float) -> void:\n    params = p\n    mesh = mesh_node\n    add_to_group("grapple_post")\n    if mesh is MeshInstance3D:\n        var aabb: AABB = (mesh as MeshInstance3D).get_aabb()\n        var hi := mesh.global_transform * (aabb.position + aabb.size)\n        var lo := mesh.global_transform * aabb.position\n        top = maxf(hi.y, lo.y) - global_position.y\n\nfunc hook_point() -> Vector3:\n    return global_position + Vector3(0, top, 0)\n'

_TAG_EVENT_GD = 'extends Area3D\n# gcrip: TagEv (d_a_tag_event.cpp) - an invisible cylinder (scale x 100) that orders the\n# stage event named by the EVNT table entry params >> 24 when Link walks in. A switch bit\n# (params >> 8) remembers it fired; an event bit in rot.z gates it (0 / 0xFFFF = none).\n\nvar params := 0\nvar event_flag := 0\nvar event_name := ""\nvar swbit := 0xFF\nvar room := 0\nvar done := false\n\nfunc setup(p: int, rot_z: int, r: int, table: Array, sc: Array) -> void:\n    params = p\n    room = r\n    event_flag = rot_z & 0xFFFF\n    swbit = (p >> 8) & 0xFF\n    var no := (p >> 24) & 0xFF\n    if no < table.size():\n        event_name = str(table[no])\n    var shape := CollisionShape3D.new()\n    var cyl := CylinderShape3D.new()\n    cyl.radius = maxf(float(sc[0]) * 100.0, 40.0)\n    cyl.height = maxf(float(sc[1]) * 100.0, 60.0) * 2.0\n    shape.shape = cyl\n    add_child(shape)\n    collision_layer = 0\n    collision_mask = 1\n    monitoring = true\n    body_entered.connect(_on_body_entered)\n\nfunc _on_body_entered(body: Node3D) -> void:\n    if done or not (body is CharacterBody3D) or not body.is_in_group("player"):\n        return\n    if event_name == "" or not Game.events.has(event_name):\n        return\n    if swbit != 0xFF and Game.is_switch(room, swbit):\n        done = true\n        return\n    if event_flag != 0 and event_flag != 0xFFFF and not Game.event_bit(event_flag):\n        return\n    if Game.run_event(event_name):\n        done = true\n        if swbit != 0xFF:\n            Game.set_switch(room, swbit)\n'

_NPC_TAG_GD = """extends Area3D
# gcrip: TagMd (d_a_tag_etc.cpp, d_stage.cpp:580 OBJNAME("TagMd", fpcNm_TAG_ETC_e)) - a
# trigger volume that watches an NPC instead of Link.  The Dragon Roost updraft volume: its
# hunt action calls onBitCamTagIn() on Medli whenever she is inside the box (delta.y >= 0,
# abs XZ < scale.x * 100, delta.y <= scale.y * 100), and SHE is the one who orders the event
# (daNpc_Md_c::chkAdanmaeDemoOrder, d_a_npc_md.cpp:3528 - mCurEventMode = 6) once the ground
# under her is inside the window the mined story step names.  Which is why Link has to carry
# her onto that ledge first.
#
# Link walking in must do nothing at all, so unlike tag_event.gd this volume never asks the
# physics server who overlaps it: monitoring stays off and it box-tests the ONE named actor,
# exactly like the decomp hunt action does.  Nothing here can fire on the player, and there
# is no spawn-overlap race to arm against either.
# The event name is the stage EVNT entry params >> 24, same decode as TagEv.

var params := 0
var type2 := 0            # (params >> 8) & 0xF: 0 = "only while she is gliding"
var event_flag := 0
var event_name := ""
var room := 0
var tag_actor := ""
var half := Vector3.ZERO  # scale * 100: XZ half width, and how far up the box reaches
var done := false
var tick := 0

func setup(p: int, rot_z: int, r: int, table: Array, sc: Array, actor_name: String) -> void:
    params = p
    room = r
    tag_actor = actor_name
    event_flag = rot_z & 0xFFFF
    type2 = (p >> 8) & 0xF
    var no := (p >> 24) & 0xFF
    if no < table.size():
        event_name = str(table[no])
    half = Vector3(maxf(float(sc[0]) * 100.0, 40.0), maxf(float(sc[1]) * 100.0, 60.0),
        maxf(float(sc[2]) * 100.0, 40.0))
    var shape := CollisionShape3D.new()
    var box := BoxShape3D.new()
    box.size = Vector3(half.x * 2.0, half.y, half.z * 2.0)
    shape.shape = box
    shape.position.y = half.y * 0.5        # the box grows upwards from the placement point
    add_child(shape)
    collision_layer = 0
    collision_mask = 0
    monitoring = false
    monitorable = false

func inside(at: Vector3) -> bool:
    var d := at - global_position
    return d.y >= 0.0 and d.y <= half.y and absf(d.x) < half.x and absf(d.z) < half.z

func _physics_process(_delta: float) -> void:
    if done:
        return
    tick += 1
    if tick % 6 != 0:            # an NPC drifting into a box does not need a 30 Hz test
        return
    if Game.event_running or Game.cutscene_running() or Game.dialog_open:
        return
    var step: Dictionary = Game.story_npc_tag_step(tag_actor)
    if step.is_empty():
        return
    var nt = step.get("npc_tag")
    if not (nt is Dictionary):
        return
    var watch := str(nt.get("actor", ""))
    var who := Game._find_actor(watch)
    if who == null or who.is_in_group("player"):
        return                   # never the player: this is not a TagEv
    if not inside(who.global_position):
        return
    # she only orders it from the ledge: the height of the GROUND under her, not her own y
    var g := Game.ground_height(who.global_position)
    var lo := -1.0e9
    var hi := 1.0e9
    if nt.get("ground_min") != null:
        lo = float(nt["ground_min"])
    if nt.get("ground_max") != null:
        hi = float(nt["ground_max"])
    if g < lo or g > hi:
        return
    var id := Game.sfield(step, "id")
    var ev := Game.sfield(step, "event")
    if ev == "":
        ev = event_name          # no event on the step: this volume names its own
    done = true
    Game._mark_story_done(id)
    print("gcrip story: ", tag_actor, " has ", watch, " inside (ground ", int(g), ") -> ",
        id, " (event ", ev, ")")
    if ev != "" and Game.events.has(ev) and Game.run_event(ev):
        return
    Game.story_event_done(id)
"""

_HIT_OBJECT_GD = """extends StaticBody3D
# gcrip: an object the player breaks by HITTING it, which then orders its own event - one
# event name per damage stage (d_a_obj_ajav.cpp, the rock wall over Jabun's cave).
# daObjAjav::damage_part() fires while M_status is below the last stage and to_broken()
# orders l_daObjAjav_ev_name[M_status] by event id, so three bombs play ajav_destroy0,
# ajav_destroy1 and ajav_uzu in that order; the last one carries the DIRECTOR NEXT into
# Pjavdou and the actor calls on_sw(mSwNo) so the wall stays open.
#
# Layer 8 is this project's "hittable" layer: the sword sweep (SwordHit, mask 8), the arrow /
# boomerang / hookshot queries and the bomb blast query (mask 8 | 16) all find it there, and
# take_hit(damage, from) is the convention every one of them calls.  min_damage is what makes
# the Ajav wall bomb-only: Atp 4 gets through, a sword swing (1) and an arrow (2) do not.

var actor := ""
var params := 0
var step_id := ""
var events: Array = []       # one event name per damage stage, in order
var stage_i := 0
var min_damage := 0
var swbit := -1
var room := 0
var mesh: Node3D = null
var cool := 0
var broken := false
var gone := 0

func setup_hit(actor_name: String, p: int, mesh_node: Node3D, rot_y_deg: float,
        step: Dictionary) -> void:
    actor = actor_name
    params = p
    mesh = mesh_node
    step_id = Game.sfield(step, "id")
    var hit = step.get("hit", {})
    if not (hit is Dictionary):
        hit = {}
    var evs = hit.get("events", [])
    if evs is Array:
        events = (evs as Array).duplicate()
    min_damage = int(hit.get("min_damage", 0))
    if hit.get("switch") != null:
        swbit = int(hit["switch"])
    if hit.get("room") != null:
        room = int(hit["room"])
    var size := Vector3(400.0, 600.0, 400.0)
    var sz = hit.get("size")
    if sz is Array and (sz as Array).size() >= 3:
        size = Vector3(float(sz[0]), float(sz[1]), float(sz[2]))
    collision_layer = 8
    collision_mask = 0
    var shape := CollisionShape3D.new()
    var box := BoxShape3D.new()
    box.size = size
    shape.shape = box
    shape.position.y = size.y * 0.5
    add_child(shape)
    rotation.y = deg_to_rad(rot_y_deg)
    if mesh == null:
        # nothing baked for this actor yet (the Ajav pieces are in ww_actors.py but the
        # placement never reached the rip): a rock-coloured block, so it can at least be
        # seen and aimed at instead of being an invisible collider
        var mi := MeshInstance3D.new()
        var bm := BoxMesh.new()
        bm.size = size
        mi.mesh = bm
        var mat := StandardMaterial3D.new()
        mat.albedo_color = Color(0.42, 0.40, 0.36)
        mi.material_override = mat
        mi.position.y = size.y * 0.5
        add_child(mi)
        mesh = mi
    add_to_group("interact")
    if events.is_empty():
        print("gcrip hit: ", actor, " has no event table - it can never break")

func interact_prompt(_link: Node3D) -> String:
    return ""                # every "interact" member is asked: this one is hit, not touched

func take_hit(damage: int, _from: Vector3) -> void:
    if broken or cool > 0 or stage_i >= events.size():
        return
    if damage < min_damage:
        return               # the rock wall answers a bomb, not a sword swing
    var ev := str(events[stage_i])
    if ev != "" and Game.events.has(ev):
        if not Game.run_event(ev):
            return           # something else is already playing: this hit does not count
    else:
        print("gcrip hit: ", actor, " wanted event ", ev, " - not in this stage")
    stage_i += 1
    cool = 20
    Game.hit_log.append(ev)
    print("gcrip hit: ", actor, " ", stage_i, "/", events.size(), " -> ", ev)
    if stage_i < events.size():
        return
    broken = true            # last stage: the wall is open for good
    collision_layer = 0
    if mesh:
        mesh.visible = false
    if swbit >= 0:
        Game.set_switch(room, swbit)
    Game.story_event_done(step_id)
    Game.burst(global_position + Vector3(0, 100, 0), Color(0.55, 0.5, 0.45))

func _physics_process(_delta: float) -> void:
    if cool > 0:
        cool -= 1
    if broken:
        gone += 1
        if gone > 150:       # the last event may still name this actor in its staff list
            queue_free()
"""

_ACTOR_ENEMY_GD = 'extends CharacterBody3D\n# gcrip: data-driven enemy (melee / flying / ranged) for the actors that are not worth their\n# own script yet. Constants come from enemies.json (data/ww_enemies_*.json mined from the\n# decomp); anything missing falls back to the Bokoblin-like defaults below. Per-frame units.\n\nconst DEFAULTS := {\n    "hp": 3, "radius": 40.0, "height": 100.0, "notice": 1000.0, "lose": 1800.0,\n    "walk": 3.0, "run": 10.0, "gravity": -3.0, "terminal": -50.0, "turn_s16": 0x600,\n    "attack_range": 110.0, "attack_frames": 30, "hit_frame": 14, "damage": 2,\n    "knockback": 8.0, "flinch_frames": 12, "flying": false, "hover": 250.0, "fly_speed": 8.0,\n    "ranged": null, "clips": {},\n}\n\nconst RANGED_DEFAULTS := {"speed": 40.0, "range": 1200.0, "cooldown": 90, "damage": 1}\n\nenum Act { STAND, APPROACH, ATTACK, DAMAGE, DEAD, RETURN }\nvar room := 0        # which room placed it, so a room-clear can be counted\nvar dead := false    # true the instant hp runs out, before the death animation ends\nvar act: int = Act.STAND\nvar actor := ""\nvar cfg: Dictionary = {}\nvar hp := 3\nvar facing := 0.0\nvar speed := 0.0\nvar timer := 0\nvar cooldown := 0\nvar hit_done := false\nvar mesh: Node3D = null\nvar anim: AnimationPlayer = null\nvar home := Vector3.ZERO\nvar bob := 0.0\nvar dive_from := Vector3.ZERO\nvar dive_to := Vector3.ZERO\nvar clips: Dictionary = {}\n\nfunc setup(actor_name: String, _p: int, mesh_node: Node3D, rot_y_deg: float) -> void:\n    actor = actor_name\n    cfg = DEFAULTS.duplicate(true)\n    var table: Dictionary = Game.enemies.get(actor, {})\n    for k in table:\n        if table[k] != null:\n            cfg[k] = table[k]\n    # a few enemies are mined "low confidence" because their decomp bodies are stubs: their\n    # ranged block exists but its numbers are null, and float(null) throws every frame\n    if cfg.get("ranged") is Dictionary:\n        var r: Dictionary = (cfg["ranged"] as Dictionary).duplicate()\n        for k2 in RANGED_DEFAULTS:\n            if r.get(k2) == null:\n                r[k2] = RANGED_DEFAULTS[k2]\n        cfg["ranged"] = r\n    mesh = mesh_node\n    home = global_position\n    facing = deg_to_rad(rot_y_deg)\n    hp = int(cfg["hp"])\n    collision_layer = 1 | 8\n    collision_mask = 1\n    var shape := CollisionShape3D.new()\n    var cyl := CylinderShape3D.new()\n    cyl.radius = float(cfg["radius"])\n    cyl.height = float(cfg["height"])\n    shape.shape = cyl\n    shape.position.y = float(cfg["height"]) / 2.0\n    add_child(shape)\n    add_to_group("enemy")\n    if bool(cfg["flying"]):\n        motion_mode = CharacterBody3D.MOTION_MODE_FLOATING\n    anim = mesh.find_child("AnimationPlayer", true, false) if mesh else null\n    if anim:\n        var wanted: Dictionary = cfg.get("clips", {})\n        var names := anim.get_animation_list()\n        for key in ["wait", "walk", "run", "notice", "attack", "damage", "dead", "fly"]:\n            var want := str(wanted.get(key, ""))\n            if want != "" and anim.has_animation(want):\n                clips[key] = want\n        for n in names:\n            var l := n.to_lower()\n            for key in ["wait", "walk", "run", "attack", "damage", "dead", "fly", "hakken"]:\n                var k2: String = "notice" if key == "hakken" else key\n                if key in l and not clips.has(k2):\n                    clips[k2] = n\n        for key in ["wait", "walk", "run", "fly"]:\n            if clips.has(key):\n                anim.get_animation(clips[key]).loop_mode = Animation.LOOP_LINEAR\n        _play("fly" if bool(cfg["flying"]) and clips.has("fly") else "wait")\n\nfunc _play(key: String, blend := 0.2) -> void:\n    if anim and clips.has(key) and anim.current_animation != clips[key]:\n        anim.play(clips[key], blend)\n\nfunc take_hit(damage: int, from: Vector3) -> void:\n    if act == Act.DEAD:\n        return\n    hp -= damage\n    var away := global_position - from\n    away.y = 0.0\n    if away.length() > 0.01:\n        facing = atan2(-away.x, -away.z)\n    if hp <= 0:\n        act = Act.DEAD\n        dead = true\n        timer = 40\n        _play("dead", 0.1)\n        # the real death set: SIBOUBAKUEN 0x0013 (the big smoke) + SIBOUFLASH 0x0016; the\n        # burst stays as the fallback when no bank is exported\n        var dp := global_position + Vector3(0, float(cfg["height"]) * 0.5, 0)\n        if not Game.fx(0x0013, dp):\n            Game.burst(dp, Color(0.502, 0.125, 0.392))\n        Game.fx(0x0016, dp)\n        # a dungeon boss writes a per-stage save field rather than an event bit, so the\n        # story is told which of the two this death was\n        Game.story_enemy_defeated(actor, bool(cfg.get("boss", false)))\n        Game.story_room_cleared(room)\n        return\n    act = Act.DAMAGE\n    timer = int(cfg["flinch_frames"])\n    speed = -float(cfg["knockback"])\n    _play("damage", 0.05)\n\nfunc _turn_to(t: float) -> void:\n    var max_step := int(cfg["turn_s16"]) * PI / 32768.0\n    facing += clampf(wrapf(t - facing, -PI, PI), -max_step, max_step)\n\nfunc _physics_process(_delta: float) -> void:\n    var link := Game.player()\n    var to_link := Vector3.ZERO\n    var dist := 1.0e9\n    if link:\n        to_link = link.global_position - global_position\n        to_link.y = 0.0\n        dist = to_link.length()\n    var flying := bool(cfg["flying"])\n    var ranged = cfg.get("ranged")\n    var has_ranged: bool = ranged is Dictionary\n    if cooldown > 0:\n        cooldown -= 1\n    match act:\n        Act.STAND:\n            speed = 0.0\n            _play("fly" if flying and clips.has("fly") else "wait")\n            if link and dist < float(cfg["notice"]) and Game.line_of_sight(global_position + Vector3(0, 80, 0), link.global_position + Vector3(0, 80, 0)):\n                act = Act.APPROACH\n                _play("notice" if clips.has("notice") else ("fly" if flying else "run"), 0.1)\n        Act.APPROACH:\n            _turn_to(atan2(to_link.x, to_link.z))\n            if has_ranged and dist < float(ranged.get("range", 1200.0)) and dist > float(cfg["attack_range"]):\n                speed = 0.0\n                _play("wait")\n                if cooldown <= 0 and link:\n                    _shoot(ranged, link)\n            else:\n                speed = float(cfg["fly_speed"] if flying else cfg["run"])\n                _play("fly" if flying and clips.has("fly") else "run")\n            if dist < float(cfg["attack_range"]) and link:\n                act = Act.ATTACK\n                timer = int(cfg["attack_frames"])\n                hit_done = false\n                speed = 0.0\n                dive_from = global_position\n                dive_to = link.global_position + Vector3(0, 60.0, 0)\n                _play("attack", 0.1)\n            elif dist > float(cfg["lose"]):\n                act = Act.RETURN\n        Act.ATTACK:\n            timer -= 1\n            var n := int(cfg["attack_frames"])\n            if flying:\n                # swoop: dive at Link\'s body and climb back out over the attack\'s frames\n                var k := 1.0 - float(timer) / maxf(float(n), 1.0)\n                var arc := sin(k * PI)\n                global_position = dive_from.lerp(dive_to, minf(k * 2.0, 1.0)) + Vector3(0, (1.0 - arc) * 0.0, 0)\n                if k > 0.5:\n                    global_position = dive_to.lerp(dive_from + Vector3(0, float(cfg["hover"]), 0), (k - 0.5) * 2.0)\n            if timer == n - int(cfg["hit_frame"]) and not hit_done and link and link.global_position.distance_to(global_position) < float(cfg["attack_range"]) + 40.0:\n                hit_done = true\n                link.call("take_damage", int(cfg["damage"]), global_position)\n            if timer <= 0:\n                act = Act.APPROACH\n        Act.DAMAGE:\n            timer -= 1\n            speed = minf(speed + 1.0, 0.0)\n            if timer <= 0:\n                act = Act.APPROACH\n        Act.RETURN:\n            var to_home := home - global_position\n            to_home.y = 0.0\n            _turn_to(atan2(to_home.x, to_home.z))\n            speed = float(cfg["walk"] if not flying else cfg["fly_speed"])\n            _play("walk" if clips.has("walk") else "run")\n            if to_home.length() < 40.0:\n                act = Act.STAND\n            elif link and dist < float(cfg["notice"]) * 0.8:\n                act = Act.APPROACH\n        Act.DEAD:\n            timer -= 1\n            if mesh:\n                mesh.scale = mesh.scale * 0.92\n            if timer <= 0:\n                queue_free()\n            return\n    if flying:\n        if act != Act.ATTACK:\n            bob += 0.12\n            var target_y := Game.ground_height(global_position) + float(cfg["hover"]) + sin(bob) * 15.0\n            var dy := clampf(target_y - global_position.y, -6.0, 6.0)\n            velocity = (Vector3(sin(facing) * speed, dy, cos(facing) * speed)) * 30.0\n            move_and_slide()\n    else:\n        var vy := velocity.y / 30.0 + float(cfg["gravity"])\n        vy = maxf(vy, float(cfg["terminal"]))\n        velocity = Vector3(sin(facing) * speed, vy, cos(facing) * speed) * 30.0\n        move_and_slide()\n        if is_on_floor():\n            velocity.y = 0.0\n    if mesh:\n        mesh.rotation.y = facing\n\nfunc _shoot(r: Dictionary, link: Node3D) -> void:\n    cooldown = int(r.get("cooldown", 90))\n    var shot := Area3D.new()\n    shot.set_script(load("res://items/enemy_shot.gd"))\n    get_tree().current_scene.add_child(shot)\n    var from := global_position + Vector3(0, float(cfg["height"]) * 0.6, 0)\n    var aim := (link.global_position + Vector3(0, 80.0, 0)) - from\n    shot.launch(from, aim.normalized(), float(r.get("speed", 30.0)), float(r.get("range", 1500.0)), int(r.get("damage", 2)))\n    _play("attack", 0.1)\n'

_ENEMY_SHOT_GD = 'extends Area3D\n# gcrip: a simple enemy projectile (Octorok rock, Wizzrobe fire ball): straight flight, hurts\n# Link within 40 units, stops on the world.\n\nvar vel := Vector3.ZERO\nvar left := 0.0\nvar damage := 2\nvar mesh: MeshInstance3D = null\n\nfunc launch(from: Vector3, dir: Vector3, speed: float, range_units: float, dmg: int) -> void:\n    global_position = from\n    vel = dir * speed\n    left = range_units\n    damage = dmg\n    mesh = MeshInstance3D.new()\n    var sph := SphereMesh.new()\n    sph.radius = 14.0\n    sph.height = 28.0\n    mesh.mesh = sph\n    var mat := StandardMaterial3D.new()\n    mat.albedo_color = Color(0.9, 0.4, 0.1)\n    mat.emission_enabled = true\n    mat.emission = Color(1.0, 0.5, 0.1)\n    mesh.material_override = mat\n    add_child(mesh)\n\nfunc _physics_process(_delta: float) -> void:\n    var old := global_position\n    var next := old + vel\n    var space := get_world_3d().direct_space_state\n    var q := PhysicsRayQueryParameters3D.create(old, next, 1)\n    if space.intersect_ray(q):\n        queue_free()\n        return\n    global_position = next\n    left -= vel.length()\n    var link := Game.player()\n    if link and link.global_position.distance_to(global_position - Vector3(0, 60.0, 0)) < 45.0:\n        link.call("take_damage", damage, global_position)\n        queue_free()\n        return\n    if left <= 0.0:\n        queue_free()\n'

_CUTSCENE_GD = 'extends Node\n# gcrip: plays a baked JStudio cutscene (.stb -> cutscenes/<name>.json, one value per frame\n# run-length encoded). Camera, actor transforms and the message box; sounds and particles\n# are not driven yet, and animation ids are only applied when we can name the clip.\n#\n# Scene coordinates are local to the demo: world = Ry(offset_angy) * local + offset_pos,\n# then minus the stage\'s recentring offset to land in engine space.\n\nsignal finished\n\nvar data: Dictionary = {}\nvar frame := 0\nvar frames := 0\nvar offset_pos := Vector3.ZERO\nvar offset_angy := 0.0\nvar basis_y := Basis.IDENTITY\nvar actors: Dictionary = {}      # cutscene actor id -> node in the scene\nvar link: Node3D = null\nvar last_msg := -1\nvar cursors: Dictionary = {}\nvar players: Dictionary = {}     # actor id -> its AnimationPlayer\nvar playing: Dictionary = {}     # actor id -> clip name currently playing\n\nfunc play(name: String, off_pos: Vector3, off_angy: float) -> bool:\n    var path := "res://cutscenes/%s.json" % name\n    var f := FileAccess.open(path, FileAccess.READ)\n    if f == null:\n        print("gcrip cutscene: no baked scene ", name)\n        return false\n    var parsed = JSON.parse_string(f.get_as_text())\n    if not (parsed is Dictionary):\n        return false\n    data = parsed\n    frames = int(data.get("frames", 0))\n    offset_pos = off_pos\n    offset_angy = off_angy\n    basis_y = Basis(Vector3.UP, deg_to_rad(off_angy))\n    link = Game.player()\n    for a in data.get("actors", []):\n        var id := str(a.get("id", ""))\n        var node := _find_actor(id)\n        actors[id] = node\n        if node:\n            players[id] = _find_anim(node)\n    Game.event_running = true\n    if link and link.has_method("event_begin"):\n        link.event_begin()\n    print("gcrip cutscene: ", name, " ", frames, " frames, actors ", actors.keys())\n    return true\n\nfunc _find_actor(id: String) -> Node3D:\n    if id == "Link":\n        return link\n    var cs := get_tree().current_scene\n    if cs == null:\n        return null\n    for grp in ["interact", "enemy"]:\n        for n in get_tree().get_nodes_in_group(grp):\n            if is_instance_valid(n) and str(n.get("actor")) == id:\n                return n\n    return null\n\nfunc _find_anim(node: Node3D) -> AnimationPlayer:\n    for n in node.find_children("*", "AnimationPlayer", true, false):\n        return n\n    return null\n\nfunc _world(local: Vector3) -> Vector3:\n    return (basis_y * local) + offset_pos - Game.world_offset\n\n# --- run-length tracks: null, a bare value, or [[frame, value], ...] ---\nfunc _sample(track, f: int):\n    if track == null:\n        return null\n    if not (track is Array):\n        return track\n    var arr: Array = track\n    if arr.is_empty() or not (arr[0] is Array):\n        return track   # a bare vector value, e.g. [x, y, z]\n    var lo := 0\n    var hi := arr.size() - 1\n    if int(arr[0][0]) > f:\n        return null\n    while lo < hi:\n        var mid := (lo + hi + 1) / 2\n        if int(arr[mid][0]) <= f:\n            lo = mid\n        else:\n            hi = mid - 1\n    return arr[lo][1]\n\nfunc _physics_process(_delta: float) -> void:\n    if data.is_empty():\n        return\n    if frame >= frames:\n        _finish()\n        return\n    var cam = data.get("camera")\n    if cam != null:\n        var eye = _sample(cam.get("eye"), frame)\n        var tgt = _sample(cam.get("target"), frame)\n        var fov = _sample(cam.get("fov"), frame)\n        if eye is Array and tgt is Array and eye.size() >= 3 and tgt.size() >= 3:\n            Game.set_event_cam(\n                _world(Vector3(float(eye[0]), float(eye[1]), float(eye[2]))),\n                _world(Vector3(float(tgt[0]), float(tgt[1]), float(tgt[2]))),\n                float(fov) if fov != null else 60.0,\n            )\n    for a in data.get("actors", []):\n        var node: Node3D = actors.get(str(a.get("id", "")))\n        if node == null or not is_instance_valid(node):\n            continue\n        var pos = _sample(a.get("pos"), frame)\n        if pos is Array and pos.size() >= 3:\n            node.global_position = _world(Vector3(float(pos[0]), float(pos[1]), float(pos[2])))\n        var id2 := str(a.get("id", ""))\n        var clip = _sample(a.get("clip"), frame)\n        if clip != null:\n            var ap: AnimationPlayer = players.get(id2)\n            var nm := str(clip)\n            if ap and ap.has_animation(nm) and str(playing.get(id2, "")) != nm:\n                ap.play(nm, 0.15)\n                playing[id2] = nm\n                if node == link:\n                    link.set("current_clip", nm)   # keep the controller from fighting it\n        var ry = _sample(a.get("rot_y"), frame)\n        if ry != null:\n            var yaw := deg_to_rad(float(ry)) + deg_to_rad(offset_angy)\n            if node == link:\n                link.set("facing", yaw)\n            else:\n                node.set("facing", yaw)\n    for m in data.get("messages", []):\n        var id = _sample(m.get("msg"), frame)\n        if id != null and int(id) > 0 and int(id) != last_msg:\n            last_msg = int(id)\n            Game.show_message(int(id))\n    if Game.dialog_open:\n        return          # hold the timeline while a text box is up\n    if Input.is_action_just_pressed("action_b") or Input.is_action_just_pressed("pause"):\n        frame = frames  # B skips\n        return\n    frame += 1\n\nfunc abort() -> void:\n    _finish()\n\nfunc _finish() -> void:\n    if data.is_empty():\n        return\n    var played := str(data.get("name", ""))\n    data = {}\n    Game.story_event_done(played)\n    Game.event_running = false\n    Game.clear_event_cam()\n    if link and is_instance_valid(link) and link.has_method("event_end"):\n        link.event_end()\n    finished.emit()\n    queue_free()\n\nfunc _exit_tree() -> void:\n    if not data.is_empty():\n        Game.event_running = false\n        Game.clear_event_cam()\n'

_WARP_GD = """extends Area3D
# gcrip: walking into this (a door) loads the destination stage.

@export var dest_stage := ""
@export var dest_room := 0
@export var dest_spawn := 0
var armed := false   # arriving through this door puts Link inside the box: wait until he leaves
var locked := false  # a placed door actor in front of this exit has not been unlocked yet

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
    if locked:
        return
    if armed and body is CharacterBody3D:
        Game.warp(dest_stage, dest_room, dest_spawn)
"""


def _shader_variants(src: str) -> list[tuple[str, str]]:
    """(filename suffix, source) for the four cull x blend combinations of a cel shader.

    `render_mode` and whether ALPHA is written are both compile-time in Godot, so a single
    shader cannot serve a double-sided material and a single-sided one, nor an opaque
    material and a blended one. The blended variants also take `depth_prepass_alpha`: they
    still sort as transparent, but they lay down depth first, so they occlude the sea
    instead of being painted over by it.
    """
    assert "// gcrip:alpha" in src, "cel shader lost its alpha marker"
    out = []
    for cull_suffix, cull_src in (
        ("", src),
        ("_ds", src.replace("cull_back", "cull_disabled")),
    ):
        out.append((cull_suffix, cull_src.replace("// gcrip:alpha", "// opaque variant")))
        blended = cull_src.replace("// gcrip:alpha", "ALPHA = base.a;")
        first_nl = blended.index(chr(10), blended.index("render_mode"))
        head, tail = blended[:first_nl], blended[first_nl:]
        blended = head.rstrip(";") + ", depth_prepass_alpha;" + tail
        out.append((cull_suffix + "_a", blended))
    return out


def _render_block(physical: bool) -> str:
    phys = "true" if physical else "false"
    return (
        "[rendering]\n"
        f"lights_and_shadows/use_physical_light_units={phys}\n"
        "lights_and_shadows/directional_shadow/size=4096\n"
        "lights_and_shadows/directional_shadow/soft_shadow_filter_quality=2\n"
        "anti_aliasing/quality/msaa_3d=2\n"
        "anti_aliasing/quality/screen_space_aa=1"
    )


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


def _lighting_block(physical: bool) -> str:
    if physical:
        return """[sub_resource type="PhysicalSkyMaterial" id="sky"]
rayleigh_coefficient = 2.0
mie_coefficient = 0.005
turbidity = 10.0
ground_color = Color(0.3, 0.26, 0.22, 1)

[sub_resource type="Sky" id="skyres"]
sky_material = SubResource("sky")
radiance_size = 4

[sub_resource type="CameraAttributesPhysical" id="camattr"]
exposure_aperture = 16.0
exposure_shutter_speed = 100.0
exposure_sensitivity = 100.0
auto_exposure_enabled = true
auto_exposure_min_exposure_value = 1.0
auto_exposure_max_exposure_value = 15.0

[sub_resource type="Environment" id="env"]
background_mode = 2
sky = SubResource("skyres")
ambient_light_source = 3
reflected_light_source = 2
tonemap_mode = 3
tonemap_white = 6.0
ssao_enabled = true
ssao_radius = 120.0
ssil_enabled = true
glow_enabled = true
glow_intensity = 0.35
glow_hdr_threshold = 1.2"""
    # simple: a plain sky, sky ambient, Filmic, mild glow - always visible, no exposure games
    return """[sub_resource type="ProceduralSkyMaterial" id="sky"]
sky_top_color = Color(0.28, 0.5, 0.78, 1)
sky_horizon_color = Color(0.7, 0.82, 0.92, 1)
ground_bottom_color = Color(0.42, 0.45, 0.4, 1)
ground_horizon_color = Color(0.7, 0.82, 0.92, 1)
sun_angle_max = 30.0

[sub_resource type="Sky" id="skyres"]
sky_material = SubResource("sky")

[sub_resource type="Environment" id="env"]
background_mode = 2
sky = SubResource("skyres")
ambient_light_source = 3
ambient_light_energy = 1.0
tonemap_mode = 2
glow_enabled = true
glow_intensity = 0.25
glow_bloom = 0.05"""


def _sun_env_nodes(physical: bool) -> str:
    sun = (
        '''[node name="Sun" type="DirectionalLight3D" parent="."]
transform = Transform3D(%s, 0, 10000, 0)
light_intensity_lux = 100000.0
light_temperature = 5500.0
light_angular_distance = 0.53
shadow_enabled = true
directional_shadow_max_distance = 60000.0
shadow_blur = 1.5'''
        if physical
        else '''[node name="Sun" type="DirectionalLight3D" parent="."]
transform = Transform3D(%s, 0, 10000, 0)
light_energy = 1.15
shadow_enabled = true
directional_shadow_max_distance = 60000.0'''
    ) % _sun_basis()
    env = (
        '[node name="Env" type="WorldEnvironment" parent="."]\n'
        'environment = SubResource("env")'
    )
    if physical:
        env += '\ncamera_attributes = SubResource("camattr")'
    return sun + "\n\n" + env


def _stage_tscn(
    name: str,
    spawn: tuple[float, float, float],
    *,
    has_col: bool = False,
    exits: list[dict] | None = None,
    water_level: float = -1.0e9,
    spawns: list[dict] | None = None,
    physical: bool = False,
) -> str:
    x, y, z = spawn
    exits = exits or []
    spawns = spawns or []
    col_res = (
        f'[ext_resource type="PackedScene" path="res://stages/{name}_col.glb" id="3"]\n'
        if has_col
        else ""
    )
    col_node = '\n[node name="Collision" parent="." instance=ExtResource("3")]\n' if has_col else ""
    warp_res = '[ext_resource type="Script" path="res://warp.gd" id="4"]\n' if exits else ""
    stage_res = '[ext_resource type="Script" path="res://stage.gd" id="5"]\n'
    warp_shape = (
        '\n[sub_resource type="BoxShape3D" id="warpbox"]\nsize = Vector3(220, 320, 220)\n'
        '\n[sub_resource type="BoxShape3D" id="doorslab"]\nsize = Vector3(260, 340, 30)\n'
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
        # the game's door actors are solid: a slab just beyond the trigger keeps Link from
        # walking through the doorway hole in the room mesh (hollow houses have no floor)
        rot = math.radians(float(e.get("rot_y_deg", 0.0)))
        out_x, out_z = math.sin(rot), math.cos(rot)
        near = [sp for sp in spawns if math.dist((sp["pos"][0], sp["pos"][2]), (ex, ez)) < 400.0]
        if near:
            f = math.radians(float(near[0].get("rot_y_deg", 0.0)))
            out_x, out_z = -math.sin(f), -math.cos(f)  # Link arrives facing into the room
        a = math.atan2(out_x, out_z)
        ca, sa = math.cos(a), math.sin(a)
        warp_nodes.append(
            f'\n[node name="Door{i}" type="StaticBody3D" parent="."]\n'
            f"transform = Transform3D({ca:.4f}, 0, {-sa:.4f}, 0, 1, 0, {sa:.4f}, 0, {ca:.4f}, "
            f"{ex + out_x * 70.0:.1f}, {ey + 170:.1f}, {ez + out_z * 70.0:.1f})\n"
            f'\n[node name="Slab" type="CollisionShape3D" parent="Door{i}"]\n'
            f'shape = SubResource("doorslab")\n'
        )
    return f"""[gd_scene load_steps={7 + int(has_col) + (2 if exits else 0)} format=3]

[ext_resource type="PackedScene" path="res://stages/{name}.glb" id="1"]
[ext_resource type="PackedScene" path="res://player.tscn" id="2"]
{col_res}{warp_res}{stage_res}

{warp_shape}
{_lighting_block(physical)}

[node name="{name}" type="Node3D"]
script = ExtResource("5")

[node name="Level" parent="." instance=ExtResource("1")]
{col_node}
{_sun_env_nodes(physical)}

[node name="Player" parent="." instance=ExtResource("2")]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {x:.1f}, {y + 30:.1f}, {z:.1f})
water_level = {water_level:.1f}
{"".join(warp_nodes)}"""


# --- placed warp objects (mined trigger kind "warp") ---------------------------------
# A mined warp step describes ONE object in prose: which actor it is, where it stands, which
# event it orders and where that event's DIRECTOR NEXT puts Link. Two steps can describe the
# same object taking different branches - daWarpf_c::CreateInit orders WARP_WIND or
# WARP_WIND_AFTER from the same flower depending on checkEndDemo() - so the engine groups
# them per (stage, actor) and picks the branch the save satisfies.
_WARP_OBJ_ACTOR_RE = re.compile(r"\b(Warpf|Ywarp00|Warpls|Warpmj|Warpgn)\b")
# "the same Warpf in SirenB takes the other branch": the object's home stage, for steps whose
# own `stage` is the ARRIVAL stage instead. "Ywarp00 in room 17" must not match.
_WARP_OBJ_HOME_RE = re.compile(
    r"\b(?:Warpf|Ywarp00|Warpls|Warpmj|Warpgn)\s+in\s+(?!room\b)([A-Za-z][A-Za-z0-9_]*)"
)
_WARP_OBJ_POS_RE = re.compile(
    r"\bat\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)"
)
# an event script's tail: DIRECTOR NEXT -> Stage 'ADMumi', RoomNo 0, Layer 9, StartCode 200
_WARP_OBJ_DEST_RE = re.compile(
    r"Stage\s*['\"]([A-Za-z0-9_]+)['\"]\s*,\s*RoomNo\s*(-?\d+)\s*,"
    r"\s*Layer\s*(-?\d+)\s*,\s*StartCode\s*(-?\d+)"
)
# "Room 17 spawn 0 carries EVNT index 3": a destination inside the step's own stage
_WARP_OBJ_ROOM_SPAWN_RE = re.compile(r"[Rr]oom\s+(\d+)\s+spawn\s+(\d+)")
# which event this branch orders, when it is not simply the step's `event` (the mined step
# totg_return_from_tower names TOWER_WARPOUT, the ARRIVAL event, not WARP_WIND_AFTER)
_WARP_OBJ_EVENT_RES = (
    re.compile(r"\bpicks\s+([A-Z][A-Z0-9_]{2,})"),
    re.compile(r"\borders\s+([A-Z][A-Z0-9_]{2,})"),
    re.compile(r"\btakes\s+the\s+([A-Z][A-Z0-9_]{2,})\s+branch"),
    re.compile(r"\bplays\s+([A-Z][A-Z0-9_]{2,})"),
)


def _warp_object_of(step: dict) -> dict | None:
    """One mined "warp" step -> the placed object plus the single branch it describes, or None
    when the prose names no actor or no destination."""
    trig = step.get("trigger") or {}
    if trig.get("kind") != "warp":
        return None
    detail = str(trig.get("detail", ""))
    m_actor = _WARP_OBJ_ACTOR_RE.search(detail)
    if not m_actor:
        return None
    actor = m_actor.group(1)
    m_home = _WARP_OBJ_HOME_RE.search(detail)
    stage = str(step.get("stage", ""))
    home = m_home.group(1) if m_home else stage
    # the step's own room and the coordinates in its prose describe the OBJECT only when the
    # object lives in the step's stage; otherwise they describe where Link lands
    room = step.get("room") if home == stage else None
    pos = None
    if home == stage:
        m_pos = _WARP_OBJ_POS_RE.search(detail)
        if m_pos:
            pos = [float(m_pos.group(1)), float(m_pos.group(2)), float(m_pos.group(3))]
    dest = None
    m_dest = _WARP_OBJ_DEST_RE.search(detail)
    if m_dest:
        dest = {
            "stage": m_dest.group(1),
            "room": int(m_dest.group(2)),
            "layer": int(m_dest.group(3)),
            "spawn": int(m_dest.group(4)),
        }
    else:
        m_rs = _WARP_OBJ_ROOM_SPAWN_RE.search(detail)
        if m_rs and stage:
            dest = {
                "stage": stage,
                "room": int(m_rs.group(1)),
                "layer": step.get("layer", -1),
                "spawn": int(m_rs.group(2)),
            }
    if dest is None:
        return None
    event = ""
    for rx in _WARP_OBJ_EVENT_RES:
        m_ev = rx.search(detail)
        if m_ev:
            event = m_ev.group(1)
            break
    if not event:
        v = step.get("event")
        event = "" if v is None else str(v)
    return {
        "actor": actor,
        "stage": home,
        "room": room,
        "pos": pos,
        "event": event,
        "dest": dest,
        # verbatim, so the engine can reuse _story_bits_ok (event bits AND item tests)
        "requires": list(step.get("requires_bits") or []),
    }


_WARP_OBJECT_GD = """extends Area3D
# gcrip: a placed warp object - the boss room's warp flower (daWarpf_c) and the in-dungeon
# lift (Ywarp00 / daWarpls_c). It is warp.gd and tag_event.gd in one: stepping in orders a
# stage event and, once that event (and any .stb it launched) ends, changes stage.
#
# WHICH event and destination it uses is read from the save the moment Link touches it.
# daWarpf_c::CreateInit asks checkEndDemo() whether this dungeon's reward has been taken and
# orders WARP_WIND (out through the reward cutscene) or WARP_WIND_AFTER (straight out); for
# the Tower of the Gods that test is the single event bit 0x2D10. The mined steps carry it as
# requires_bits, so Game.warp_branch() takes the most specific branch the save satisfies and
# the unconditional branch is the fallback.

var obj: Dictionary = {}
var actor := ""
var armed := false      # spawning on top of Link must not fire it (warp.gd's guard)
var busy := false

func setup(o: Dictionary, radius: float) -> void:
    obj = o
    actor = str(o.get("actor", ""))
    var shape := CollisionShape3D.new()
    var cyl := CylinderShape3D.new()
    cyl.radius = maxf(radius, 40.0)
    cyl.height = 400.0
    shape.shape = cyl
    add_child(shape)
    collision_layer = 0
    collision_mask = 1
    monitoring = true
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
    if busy or not armed or not (body is CharacterBody3D) or not body.is_in_group("player"):
        return
    if Game.event_running or Game.cutscene_running():
        return
    var branch: Dictionary = Game.warp_branch(obj)
    if branch.is_empty():
        return          # no branch this save satisfies: the warp is not open yet
    busy = true
    _take(branch)

func _take(branch: Dictionary) -> void:
    var ev := str(branch.get("event", ""))
    var raw = branch.get("dest", {})
    var dest: Dictionary = raw if raw is Dictionary else {}
    var stage := str(dest.get("stage", ""))
    var shown := ev
    if shown == "":
        shown = "(no event)"
    var going := stage
    if going == "":
        going = "(nowhere)"
    print("gcrip warp: ", actor, " ordering ", shown, " -> ", going,
          " room ", int(dest.get("room", 0)), " spawn ", int(dest.get("spawn", 0)))
    if ev != "" and Game.run_event(ev):
        # deliberately untyped: `finished` is event_runner.gd's own signal, and a Node-typed
        # var would make the static access to it a compile error
        var runner = Game.event_runner
        if runner != null and is_instance_valid(runner) and runner.has_signal("finished"):
            await runner.finished
        while Game.cutscene_running():
            await get_tree().physics_frame
    # the branch's own step id: story_event_done matches on id as well as on event name, so
    # the step is marked done and its sets_bits raised even when the event it ordered is
    # named only in the mined prose (WARP_WIND_AFTER vs the step's TOWER_WARPOUT)
    Game.story_event_done(str(branch.get("step", "")))
    if stage == "":
        busy = false
        return
    # the event just played is far longer than warp()'s just-arrived guard, but a fade-only
    # script can finish inside it - clear the guard the way the story chain does
    Game.last_warp_ms = -100000
    Game.warp(stage, int(dest.get("room", 0)), int(dest.get("spawn", 0)))
"""


_STORY_ACTOR_RE = re.compile(r"\b(Ba1|Ls1|Ji1|Zl1|ZL1|Aj1|Ko1|Ko2|Ob1|Yw1|Ym1|Ym2|Bm1|Dk)\b")
_STORY_ID_HINTS = {"grandma": "Ba1", "aryll": "Ls1", "orca": "Ji1", "tetra": "Zl1", "aj_": "Aj1"}


# The opening hands out four things the later steps and NPC lines are gated on.  The decomp
# gates them on the save file's collect[] bits; we model them as named items.
_STORY_PICKUPS = {
    # d_a_deku_item.cpp - the leaf itself, on top of the Ojtree poles
    "fw_get_deku_leaf": {"actor": "itemDek"},
    # d_a_boss_item.cpp - the pedestal that spawns the Heart Container in a cleared boss room
    "fw_heart_container": {"actor": "Bitem", "heart": 4},
}

_STORY_ITEMS = {
    "tale_demo_hero_clothes": "clothes",
    "aryll_get_telescope": "telescope",
    "orca_gives_hero_sword": "sword",
    "grandma_gives_shield": "shield",
    "fw_get_deku_leaf": "leaf",
    "fw_get_boomerang": "boomerang",
}

# d_a_npc_ls1.cpp:1884 - Aryll watches Link's scope: chkTelescope(Bm1 attention pos + 2000,
# 60 deg, -30 deg) succeeding is what sets her m850 = 3, which orders "zelda_fly".
# Two opening steps were mined as "tag", but no TagEv volume in those rooms names their
# event - the NPC's own code orders it.  Both radii are the actors' chk_areaIN parameter.
_STORY_NPC_ORDER = {
    # d_a_npc_ls1.cpp:1928 wait_1 - chk_areaIN(mPrm.m29 = 200) sets m850 = 4 -> "omedeto"
    "aryll_omedeto": {"actor": "Ls1", "radius": 200.0},
    # d_a_npc_zl1.cpp:2259 demo_4 - the Tetra placed for this state orders it as she spawns
    "tetra_dock_conversation": {"actor": "Zl1", "radius": 0.0},
}

_STORY_LOOK = {
    "zelda_fly_helmaroc": {
        "actor": "Bm1",
        "y": 2000.0,
        "half_angle": 60.0,
        "also_done": "telescope_watch_quill",
    },
}

# `object`: a placed non-NPC object polls its own condition and orders its own event.  That is
# a predicate, not a volume - daWarphr_c::normal_execute calls check_warp() every frame from the
# actor, where a TagEv would wait for a body_entered.  The mined steps only describe the
# predicate in prose, so the machine-readable form is spelled out here, keyed by step id.
#
# The vocabulary is a conjunction of optional keys - every key present must hold, and a block
# with no test at all fires as soon as the object is placed ("on spawn"):
#   actor       which placed actor answers (required; several copies are allowed - the copy
#               nearest Link is the one that polls, which is how three MtryB blocks work)
#   radius      Link within this distance of the object
#   min_radius  Link at least this far from the object
#   xz          measure the two distances in XZ only (default True, like check_warp)
#   switch      a room switch bit the object itself sets, with optional "room"
#   item        something Link must be carrying
#   swing       Link is mid sword swing
_STORY_OBJECT = {
    # d_a_warphr.cpp:402-416 check_warp: the distance is measured to the SHIP, not to Link, it
    # only counts while daPyStts0_SHIP_RIDE_e is set, and the threshold is 500.  Link swimming up
    # to the pool does nothing - he has to sail into it.
    "hy_warp_back": {"actor": "Ghrwp", "radius": 500.0, "ship": True},
    # d_a_obj_YLzou.cpp is signatures only - every body is a /* Nonmatching */ stub - so the real
    # condition is unrecoverable.  Approximated: the statue grinds aside as Link walks up to it.
    "hy_statue_moves": {"actor": "YLzou", "radius": 300.0},
    # there is no d_a_obj_mtryb.cpp at all, and nothing in the remake can push the three blocks
    # into their sockets, so the crest camera plays when Link reaches a block instead.
    "hy_floor_puzzle": {"actor": "MtryB", "radius": 300.0},
    # d_a_obj_barrier.cpp:227-260 - break_start_wait_proc wants the Master Sword equipped, one of
    # ten sword cut types running, and the player 8800+ units away in XZ.  We have no sword tiers,
    # so "item": "sword" is as close as the remake gets.  No Barrier is placed in Hyrule's
    # exported actors, so this block finds no object and the step stays asleep.
    "hy_third_visit_break_barrier": {
        "actor": "Barrier",
        "min_radius": 8800.0,
        "item": "sword",
        "swing": True,
    },
}

# Which actor's death advances which mined step.  The trigger detail names the actor in prose;
# this table is the structured form, kept here rather than in the mined JSON so the chapter files
# stay a record of what the decomp says.  `stage` overrides the step's own stage when the fight
# happens somewhere else (Ganon's Tower steps sit on the approach room, not the arena).
_STORY_DEFEAT = {
    "dr_clear_room_bars_open": {"room_clear": True},
    "dr_gohma": {"enemy": "Btd", "boss": True},
    "fw_mothula": {"enemy": "gmos"},
    "fw_kalle_demos": {"enemy": "Bkm", "boss": True},
    "ff2_phantom_ganon": {"enemy": "Fganon"},
    "ff2_helmaroc_king": {"enemy": "Bdk", "boss": True},
    "totg_gohdan": {"enemy": "Bst", "boss": True},
    "gt_trial_gohma": {"enemy": "Btd", "boss": True, "stage": "Xboss0"},
    "gt_trial_kalle_demos": {"enemy": "Bkm", "boss": True, "stage": "Xboss1"},
    # the rematch arenas place different actors from the main dungeons: Xboss2 holds "big_pow",
    # not the Earth Temple's "Bpw", and Molgera is "Bwd" - there is no "Bmgn" in the game at all
    "gt_trial_jalhalla": {"enemy": "big_pow", "boss": True, "stage": "Xboss2"},
    "gt_trial_molgera": {"enemy": "Bwd", "boss": True, "stage": "Xboss3"},
}

# TagMd (d_a_tag_etc.cpp) watches an NPC, not Link: which actor its box is for, and the
# ground-height window the NPC's own order check wants.  chkAdanmaeDemoOrder sets
# mCurEventMode = 6 when checkStatusCamTagIn() is true AND her ground height is between 600
# and 700 (d_a_npc_md.cpp:3528), which is what makes Link carry her onto the ledge.  The box
# itself, its scale and its EVNT index all come from the ripped TagMd placement.
_STORY_NPC_TAG = {
    "dr_throw_medli_to_ledge": {
        "tag": "TagMd",          # the tag actor whose placement carries the volume
        "actor": "Md1",          # who it watches (never the player)
        "ground_min": 600.0,
        "ground_max": 700.0,
    },
}

# Objects the player breaks by hitting them: one event name per damage stage, in order, plus
# the damage a hit has to carry (bomb Atp 4, so a sword swing does nothing).
#
# "pos" is None on purpose: the Ajav wall is a model-less "logic" placement (sea room 44,
# layers 5 and 7 - the endless night - params 28, at (-192902.5, 0, 324297.3)), and stage.gd
# resolves it from the stage's logic records at runtime, so it follows the story layer and
# the recentring offset without a copied coordinate.  Its six models are ajava..ajavf.bdl.
_STORY_HIT = {
    "jab_blow_open_the_cave": {
        "actor": "Ajav",
        "events": ["ajav_destroy0", "ajav_destroy1", "ajav_uzu"],
        "min_damage": 4,
        "room": 44,
        "switch": None,
        "size": [700.0, 900.0, 400.0],
        "pos": None,
        "rot_y_deg": 0.0,
    },
}

# The two timed islands.  Like _STORY_HIT these keep the structured form here so the chapter
# files stay a record of what the decomp says rather than of what this engine needs.
# swSave / bitTRB / the 300 seconds are all read out of the placements' params in
# ww_story_labyrinths.json; sources are on each step there.
_STORY_TIMER = {
    "icering_timer_starts": {
        "start": True, "switch": 27, "room": 40, "seconds": 300.0,
        "cave_stage": "MiniHyo", "isle_room": 40, "after_event": "MELT_ICE",
    },
    "firemountain_timer_starts": {
        "start": True, "switch": 24, "room": 20, "seconds": 300.0,
        "cave_stage": "MiniKaz", "isle_room": 20, "after_event": "FREEZE_VOLCANO",
    },
    # the failure branch; only Ice Ring was mined as its own step, Fire Mountain shares the code
    "icering_timeout": {"timeout": True, "cave_stage": "MiniHyo"},
    # success: the cave-side VolTag watching its chest bit
    "icering_beaten": {"beaten": True, "cave_stage": "MiniHyo", "tbox": 1},
    "firemountain_beaten": {"beaten": True, "cave_stage": "MiniKaz", "tbox": 0},
}

_DLG_BIT_RE = re.compile(r"UNK_([0-9A-Fa-f]{4})")
_DLG_TYPE_RE = re.compile(r"type\s*([0-9](?:\s*/\s*[0-9])*)")
_DLG_PAREN_RE = re.compile(r"\(([^)]*)\)")
# lines whose condition is a counter, a menu choice or a sub-quest we do not model at all
_DLG_SKIP_RE = re.compile(
    r"eventReg|soup|fairy|pig|Crest|delivered|choice|prompts|stomping|showing|rolled into"
    r"|telescope on|event data|cutscene chain|master|scope",
    re.I,
)
_DLG_NEG_BEFORE = ("!", "not ", "until ", "no ", "before ", "without ", "unless ")
_DLG_ITEM_WORDS = {
    "sword": "sword",
    "shield": "shield",
    "clothes": "clothes",
    "telescope": "telescope",
}
_DLG_PHASE_WORDS = ("first talk", "first", "repeat", "just set", "second", "same session")
# hand-wired conditions for lines whose prose says something the parser cannot
_DLG_OVERRIDE = {
    "Ba1|right after tale_1 cutscene (same session)": {"bits": ["0x2A80"], "phase": "first"},
}


def _dlg_strip_notes(key: str) -> str:
    """Drop parentheticals that annotate which bit a line SETS rather than requires."""

    def keep(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        low = inner.lower()
        if "set by" in low or low.startswith("sets ") or re.fullmatch(r"UNK_[0-9A-Fa-f]{4}", inner):
            return " "
        return m.group(0)

    return _DLG_PAREN_RE.sub(keep, key)


def _dlg_condition(text: str, flags: dict) -> dict:
    """Pull event bits and item requirements out of one prose condition."""
    bits: list[str] = []
    nbits: list[str] = []
    for m in _DLG_BIT_RE.finditer(text):
        before = text[max(0, m.start() - 10) : m.start()].lower()
        after = text[m.end() : m.end() + 8].lower()
        neg = any(w in before for w in _DLG_NEG_BEFORE) or "clear" in after
        (nbits if neg else bits).append("0x" + m.group(1).upper())
    for name, value in flags.items():
        idx = text.find(name)
        if idx < 0:
            continue
        before = text[max(0, idx - 10) : idx].lower()
        neg = any(w in before for w in _DLG_NEG_BEFORE)
        (nbits if neg else bits).append(value)
    needs: list[str] = []
    nneeds: list[str] = []
    low = text.lower()
    for word, item in _DLG_ITEM_WORDS.items():
        idx = low.find(word)
        if idx < 0:
            continue
        before = low[max(0, idx - 8) : idx]
        (nneeds if any(w in before for w in _DLG_NEG_BEFORE) else needs).append(item)
    for m in re.finditer(r"checkCollect\((\d)\)", text):
        needs.append("sword" if m.group(1) == "0" else "shield")
    cond: dict = {}
    if bits:
        cond["bits"] = sorted(set(bits))
    if nbits:
        cond["not_bits"] = sorted(set(nbits))
    if needs:
        cond["needs"] = sorted(set(needs))
    if nneeds:
        cond["not_needs"] = sorted(set(nneeds))
    return cond


def _dlg_base(key: str) -> str:
    """The key with its first/repeat wording removed, so the two halves of a pair match."""
    b = key.lower()
    for w in _DLG_PHASE_WORDS:
        b = b.replace(w, " ")
    return re.sub(r"[^a-z0-9_]+", " ", b).strip()


def _dialogue_with_conditions(path: Path) -> dict:
    """Turn each NPC's prose "alternatives" keys into conditions the engine can test, so a
    villager's line follows the story instead of being a fixed list (Grandma stops asking for
    Aryll once the pirates have her)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    flags = {
        name: str(desc).split(",")[0].strip()
        for name, desc in (data.get("_meta", {}).get("story_flags", {}) or {}).items()
        if str(desc).strip().startswith("0x")
    }
    for actor, info in data.items():
        if actor.startswith("_") or not isinstance(info, dict):
            continue
        type_conds = {
            t: _dlg_condition(str(desc), flags) for t, desc in (info.get("types", {}) or {}).items()
        }
        # a variant that "sets UNK_xxxx on spawn" conditions its own later lines on that bit
        spawn_bits = sorted(
            {
                "0x" + m.group(1).upper()
                for desc in (info.get("types", {}) or {}).values()
                for m in re.finditer(r"sets UNK_([0-9A-Fa-f]{4}) on spawn", str(desc))
            }
        )
        if spawn_bits:
            info["spawn_bits"] = spawn_bits
        rules = []
        for key, ids in (info.get("alternatives", {}) or {}).items():
            if not isinstance(ids, list) or not ids:
                continue
            over = _DLG_OVERRIDE.get(f"{actor}|{key}")
            if over is None and _DLG_SKIP_RE.search(key):
                continue
            text = _dlg_strip_notes(key)
            cond = dict(over) if over else _dlg_condition(text, flags)
            phase = str(cond.pop("phase", ""))
            if not phase:
                if "repeat" in key.lower():
                    phase = "repeat"
                elif any(w in key.lower() for w in ("first", "just set", "same session")):
                    phase = "first"
            tm = _DLG_TYPE_RE.search(key)
            if tm and not over:
                wanted = [t.strip() for t in tm.group(1).split("/")]
                alts = [type_conds[t] for t in wanted if type_conds.get(t)]
                if alts:
                    cond["type_conds"] = alts
            if not cond:
                continue  # nothing testable: never fire it blind
            score = 10 * (len(cond.get("bits", [])) + len(cond.get("not_bits", [])))
            score += 4 * (len(cond.get("needs", [])) + len(cond.get("not_needs", [])))
            score += 6 * len(cond.get("type_conds", []))
            msgs = [int(i) for i in ids if isinstance(i, int)]
            if not msgs:
                continue  # a prose note ("2513 if ... else ..."), not a message chain
            cond.update(
                {"key": key, "ids": msgs, "phase": phase, "score": score, "base": _dlg_base(text)}
            )
            rules.append(cond)
        firsts = {r["base"]: r["key"] for r in rules if r["phase"] == "first"}
        repeats = {r["base"] for r in rules if r["phase"] == "repeat"}
        for r in rules:
            if r["phase"] == "repeat" and r["base"] in firsts:
                r["pair_key"] = firsts[r["base"]]
            elif r["phase"] == "first" and r["base"] not in repeats:
                r["solo"] = True
            r.pop("base", None)
        if rules:
            info["rules"] = rules
    return data


# the chapters in story order; anything else matching ww_story_*.json is appended after them
_STORY_CHAPTERS = [
    "outset",
    "fortress",
    "dragonroost",
    "forbiddenwoods",
    "jabun",
    "towerofgods",
    "hyrule",
    "temples",
    "fortress2",
    "ganon",
    "ganontower",
]


def _story_all_chapters(data_dir: Path) -> dict:
    """Every mined chapter merged into one graph, in story order.

    Each file is self-contained (its own _bits, _source and steps); the engine only needs the
    steps, but the merged file keeps the per-chapter provenance so the graph stays traceable.
    """
    found = {f.stem[len("ww_story_") :]: f for f in sorted(data_dir.glob("ww_story_*.json"))}
    order = [c for c in _STORY_CHAPTERS if c in found]
    order += [c for c in sorted(found) if c not in order]
    merged: dict = {"chapters": order, "_bits": {}, "_sources": {}, "steps": []}
    for chapter in order:
        data = _story_with_actors(found[chapter])
        merged["_bits"].update(data.get("_bits") or {})
        merged["_sources"][chapter] = data.get("_source", "")
        for step in data.get("steps", []):
            step["chapter"] = chapter
            merged["steps"].append(step)
    return merged


def _story_with_actors(path: Path) -> dict:
    """The mined opening graph, with each talk step's actor pulled out of its prose trigger
    detail so the engine can match "Link talked to Ba1" without parsing English."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for step in data.get("steps", []):
        trig = step.get("trigger") or {}
        if trig.get("kind") != "talk":
            continue
        m = _STORY_ACTOR_RE.search(str(trig.get("detail", "")))
        actor = None
        if m:
            actor = "Zl1" if m.group(1).upper() == "ZL1" else m.group(1)
        else:
            for hint, name in _STORY_ID_HINTS.items():
                if str(step.get("id", "")).startswith(hint):
                    actor = name
                    break
        step["actor"] = actor
    for step in data.get("steps", []):
        # the mined "gives_item" is the game's dItemNo prose; the engine wants a plain name
        item = _STORY_ITEMS.get(str(step.get("id", "")))
        if item:
            step["item_key"] = item
        m_item = re.search(r"\((0x[0-9A-Fa-f]{1,2})\)", str(step.get("gives_item") or ""))
        if m_item and (step.get("trigger") or {}).get("kind") == "chest":
            step["item_no"] = int(m_item.group(1), 16)
        beat = _STORY_DEFEAT.get(str(step.get("id", "")))
        if beat:
            step["defeat"] = dict(beat)
        if (step.get("trigger") or {}).get("kind") == "item":
            step["item_nos"] = [
                int(h, 16) for h in re.findall(r"0x([0-9A-Fa-f]{2})", str(step.get("gives_item") or ""))
            ]
            pick = _STORY_PICKUPS.get(str(step.get("id", "")))
            if pick:
                step["pickup"] = pick
        look = _STORY_LOOK.get(str(step.get("id", "")))
        if look:
            step["look"] = look
        near = _STORY_NPC_ORDER.get(str(step.get("id", "")))
        if near:
            step["near"] = near
        npc_tag = _STORY_NPC_TAG.get(str(step.get("id", "")))
        if npc_tag:
            step["npc_tag"] = npc_tag
        hit = _STORY_HIT.get(str(step.get("id", "")))
        if hit:
            step["hit"] = hit
        clock = _STORY_TIMER.get(str(step.get("id", "")))
        if clock:
            step["timer"] = clock
        obj = _STORY_OBJECT.get(str(step.get("id", "")))
        if obj and (step.get("trigger") or {}).get("kind") == "object":
            step["object"] = obj
    # some steps are reached by the previous one calling setNextStage(stage, spawn, room, layer):
    # that re-entry is what auto-plays their cutscene (Grandma's tale, the shield, the ship)
    warp_re = re.compile(
        r'setNextStage\(\s*"([A-Za-z0-9_]+)"\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*([^,)]+),\s*(\d+)'
    )
    for step in data.get("steps", []):
        m = warp_re.search(str((step.get("trigger") or {}).get("detail", "")))
        if not m:
            continue
        stage, spawn, room, layer = m.groups()
        room = room.strip()
        step["warp"] = {
            "stage": stage,
            "spawn": int(spawn, 0),
            "room": int(room) if room.isdigit() else None,
            "layer": int(layer),
        }
    # placed warp objects: the object, the event it orders and where that event sends Link,
    # pulled out of the step's prose so the engine never parses English
    for step in data.get("steps", []):
        wo = _warp_object_of(step)
        if wo is not None:
            step["warp_object"] = wo
    return data


def _copy_cutscenes(rip_dir: Path, out_dir: Path) -> int:
    """Baked .stb scenes (``gcrip cutscenes``) -> the project's cutscenes/ folder."""
    src = rip_dir / "cutscenes"
    if not src.is_dir():
        return 0
    dst = out_dir / "cutscenes"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for js in sorted(src.glob("*.json")):
        target = dst / js.name
        if not target.exists() or target.stat().st_mtime < js.stat().st_mtime:
            shutil.copyfile(js, target)
        n += 1
    return n


def _normalise_layer_rules(path: Path) -> dict:
    """data/ww_layers.json (mined from the decomp) -> a form GDScript can evaluate directly:
    each rule becomes an ordered list of (event bit, must-be-set) tests plus the day / night
    layer. Conditions like ``!isEventBit(UNK_0520) && isEventBit(UNK_0E20)`` carry one
    ``isEventBit`` call per entry of ``bits``, in order, so the leading ``!`` of each call
    gives that bit's polarity. Rules whose condition uses anything else (nightStop() ...)
    keep an ``extra`` note and are skipped at runtime unless their bit tests alone match."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = []
    for r in raw.get("rules", []):
        calls = re.findall(r"(!?)\s*isEventBit\s*\(", r.get("condition", ""))
        bits = list(r.get("bits", []))
        tests = [[int(b), calls[i] != "!"] for i, b in enumerate(bits) if i < len(calls)]
        extra = re.sub(r"!?\s*isEventBit\s*\([^)]*\)", "", r.get("condition", ""))
        extra = extra.replace("&&", "").replace("||", "").strip()
        day = r.get("layer_day", r.get("layer"))
        night = r.get("layer_night", r.get("layer"))
        if day is None and night is None:
            continue
        rules.append(
            {
                "stage": r.get("stage"),
                "room": r.get("room"),
                "tests": tests,
                "layer_day": day if day is not None else night,
                "layer_night": night if night is not None else day,
                "extra": extra,
                "source": r.get("source", ""),
            }
        )
    d_day = raw.get("default_layer_day", raw.get("default_layer"))
    d_night = raw.get("default_layer_night", raw.get("default_layer"))
    return {
        "_source": raw.get("_source", ""),
        "rules": rules,
        "default_day": 0 if d_day is None else d_day,
        "default_night": (0 if d_day is None else d_day) if d_night is None else d_night,
    }


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


def _project_godot(
    title: str, main_scene: str, renderer: str = "forward_plus", physical: bool = False
) -> str:
    k = _KEYS
    return f"""; generated by gcrip godot - open this folder with Godot 4
config_version=5

[application]

config/name={json.dumps(title)}
run/main_scene="res://scenes/{main_scene}.tscn"
config/features=PackedStringArray("4.4")

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

renderer/rendering_method="{renderer}"
renderer/rendering_method.mobile="{renderer}"

{_render_block(physical)}
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


def _write_hdri(out_dir: Path, hdri: dict | None) -> None:
    """Write sky_<slot>.hdr for each slot and sky.json describing them all."""
    import shutil

    if not hdri:
        return
    from gcrip.formats import hdr as hdr_mod

    slots = {}
    for slot, path in hdri.items():
        if not path.exists():
            print(f"  hdri {slot}: {path} not found")
            continue
        try:
            img = hdr_mod.parse(path.read_bytes())
            direction, peak, ratio = img.sun()
            shutil.copyfile(path, out_dir / f"sky_{slot}.hdr")
            el = math.degrees(math.asin(max(-1.0, min(1.0, -direction[1]))))
            slots[slot] = {
                "source": path.name,
                "file": f"sky_{slot}.hdr",
                "sun_dir": [round(v, 5) for v in direction],
                "sun_elev_deg": round(el, 1),
                "sun_to_sky": round(ratio, 1),
            }
            print(f"  hdri {slot}: {path.name} sun {el:.0f} deg up -> sky_{slot}.hdr")
        except Exception as exc:
            print(f"  hdri {slot} not written: {exc}")
    if slots:
        (out_dir / "sky.json").write_text(json.dumps({"slots": slots}, indent=1), encoding="utf-8")


def _write_ies(out_dir: Path) -> None:
    """Every gcrip/data/ies/*.ies -> ies/<name>.png, a light projector of the real throw."""
    src = Path(__file__).parent / "data" / "ies"
    if not src.is_dir():
        return
    from gcrip.formats import ies as ies_mod

    dst = out_dir / "ies"
    n = 0
    for f in sorted(src.glob("*.ies")):
        try:
            prof = ies_mod.parse(f.read_text(encoding="latin-1"))
            img = (prof.projector(256) * 255.0).astype("uint8")
            dst.mkdir(parents=True, exist_ok=True)
            rgb = __import__("numpy").stack([img, img, img], axis=-1)
            try:
                from PIL import Image

                Image.fromarray(rgb, "RGB").save(dst / f"{f.stem}.png")
            except ImportError:
                _write_png_rgb(dst / f"{f.stem}.png", rgb)
            n += 1
        except Exception as exc:
            print(f"  ies {f.name}: {exc}")
    if n:
        print(f"  ies: {n} photometric profiles -> ies/")


def _write_particles(rip_dir: Path, out_dir: Path) -> None:
    """fx/<id>.json + fx/tex/<name>.png for every effect in common.jpc."""
    try:
        from gcrip.formats import jpa
        from gcrip.stage import _Disc, _find_iso

        disc = _Disc(_find_iso(rip_dir, None))
        try:
            e = disc.entries.get("res/Particle/common.jpc")
            if e is None:
                print("  particles: common.jpc not on this disc")
                return
            bank = jpa.parse(disc.img.read(e.offset, e.size))
        finally:
            disc.close()
        fx = out_dir / "fx"
        tex_dir = fx / "tex"
        tex_dir.mkdir(parents=True, exist_ok=True)
        written_tex: set[str] = set()
        for name, tex in bank.textures:
            if name in written_tex:
                continue
            try:
                img = tex.decode()
                try:
                    from PIL import Image

                    Image.fromarray(img, "RGBA").save(tex_dir / f"{name}.png")
                except ImportError:
                    continue
                written_tex.add(name)
            except Exception:
                continue
        n = 0
        for ef in bank.effects:
            if ef.shape is None or ef.dynamics is None:
                continue
            ti = ef.texture_index
            tname = bank.textures[ti][0] if ti is not None and ti < len(bank.textures) else ""
            sh, dy, en = ef.shape, ef.dynamics, ef.envelope
            rec = {
                "id": ef.res_id,
                "texture": tname,
                "base_size": [sh.base_size[0] * 25.0, sh.base_size[1] * 25.0],
                "additive": sh.additive,
                "multiply": sh.multiply,
                "prm": list(sh.prm_color),
                "env": list(sh.env_color),
                "life_frames": int(dy.life_time),
                "max_frames": int(dy.max_frame),
                "rate": float(dy.rate),
                "volume_type": dy.volume_type,
                "volume_size": int(dy.volume_size),
                "vel_omni": float(dy.init_vel_omni),
                "vel_axis": float(dy.init_vel_axis),
                "vel_rndm": float(dy.init_vel_rndm),
                "spread": float(dy.spread),
                "children": ef.has_children,
                "fields": ef.has_fields,
            }
            if en is not None:
                rec["alpha"] = [en.alpha_in_timing, en.alpha_out_timing, en.alpha_in_value,
                                en.alpha_base_value, en.alpha_out_value]
                rec["scale"] = [en.scale_in_timing, en.scale_out_timing, en.scale_in_x,
                                en.scale_out_x, en.scale_in_y, en.scale_out_y]
            (fx / f"{ef.res_id:04x}.json").write_text(json.dumps(rec), encoding="utf-8")
            n += 1
        print(f"  particles: {n} effects, {len(written_tex)} textures -> fx/")
    except Exception as exc:
        print(f"  particles not written: {exc}")


def _write_wav(path: Path, pcm, rate: int) -> None:
    import struct
    import wave

    import numpy as np

    data = np.asarray(pcm, dtype=np.int16).tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate) if rate else 32000)
        w.writeframes(data)
    _ = struct


def _write_footsteps(rip_dir: Path, out_dir: Path) -> None:
    """sfx/foot_{material}_{foot}.wav for all 28 materials, from IBNK bank 131 program 0.

    key = 12 + 2*m is one foot, 13 + 2*m the other (ww_sound_effects.json, confirmed by the
    bank having exactly 56 key regions).  Decoded through the existing wsys decoder - no new
    sample-format code.
    """
    sfx = out_dir / "sfx"
    try:
        from gcrip.music import JAudioBanks
        from gcrip.stage import _Disc, _find_iso

        disc = _Disc(_find_iso(rip_dir, None))
        try:
            banks = JAudioBanks(disc)
            bank = banks.banks.get(131)
            if bank is None:
                return
            prog = bank.program(0)
            if prog is None or not hasattr(prog, "region"):
                return
            sfx.mkdir(parents=True, exist_ok=True)
            written = 0
            for m in range(28):
                for foot in (0, 1):
                    r = prog.region(12 + 2 * m + foot, 100)
                    if r is None:
                        continue
                    found = banks.lookup(131, r.wave_id)
                    if found is None:
                        continue
                    wave, pcm = found
                    if len(pcm) == 0:
                        continue
                    _write_wav(sfx / f"foot_{m}_{foot}.wav", pcm, wave.rate)
                    written += 1
            print(f"  footsteps: {written} waves -> sfx/")
        finally:
            disc.close()
    except Exception as exc:  # sound is a nicety; never fail an export over it
        print(f"  footsteps not written: {exc}")


def _write_toon_ramp(rip_dir: Path, out_dir: Path) -> None:
    """The game's own cel ramp: res/Object/System.arc :: archive/dat/toon.bti, 256x8 I4.

    The 8x8 ramp baked into every BMD is a placeholder that d_resorce.cpp:76-82 swaps at load
    by testing two characters of the texture name, so the real curve has to come from here.
    Decoded off the disc it is flat 0 up to index 119, rises to 137, then flat 255.
    """
    out = out_dir / "toon_ramp.png"
    try:
        from gcrip.formats import bti, rarc, yaz0
        from gcrip.stage import _Disc, _find_iso

        disc = _Disc(_find_iso(rip_dir, None))
        try:
            e = disc.entries.get("res/Object/System.arc")
            if e is None:
                return
            blob = disc.img.read(e.offset, e.size)
            if blob[:4] == b"Yaz0":
                blob = yaz0.decompress(blob)
            arc = rarc.parse(blob)
            for f in arc.files:
                if not f.path.endswith("toon.bti"):
                    continue
                tex = bti.parse(arc.read(blob, f))
                img = tex.decode()
                try:
                    from PIL import Image

                    Image.fromarray(img[:, :, :3], "RGB").save(out)
                except ImportError:
                    _write_png_rgb(out, img[:, :, :3])
                return
        finally:
            disc.close()
    except Exception as exc:  # the ramp is a nicety; never fail an export over it
        print(f"  toon ramp not written: {exc}")


def _write_png_rgb(path: Path, arr) -> None:
    """Minimal PNG writer, so the ramp does not depend on Pillow."""
    import struct
    import zlib

    h, w = arr.shape[0], arr.shape[1]
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


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
            node["name"] = (
                f"wall_{surface}_" + node.get("name", "col").replace("/", "_") + "-colonly"
            )
        elif surface and "mesh" in node:
            # liquid surfaces become colliders too; stage.gd moves them to the water /
            # hazard physics layers at runtime (Godot's import suffixes can't set layers)
            node["name"] = (
                f"liquid_{surface}_" + node.get("name", "col").replace("/", "_") + "-colonly"
            )
    tmp = col_gltf.with_suffix(".godot.gltf")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    try:
        out_glb.parent.mkdir(parents=True, exist_ok=True)
        out_glb.write_bytes(glbmod.pack(tmp))
    finally:
        tmp.unlink(missing_ok=True)
    return n_solid


def _trim_animations(
    doc: dict,
    blob: bytes,
    keep: tuple[str, ...],
    drop_root_motion: tuple[str, ...] = (),
) -> tuple[dict, bytes]:
    """Keep only the named animations, then garbage-collect accessors/bufferViews so
    the dropped clips' keyframe data leaves the buffer (Link ships 14 MB of clips).
    Clips in ``drop_root_motion`` lose the root joint's translation track: the game
    applies that motion from code (ladder rungs, shimmy, climb-over), and so do we."""
    doc = json.loads(json.dumps(doc))  # deep copy
    doc["animations"] = [a for a in doc.get("animations", []) if a.get("name") in keep]
    if drop_root_motion:
        root_nodes = set()
        for skin in doc.get("skins", []):
            joints = skin.get("joints", [])
            if joints:
                root_nodes.add(joints[0])
        for i, n in enumerate(doc.get("nodes", [])):
            if n.get("name") in ("link_root", "world_root"):
                root_nodes.add(i)
        for a in doc["animations"]:
            if a.get("name") not in drop_root_motion:
                continue
            a["channels"] = [
                c
                for c in a.get("channels", [])
                if not (
                    c["target"].get("path") == "translation"
                    and c["target"].get("node") in root_nodes
                )
            ]
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


def _animated_glb(
    src: Path, out_glb: Path, clips: tuple[str, ...], drop_root_motion: tuple[str, ...] = ()
) -> list[str]:
    """Rigged model + the named clips as a small self-contained glb. Returns the clip
    names that were kept (in file order)."""
    doc = json.loads(src.read_text(encoding="utf-8"))
    blob = (src.parent / doc["buffers"][0]["uri"]).read_bytes()
    trimmed, new_bin = _trim_animations(doc, blob, clips, drop_root_motion)
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
    "ropeend": "Link.arc/archive/bdlc/ropeend.gltf",
}


def _item_models(rip_dir: Path, out_dir: Path) -> int:
    """Link's item models (arrow, boomerang, bomb, hookshot, bow) -> items/<name>.glb."""
    results = rip_dir / "rip_results.json"
    if not results.exists():
        return 0
    models = json.loads(results.read_text(encoding="utf-8"))["models"]
    n = 0
    for name, suffix in _ITEM_MODELS.items():
        rel = next(
            (m["out_rel"] for m in models if (m.get("out_rel") or "").endswith(suffix)), None
        )
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
    from gcrip.cutscene import clips_by_actor

    clips = _PLAYER_CLIPS + tuple(sorted(clips_by_actor().get("Link", ())))
    _animated_glb(rip_dir / rel, out_glb, clips, _PLAYER_ROOT_MOTION_CLIPS)
    return True


# Actors that come alive with their own rig + clips (everything else stays a baked mesh).
# Clip choice: anything whose name contains one of these words, capped, so an NPC archive
# with 60 cutscene clips still exports small.
_ANIMATED_ACTORS = {
    "Aj1",
    "Ls1",
    "Ob1",
    "Ko1",
    "Ko2",
    "Yw1",
    "Ym1",
    "Ym2",
    "Bm1",
    "Ji1",
    "Ba1",
    "Kg1",
    "Kg2",
    "Dk",
    "Zl1",
    "NpcSo",
    "Bk",
    "Pig",
    "Kamome",
    "kani",
    "Ac1",
    "Cb1",
    "Hi1",
    "Md1",
    "De1",
    "Co1",
    "Zk1",
    "Tc",
    "Bs1",
    "Bs2",
    "Kp1",
    "Mt",
    "Ds1",
    "Sa1",
    "Gk1",
    "Um1",
    "Uo1",
    "Uo2",
    "Uo3",
    "Ub1",
    "Ub2",
    "Ub3",
    "Ub4",
    "Bj1",
    "Jb1",
    "Mk",
    "Hr",
    "Aj2",
    "Bmcon1",
    "Bms1",
    "Ah",
    "Auzu",
    "Puti",
    "c_green",
    "c_red",
    "c_blue",
    "c_black",
    "c_kiiro",
    "keeth",
    "Fkeeth",
    "mo2",
    "Tn",
    "Stal",
    "amos2",
    "Bb",
    "p_hat",
    "Oq",
    "wiz_r",
}
_ANIM_WORDS = ("wait", "talk", "walk", "run", "attack", "damage", "dead", "fly", "swim", "idle")
_ANIM_CAP = 12


def _head_model(body: Path) -> Path | None:
    """The separate head model of an NPC body (``<stem>head01``, ``<stem>_head``, ``*head01``)
    inside the same archive, or None."""
    arc_dir = body.parent.parent  # .../<Arc>.arc/archive
    stem = body.stem.lower()
    cands = [g for g in arc_dir.rglob("*.gltf") if g != body and "head" in g.stem.lower()]
    if not cands:
        return None

    def score(g: Path) -> tuple:
        n = g.stem.lower()
        return (0 if n.startswith(stem) else 1, 0 if "01" in n or n.endswith("_head") else 1, n)

    return sorted(cands, key=score)[0]


def _actor_models(rip_dir: Path, out_dir: Path, stage_data: dict) -> dict:
    from gcrip.cutscene import clips_by_actor

    cut_clips = clips_by_actor()
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
            if not rel:
                continue
            src = rip_dir / rel
            if not src.exists():
                continue
            if rel in table:
                if "head" not in table[rel]:  # older table: add the separate head model
                    head = _head_model(src)
                    if head is not None:
                        head_glb = f"{Path(rel).parent.parent.parent.name}_{head.stem}.glb".replace(
                            ".arc", ""
                        )
                        try:
                            _animated_glb(head, out_dir / "actors" / "models" / head_glb, ())
                            table[rel]["head"] = f"res://actors/models/{head_glb}"
                        except (OSError, ValueError, KeyError):
                            pass
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
            # plus whatever the cutscenes make this actor play
            want = cut_clips.get(str(rec.get("actor", "")), set())
            picked += [n for n in names if n in want and n not in picked]
            glb_name = f"{Path(rel).parent.parent.parent.name}_{Path(rel).stem}.glb".replace(
                ".arc", ""
            )
            kept = _animated_glb(src, out_dir / "actors" / "models" / glb_name, tuple(picked))
            table[rel] = {"glb": f"res://actors/models/{glb_name}", "clips": kept}
            # NPCs ship their head as a separate model in the same archive (ywhead01, oba_head,
            # kohead01 ...) attached to the body's "head" joint at runtime
            head = _head_model(src)
            if head is not None:
                head_glb = f"{Path(rel).parent.parent.parent.name}_{head.stem}.glb".replace(
                    ".arc", ""
                )
                try:
                    _animated_glb(head, out_dir / "actors" / "models" / head_glb, ())
                    table[rel]["head"] = f"res://actors/models/{head_glb}"
                except (OSError, ValueError, KeyError):
                    pass
    table_path.write_text(json.dumps(table, indent=1), encoding="utf-8")
    return table


def export_godot(
    rip_dir: Path,
    stages: list[str] | None = None,
    *,
    out_dir: Path | None = None,
    quiet: bool = False,
    renderer: str = "forward_plus",
    hdri: dict | None = None,
    physical: bool | None = None,
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
    # simple lighting is the default; physical is opt-in, auto-on with an HDR
    physical_on = bool(hdri) if physical is None else bool(physical)
    (out_dir / "stages").mkdir(parents=True, exist_ok=True)
    (out_dir / "scenes").mkdir(parents=True, exist_ok=True)

    title = "gcrip level viewer"
    manifest = rip_dir / "disc_manifest.json"
    if manifest.exists():
        with contextlib.suppress(OSError, ValueError, KeyError):
            title = json.loads(manifest.read_text(encoding="utf-8"))["game"]["title"]

    done = []
    stage_data: dict[str, dict] = {}
    # every distinct place a door lands, for the --doors harness to stand on
    door_targets: dict[tuple[str, int, int], dict] = {}
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
        exits = [dict(e) for e in (rep.get("exits") or [])]
        for e in exits:
            # interiors return to "sea"; prefer the island's own scene (sea_r44) when it
            # exists - the whole-sea scene is heavy and its Outset lies 300k units off-centre
            island = f"{e.get('dest_stage', '')}_r{e.get('room', -1)}"
            if e.get("dest_stage") == "sea" and island in available:
                e["dest_stage"] = island
            # collect where every door lands, so the --doors harness can stand on each one
            key = (str(e.get("dest_stage", "")), int(e.get("dest_room", 0)),
                   int(e.get("dest_spawn", 0)))
            door_targets.setdefault(
                key, {"stage": key[0], "room": key[1], "spawn": key[2], "from": []}
            )["from"].append(name)
        # the Great Sea's water is the y=0 plane (islands are authored around it); proper
        # per-stage water volumes come with the dzb liquid surfaces later
        water = 0.0 if name.lower().startswith("sea") else -1.0e9
        (out_dir / "scenes" / f"{name}.tscn").write_text(
            _stage_tscn(
                name, spawn, has_col=has_col, exits=exits, water_level=water, spawns=spawns,
                physical=physical_on,
            ),
            encoding="utf-8",
        )
        stage_data[name] = {
            "spawns": spawns,
            "actors": rep.get("actors") or [],
            "ships": rep.get("ships") or [],
            "room_sets": rep.get("room_sets") or [],
            "wave_max": rep.get("wave_max") or {},
            "offset": rep.get("offset") or [0.0, 0.0, 0.0],
            "tags": rep.get("tags") or [],
            "logic": rep.get("logic") or [],
            "event_table": rep.get("event_table") or [],
            "bridges": rep.get("bridges") or [],
        }
        ev_json = d / f"{gltf_path.stem}_events.json"
        if ev_json.exists():
            (out_dir / "events").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ev_json, out_dir / "events" / f"{name}.json")
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
        (out_dir / "npc_dialogue.json").write_text(
            json.dumps(_dialogue_with_conditions(dlg)), encoding="utf-8"
        )
    # Field-level merge: a later file may only ADD to an entry, never blank a field that an
    # earlier file filled.  Whole-entry update() meant a null-heavy file winning on filename
    # order alone silently discarded good mined numbers.
    #
    # Some enemies are PLACED under a different name than the class the decomp profiles them
    # under, so a lookup by placed name misses them entirely: "pow" appears 28 times in the
    # placement data and "PW" never; "Oqw" 22 times against "Oq"'s 7.
    # Some enemies are PLACED under one name and PROFILED under another: the DZR object name
    # and the actor/archive name differ.  "pow" is placed 28 times and "PW" never; "Oqw" 22
    # against "Oq"'s 7; and "big_pow" is d_stage.cpp:694's only row for fpcNm_BPW_e, whose
    # archive - and so our profile key - is "Bpw" (both M_DaiB and the Xboss2 rematch place
    # it as big_pow).  Publish each profile under both names so a lookup by placed name hits.
    enemy_aliases = {"pow": "PW", "Oqw": "Oq", "big_pow": "Bpw"}
    merged: dict = {}
    for part in sorted((Path(__file__).parent / "data").glob("ww_enemies_*.json")):
        try:
            for actor, entry in json.loads(part.read_text(encoding="utf-8")).items():
                if not isinstance(entry, dict) or actor not in merged:
                    merged[actor] = entry
                    continue
                have = merged[actor]
                for field, value in entry.items():
                    if value is not None or have.get(field) is None:
                        have[field] = value
        except (OSError, ValueError):
            continue
    for placed, profiled in enemy_aliases.items():
        if profiled in merged and placed not in merged:
            merged[placed] = merged[profiled]
    (out_dir / "enemies.json").write_text(json.dumps(merged, indent=1), encoding="utf-8")
    story = _story_all_chapters(Path(__file__).parent / "data")
    if story["steps"]:
        (out_dir / "story.json").write_text(json.dumps(story), encoding="utf-8")
    layers_src = Path(__file__).parent / "data" / "ww_layers.json"
    if layers_src.exists():
        (out_dir / "layers.json").write_text(
            json.dumps(_normalise_layer_rules(layers_src), indent=1), encoding="utf-8"
        )
    n_songs = _copy_music(rip_dir, out_dir, list(stage_data))
    if not quiet:
        print(f"  {n_songs} songs in audio/music/ (gcrip music renders more)")
    (out_dir / "player.gd").write_text(_PLAYER_GD, encoding="utf-8")
    (out_dir / "player.tscn").write_text(_player_tscn(has_model), encoding="utf-8")
    (out_dir / "game.gd").write_text(_GAME_GD, encoding="utf-8")
    (out_dir / "lighting.json").write_text(
        json.dumps({"physical": physical_on}), encoding="utf-8"
    )
    # Four variants of each cel shader, because BOTH facts are fixed at shader compile time:
    #   cull mode   - the game's GX cull mode, carried through glTF as doubleSided
    #   blending    - whether the material writes ALPHA, which decides opaque vs transparent
    # The plain name is the common case: back-face culled and OPAQUE.
    for suffix, src in _shader_variants(_TOON_SHADER):
        (out_dir / f"toon{suffix}.gdshader").write_text(src, encoding="utf-8")
    _ww_shader = (Path(__file__).parent / "data" / "ww_material.gdshader").read_text(
        encoding="utf-8"
    )
    assert "cull_back" in _ww_shader, "ww_material.gdshader lost its cull_back render_mode"
    # the lit looks carry their ALPHA write inline; swap it for the marker the variant
    # builder understands, so this shader gets the same opaque / blended split as the toon one
    _alpha_line = "    ALPHA = base.a;" + chr(10)
    assert _ww_shader.count(_alpha_line) == 1, "ww_material.gdshader ALPHA moved"
    _ww_shader = _ww_shader.replace(_alpha_line, "    // gcrip:alpha" + chr(10))
    for suffix, src in _shader_variants(_ww_shader):
        (out_dir / f"ww_material{suffix}.gdshader").write_text(src, encoding="utf-8")
    mats_src = Path(__file__).parent / "data" / "ww_materials.json"
    if mats_src.exists():
        (out_dir / "materials.json").write_text(mats_src.read_text(encoding="utf-8"), encoding="utf-8")
    _write_footsteps(rip_dir, out_dir)
    _write_particles(rip_dir, out_dir)
    (out_dir / "fx.gdshader").write_text(_FX_SHADER, encoding="utf-8")
    (out_dir / "ocean.gdshader").write_text(_OCEAN_SHADER, encoding="utf-8")
    (out_dir / "skydome.gdshader").write_text(_SKYDOME_SHADER, encoding="utf-8")
    _write_ies(out_dir)
    _write_hdri(out_dir, hdri if physical_on else None)
    _write_toon_ramp(rip_dir, out_dir)
    (out_dir / "warp.gd").write_text(_WARP_GD, encoding="utf-8")
    (out_dir / "event_runner.gd").write_text(_EVENT_GD, encoding="utf-8")
    (out_dir / "cutscene.gd").write_text(_CUTSCENE_GD, encoding="utf-8")
    n_cuts = _copy_cutscenes(rip_dir, out_dir)
    if not quiet and n_cuts:
        print(f"  {n_cuts} baked cutscenes in cutscenes/")
    (out_dir / "items").mkdir(parents=True, exist_ok=True)
    for fname, src in (
        ("arrow.gd", _ARROW_GD),
        ("boomerang.gd", _BOOMERANG_GD),
        ("bomb.gd", _BOMB_GD),
        ("hookshot.gd", _HOOKSHOT_GD),
        ("ship.gd", _SHIP_GD),
        ("rope.gd", _ROPE_GD),
        ("enemy_shot.gd", _ENEMY_SHOT_GD),
    ):
        (out_dir / "items" / fname).write_text(src, encoding="utf-8")
    n_items = _item_models(rip_dir, out_dir)
    if not quiet:
        print(f"  {n_items} item models in items/")
    (out_dir / "calib.gd").write_text(_CALIB_GD, encoding="utf-8")
    (out_dir / "calib.tscn").write_text(_CALIB_TSCN, encoding="utf-8")
    (out_dir / "stage.gd").write_text(_STAGE_GD, encoding="utf-8")
    (out_dir / "dialog.gd").write_text(_DIALOG_GD, encoding="utf-8")
    (out_dir / "control.gd").write_text(_CONTROL_GD, encoding="utf-8")
    (out_dir / "dialog.tscn").write_text(_DIALOG_TSCN, encoding="utf-8")
    (out_dir / "menu.gd").write_text(_MENU_GD, encoding="utf-8")
    (out_dir / "menu.tscn").write_text(_MENU_TSCN, encoding="utf-8")
    (out_dir / "actors").mkdir(exist_ok=True)
    for fname, src_text in {
        "carriable.gd": _ACTOR_BASE_GD,
        "item.gd": _ACTOR_ITEM_GD,
        "sign.gd": _ACTOR_SIGN_GD,
        "kui.gd": _KUI_GD,
        "enemy.gd": _ACTOR_ENEMY_GD,
        "tag_event.gd": _TAG_EVENT_GD,
        "tag_island.gd": _TAG_ISLAND_GD,
        "salvage.gd": _SALVAGE_GD,
        "door.gd": _DOOR_GD,
        "hit_switch.gd": _HIT_SWITCH_GD,
        "flame_flicker.gd": _FLAME_FLICKER_GD,
        "npc_tag.gd": _NPC_TAG_GD,
        "hit_object.gd": _HIT_OBJECT_GD,
        "warp_object.gd": _WARP_OBJECT_GD,
        "chest.gd": _ACTOR_CHEST_GD,
        "pickup.gd": _ACTOR_PICKUP_GD,
        "pig.gd": _ACTOR_PIG_GD,
        "gull.gd": _ACTOR_GULL_GD,
        "npc.gd": _ACTOR_NPC_GD,
        "bokoblin.gd": _ACTOR_BOKOBLIN_GD,
    }.items():
        (out_dir / "actors" / fname).write_text(src_text, encoding="utf-8")
    msgs = rip_dir / "text" / "messages.json"
    if msgs.exists():  # gcrip msg output -> in-game text box
        shutil.copyfile(msgs, out_dir / "messages.json")
    # which save slot each stage's dungeon state lives in, and whether the HUD shows keys
    # (STAG mProp: slot = (mProp >> 1) & 0x7F, key counter = mProp & 1)
    dung_src = Path(__file__).parent / "data" / "ww_dungeons.json"
    try:
        dung_all = json.loads(dung_src.read_text(encoding="utf-8"))
        slots = dung_all.get("_stage_save_slots", {}).get("stages", {})
    except (OSError, ValueError):
        slots = {}
    (out_dir / "dungeons.json").write_text(
        json.dumps(
            {
                k: {
                    "slot": v.get("slot", 11),
                    "key_counter": bool(v.get("key_counter_shown", False)),
                    "type": v.get("stage_type", ""),
                }
                for k, v in slots.items()
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    sd_path = out_dir / "stage_data.json"
    if sd_path.exists():  # partial re-exports must not clobber other stages' spawn data
        with contextlib.suppress(OSError, ValueError):
            merged = json.loads(sd_path.read_text(encoding="utf-8"))
            merged.update(stage_data)
            stage_data = merged
    sd_path.write_text(json.dumps(stage_data), encoding="utf-8")
    # door landings (partial re-exports merge, like stage_data)
    dt_path = out_dir / "door_targets.json"
    landings: dict[str, dict] = {}
    if dt_path.exists():
        with contextlib.suppress(OSError, ValueError):
            for t in json.loads(dt_path.read_text(encoding="utf-8")):
                landings[f"{t['stage']}|{t['room']}|{t['spawn']}"] = t
    for key, t in door_targets.items():
        landings[f"{key[0]}|{key[1]}|{key[2]}"] = t
    dt_path.write_text(json.dumps(list(landings.values())), encoding="utf-8")
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
    (out_dir / "project.godot").write_text(
        _project_godot(title, main, renderer, physical_on), encoding="utf-8"
    )
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
