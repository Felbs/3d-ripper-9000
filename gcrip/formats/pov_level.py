"""Smashing Drive's phase layouts: the ``TG_<phase>`` ``BIN`` record of a phase ``.wad``
(``TG_FASE_11``), read next to gcrip.formats.pov_model.

No symbols cover it (Gaelco's game code on top of Point of View's engine), so the layout is
from the data.  Every pointer is a file offset; two headers::

    phase   +0 u32 0x10, +4 ptr cells, +8 ptr extras, +12 0, +16 u32 sections,
            +20 (u32 route distance, ptr placements) a section
    scene   +0 0, +4 u32 0x10, +8 ptr extras, +12 0, +16 u32 cells, +20 the cells
            (``TG_INTRO_11``, ``TG_FIN_11``, and the last phase's ``TG_FASE_41``)

    cell    f32 centre[3], f32 radius squared, ptr bounding boxes (32 bytes each: min[3],
            max[3], 0, 1.0), ptr placements
    extras  per-placement parameter blocks (behaviour, not geometry)

A placement list is a u32 count followed by 40-byte records::

    u16 kind, u16 sub, u16 model record id | flags << 14, u16 param, ptr extras,
    f32 position[3], f32 axis[3], f32 angle

The record id is the one the ``.wad`` wrapper carries in its fourth word (``(word >> 16) &
0x3fff``) - ``RemapPmxObject`` stores each loaded ``PHM`` in a table by that id.  The cells
hold the props of the scenery (lamps, containers, pedestrians); the sections hold the traffic
along the route.  The buildings and road pieces (``F11_230E``) are never placed: they sit in
world coordinates already, so the level is every model of the phase ``.wad`` nobody places,
plus the placed props.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

import numpy as np

CELL = 24
PLACEMENT = 40
HEADER = 24
TABLES = 20  # the sections (phase) or cells (scene) start here
VERSION = 0x10
ID_MASK = 0x3FFF
MAX_COUNT = 1 << 16


class PovLevelError(ValueError):
    pass


@dataclass
class Placement:
    kind: int
    sub: int
    model: int  # the wad record id
    param: int
    position: tuple[float, float, float]
    axis: tuple[float, float, float]
    angle: float

    def matrix(self) -> np.ndarray:
        """Row-vector rotation (``local @ m``) about ``axis`` by ``angle`` radians."""
        x, y, z = self.axis
        n = math.sqrt(x * x + y * y + z * z)
        if n < 1e-6:
            return np.eye(3, dtype=np.float32)
        x, y, z = x / n, y / n, z / n
        c, s = math.cos(self.angle), math.sin(self.angle)
        t = 1 - c
        r = np.array(
            [
                [t * x * x + c, t * x * y + s * z, t * x * z - s * y],
                [t * x * y - s * z, t * y * y + c, t * y * z + s * x],
                [t * x * z + s * y, t * y * z - s * x, t * z * z + c],
            ],
            dtype=np.float32,
        )
        # r is R(angle) transposed, the row-vector form; traffic faces along its route with
        # this and 20% of it points backwards with the transpose
        return r


@dataclass
class Cell:
    centre: tuple[float, float, float]
    radius: float
    placements: list[Placement]


@dataclass
class Level:
    cells: list[Cell]
    sections: list[tuple[int, list[Placement]]]  # (route distance, traffic)
    warnings: list[str]

    @property
    def placements(self) -> list[Placement]:
        out = [p for c in self.cells for p in c.placements]
        for _d, ps in self.sections:
            out += ps
        return out


def record_id(word: int) -> int:
    """The ``PHM`` id of a ``.wad`` wrapper's fourth word."""
    return (word >> 16) & ID_MASK


def is_level(head: bytes, size: int) -> bool:
    if len(head) < HEADER or size < HEADER + PLACEMENT:
        return False
    w = struct.unpack_from(">6I", head, 0)
    if w[3] != 0 or not 0 < w[4] < MAX_COUNT:
        return False
    if w[0] == VERSION:  # a phase: cells behind a pointer, the sections inline
        return TABLES < w[1] < size and w[1] < w[2] <= size and TABLES + 8 * w[4] <= w[1]
    if w[0] == 0 and w[1] == VERSION:  # a scene: the cells inline
        return TABLES + CELL * w[4] <= w[2] <= size
    return False


def _placements(b: bytes, at: int, warn: list[str]) -> list[Placement]:
    if at + 4 > len(b):
        warn.append(f"placement list at {at:#x} past the file")
        return []
    n = struct.unpack_from(">I", b, at)[0]
    out = []
    for i in range(min(n, MAX_COUNT)):
        o = at + 4 + PLACEMENT * i
        if o + PLACEMENT > len(b):
            warn.append(f"placement list at {at:#x}: {n} records, {i} fit")
            break
        kind, sub, model, param, _extra = struct.unpack_from(">4HI", b, o)
        pos = struct.unpack_from(">3f", b, o + 12)
        axis = struct.unpack_from(">3f", b, o + 24)
        angle = struct.unpack_from(">f", b, o + 36)[0]
        if not all(math.isfinite(v) for v in (*pos, *axis, angle)):
            warn.append(f"placement list at {at:#x}: record {i} is not finite")
            continue
        out.append(Placement(kind, sub, model & ID_MASK, param, pos, axis, angle))
    return out


def parse(b: bytes) -> Level:
    if not is_level(b[:HEADER], len(b)):
        raise PovLevelError("not a phase layout")
    w = struct.unpack_from(">5I", b, 0)
    warn: list[str] = []
    if w[0] == VERSION:
        ncells = struct.unpack_from(">I", b, w[1])[0]
        first = w[1] + 4
        nsections = w[4]
    else:
        ncells, first, nsections = w[4], TABLES, 0
    cells = []
    for i in range(min(ncells, MAX_COUNT)):
        o = first + CELL * i
        if o + CELL > len(b):
            warn.append(f"{ncells} cells, {i} fit")
            break
        centre = struct.unpack_from(">3f", b, o)
        r2, _pboxes, pplace = struct.unpack_from(">fII", b, o + 12)
        cells.append(Cell(centre, math.sqrt(max(r2, 0.0)), _placements(b, pplace, warn)))
    sections = []
    for i in range(nsections):
        dist, p = struct.unpack_from(">2I", b, TABLES + 8 * i)
        sections.append((dist, _placements(b, p, warn)))
    return Level(cells, sections, warn)
