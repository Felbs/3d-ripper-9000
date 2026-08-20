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
class Dzs:
    chunks: dict[str, tuple[int, int]] = field(default_factory=dict)  # fourcc -> (n, offset)
    placements: list[Placement] = field(default_factory=list)
    mult: dict[int, RoomTransform] = field(default_factory=dict)  # room_no -> transform


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
    return out
