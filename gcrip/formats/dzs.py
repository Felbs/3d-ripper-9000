"""DZR / DZS stage placement files (Wind Waker; Twilight Princess uses the same family).

A file is a chunk table: u32 count, then count * { fourcc, u32 entries, u32 offset }.
Chunks we place from (layouts verified against the real game files and matching the
game's own d_stage.cpp readers):

  ACTR / TGOB / TRES / PLYR (0x20):  name[8] params:u32 pos:3f rot:3h enemy_no:u16
  SCOB / TGSC / DOOR / TGDR (0x24):  ...same + scale x,y,z:u8 pad (scale is value/10)
  MULT (0x0C): trans_x:f trans_z:f rot_y:u16 room_no:u8 wave_max:s8

Layer variants ACT0..ACTb / SCO0..SCOb / TRE0..TREb hold the same layout; the digit is
the hex layer number (conditional spawns tied to story flags). Actor rotations use the
game's s16 angle units (0x8000 = 180 degrees); only rot_y is a real rotation - x/z often
carry extra parameters. Actor positions are world-space; MULT moves only room geometry.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

_ACTOR_CHUNKS = {"ACTR", "TGOB", "TRES", "PLYR"}
_SCALED_CHUNKS = {"SCOB", "TGSC", "DOOR", "TGDR"}
_LAYERED = {"ACT": "ACTR", "SCO": "SCOB", "TRE": "TRES"}


@dataclass
class Placement:
    chunk: str  # canonical chunk name (ACTR/SCOB/TRES/...)
    layer: int  # -1 = default layer, 0..11 = conditional layer
    name: str
    params: int
    pos: tuple[float, float, float]
    rot: tuple[int, int, int]  # s16 angle units
    enemy_no: int
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @property
    def rot_y_deg(self) -> float:
        return self.rot[1] * 180.0 / 0x8000


@dataclass
class RoomTransform:  # MULT entry
    trans_x: float
    trans_z: float
    rot_y: int  # s16 angle units
    room_no: int
    wave_max: int

    @property
    def rot_y_deg(self) -> float:
        return self.rot_y * 180.0 / 0x8000


@dataclass
class Exit:  # SCLS entry: where a door/exit leads
    dest_stage: str
    spawn: int
    room: int
    fade: int


@dataclass
@dataclass
class ShipPoint:  # SHIP entry: where the King of Red Lions can be moored (sea rooms)
    pos: tuple[float, float, float]
    rot_y: int
    ship_id: int

    @property
    def rot_y_deg(self) -> float:
        return self.rot_y * 180.0 / 0x8000


@dataclass
class RoomSet:
    """One RTBL entry: which rooms are resident while Link stands on this collision group."""

    rooms: list[int]        # room indices, byte & 0x3F
    with_bg: list[bool]     # byte & 0x80 - load with BG collision and its dzr actors
    reverb: int             # reverbAndFlags & 0x7F
    time_pass: int          # timePassField & 0x03


@dataclass
class CameraRegion:
    """One CAMR (stage) or RCAM (room) entry: which camera type a region switches to."""

    cam_type: str          # strcmp'd against dCamera_c::types[].name; "Keep" = no change
    arrow_idx: int         # into the AROB/RARO table; >= that table's length means "none"
    unknown_11: int        # no reader in the decomp
    fov_deg: int           # 0xFF = use the style's own field of view
    transition_frames: int  # 0xFF = derive it from the distance moved


@dataclass
class CameraArrow:
    """One AROB (stage) or RARO (room) entry: a fixed eye point and orientation."""

    pos: tuple[float, float, float]
    pitch: int             # angle.x - NEGATED where the engine uses it
    yaw: int               # angle.y
    roll: int              # angle.z - unused by every camera engine
    unknown_12: int        # no reader in the decomp

    @property
    def yaw_deg(self) -> float:
        return self.yaw * 180.0 / 0x8000

    @property
    def pitch_deg(self) -> float:
        return self.pitch * 180.0 / 0x8000


@dataclass
class Dzs:
    chunks: dict[str, tuple[int, int]] = field(default_factory=dict)  # fourcc -> (n, offset)
    placements: list[Placement] = field(default_factory=list)
    mult: dict[int, RoomTransform] = field(default_factory=dict)  # room_no -> transform
    scls: list[Exit] = field(default_factory=list)  # exit table (doors index into it)
    ships: list[ShipPoint] = field(default_factory=list)  # SHIP: boat mooring points
    events: list[str] = field(default_factory=list)  # EVNT: event names tag actors index into
    room_sets: list[RoomSet] = field(default_factory=list)  # RTBL: the streaming table
    cameras: list[CameraRegion] = field(default_factory=list)  # CAMR (stage) / RCAM (room)
    cam_arrows: list[CameraArrow] = field(default_factory=list)  # AROB (stage) / RARO (room)


def _canonical(fourcc: str) -> tuple[str, int]:
    """('ACT5', ...) -> ('ACTR', 5); plain chunks -> (name, -1)."""
    prefix, last = fourcc[:3], fourcc[3]
    if prefix in _LAYERED and last in "0123456789ab":
        return _LAYERED[prefix], int(last, 16)
    return fourcc, -1


def parse(data: bytes) -> Dzs:
    out = Dzs()
    (count,) = struct.unpack_from(">I", data, 0)
    for i in range(count):
        cc, n, off = struct.unpack_from(">4sII", data, 4 + i * 12)
        fourcc = cc.decode("latin-1")
        out.chunks[fourcc] = (n, off)
        name, layer = _canonical(fourcc)
        if name in _ACTOR_CHUNKS or name in _SCALED_CHUNKS:
            scaled = name in _SCALED_CHUNKS
            size = 0x24 if scaled else 0x20
            for k in range(n):
                base = off + k * size
                nm = data[base : base + 8].split(b"\0")[0].decode("latin-1", "replace")
                params, x, y, z, rx, ry, rz, enemy = struct.unpack_from(
                    ">I3f3hH", data, base + 8
                )
                scale = (1.0, 1.0, 1.0)
                if scaled:
                    sx, sy, sz = data[base + 0x20 : base + 0x23]
                    scale = (sx / 10.0, sy / 10.0, sz / 10.0)
                out.placements.append(
                    Placement(name, layer, nm, params, (x, y, z), (rx, ry, rz), enemy, scale)
                )
        elif fourcc == "MULT":
            for k in range(n):
                tx, tz, ry, room, wave = struct.unpack_from(">ffHBb", data, off + k * 12)
                ry = ry - 0x10000 if ry >= 0x8000 else ry
                out.mult[room] = RoomTransform(tx, tz, ry, room, wave)
        elif fourcc == "EVNT":
            for k in range(n):
                base = off + k * 0x18
                # char mName[15] starts at +1 (d_stage.h's 0x04 is the padded runtime struct)
                nm = data[base + 1 : base + 16].split(b"\0")[0].decode("latin-1", "replace")
                out.events.append(nm)
        elif fourcc == "SHIP":
            for k in range(n):
                x, y, z, ry, sid = struct.unpack_from(">3fHB", data, off + k * 0x10)
                ry = ry - 0x10000 if ry >= 0x8000 else ry
                out.ships.append(ShipPoint((x, y, z), ry, sid))
        elif fourcc == "RTBL":
            # one indirection deeper than every other chunk: `off` points at an array of u32
            # file offsets, one per entry, and each entry then points at its own room bytes
            # (d_stage.h:215-226, relocation at d_stage.cpp:1732-1743)
            for k in range(n):
                (ent,) = struct.unpack_from(">I", data, off + k * 4)
                cnt, rev, tp, _pad, rooms_off = struct.unpack_from(">4BI", data, ent)
                raw = data[rooms_off : rooms_off + cnt]
                out.room_sets.append(
                    RoomSet(
                        [b & 0x3F for b in raw],
                        [bool(b & 0x80) for b in raw],
                        rev & 0x7F,
                        tp & 0x03,
                    )
                )
        elif fourcc in ("CAMR", "RCAM"):
            for k in range(n):
                base = off + k * 0x14
                ct = data[base : base + 16].split(b"\0")[0].decode("latin-1", "replace")
                arrow, f11, f12, f13 = struct.unpack_from(">4B", data, base + 16)
                out.cameras.append(CameraRegion(ct, arrow, f11, f12, f13))
        elif fourcc in ("AROB", "RARO"):
            for k in range(n):
                base = off + k * 0x14
                x, y, z, ax, ay, az, f12 = struct.unpack_from(">3f4h", data, base)
                out.cam_arrows.append(CameraArrow((x, y, z), ax, ay, az, f12))
        elif fourcc == "SCLS":
            for k in range(n):
                base = off + k * 0x0C
                dest = data[base : base + 8].split(b"\0")[0].decode("latin-1", "replace")
                spawn, room, fade = struct.unpack_from(">3B", data, base + 8)
                out.scls.append(Exit(dest, spawn, room, fade))
    return out
