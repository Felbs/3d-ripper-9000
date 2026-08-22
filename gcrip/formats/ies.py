"""IES LM-63 photometric files -> a Godot light projector texture.

Godot 4 has no IES importer, but SpotLight3D / OmniLight3D accept `light_projector`, a 2D
texture projected through the cone.  An IES file is a table of candela values over vertical
angles (0 = straight down the beam) and horizontal angles, so baking it into a radial image -
radius = vertical angle, brightness = candela / max - reproduces the fixture's real throw:
the hot centre, the shoulder, the cut-off.

Format (IESNA LM-63-1995 / 2002):
    IESNA:LM-63-2002          header lines, keywords in [BRACKETS]
    TILT=NONE
    <lamps> <lumens/lamp> <multiplier> <n_vert> <n_horiz> <photometric_type> <units> <w> <l> <h>
    <ballast> <future> <input_watts>
    <n_vert vertical angles>
    <n_horiz horizontal angles>
    <n_horiz rows of n_vert candela values>
Type C photometry (type 1) is what almost every architectural IES is; vertical angles 0..90
or 0..180, horizontal 0 (symmetric) / 0..90 / 0..180 / 0..360.
"""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Ies:
    lumens: float
    multiplier: float
    vertical: np.ndarray  # degrees, ascending
    horizontal: np.ndarray  # degrees, ascending
    candela: np.ndarray  # (n_horiz, n_vert)
    photometric_type: int
    input_watts: float

    @property
    def max_candela(self) -> float:
        return float(self.candela.max()) if self.candela.size else 0.0

    def sample(self, vert_deg: float, horiz_deg: float) -> float:
        """Bilinear candela at an angle pair, with the file's horizontal symmetry applied."""
        h = self._fold_horizontal(horiz_deg)
        v = float(np.clip(vert_deg, self.vertical[0], self.vertical[-1]))
        vi = int(np.searchsorted(self.vertical, v, side="right") - 1)
        vi = max(0, min(vi, len(self.vertical) - 2)) if len(self.vertical) > 1 else 0
        hi = int(np.searchsorted(self.horizontal, h, side="right") - 1)
        hi = max(0, min(hi, len(self.horizontal) - 2)) if len(self.horizontal) > 1 else 0

        def lerp_v(row: np.ndarray) -> float:
            if len(self.vertical) == 1:
                return float(row[0])
            a, b = self.vertical[vi], self.vertical[vi + 1]
            t = 0.0 if b == a else (v - a) / (b - a)
            return float(row[vi] * (1 - t) + row[vi + 1] * t)

        if len(self.horizontal) == 1:
            return lerp_v(self.candela[0])
        a, b = self.horizontal[hi], self.horizontal[hi + 1]
        t = 0.0 if b == a else (h - a) / (b - a)
        return lerp_v(self.candela[hi]) * (1 - t) + lerp_v(self.candela[hi + 1]) * t

    def _fold_horizontal(self, deg: float) -> float:
        last = float(self.horizontal[-1]) if len(self.horizontal) else 0.0
        d = deg % 360.0
        if last <= 0.0:
            return 0.0
        if last <= 90.0:  # quadrant symmetry
            d = d % 180.0
            return 180.0 - d if d > 90.0 else d
        if last <= 180.0:  # bilateral symmetry
            return 360.0 - d if d > 180.0 else d
        return d

    def projector(self, size: int = 256, cone_deg: float = 90.0) -> np.ndarray:
        """(size, size) float32 in 0..1: the beam as Godot's spot projector sees it -
        image centre = the beam axis, image edge = `cone_deg` off-axis."""
        img = np.zeros((size, size), dtype=np.float32)
        mx = self.max_candela
        if mx <= 0.0:
            return img
        c = (size - 1) / 2.0
        for y in range(size):
            for x in range(size):
                dx, dy = (x - c) / c, (y - c) / c
                r = math.hypot(dx, dy)
                if r > 1.0:
                    continue
                vert = r * cone_deg
                horiz = math.degrees(math.atan2(dy, dx))
                img[y, x] = self.sample(vert, horiz) / mx
        return img


def parse(text: str) -> Ies:
    lines = [ln.strip() for ln in text.splitlines()]
    i = 0
    while i < len(lines) and not lines[i].upper().startswith("TILT="):
        i += 1
    if i >= len(lines):
        raise ValueError("no TILT= line: not an IES LM-63 file")
    tilt = lines[i].split("=", 1)[1].strip().upper()
    i += 1
    if tilt == "INCLUDE":
        # tilt block: lamp-to-luminaire geometry, N pairs of angles and factors - skip it
        n = int(lines[i + 1].split()[0])
        i += 2
        consumed = 0
        while consumed < 2 * n and i < len(lines):
            consumed += len(lines[i].split())
            i += 1
    nums: list[float] = []
    for ln in lines[i:]:
        for tok in ln.replace(",", " ").split():
            with contextlib.suppress(ValueError):
                nums.append(float(tok))
    if len(nums) < 13:
        raise ValueError("truncated IES data block")
    _lamps, lumens, mult, n_v, n_h, ptype, _units, _w, _l, _h = nums[:10]
    _ballast, _future, watts = nums[10:13]
    n_v, n_h = int(n_v), int(n_h)
    pos = 13
    vert = np.array(nums[pos : pos + n_v], dtype=np.float64)
    pos += n_v
    horiz = np.array(nums[pos : pos + n_h], dtype=np.float64)
    pos += n_h
    need = n_v * n_h
    cand = np.array(nums[pos : pos + need], dtype=np.float64)
    if cand.size != need:
        raise ValueError(f"expected {need} candela values, got {cand.size}")
    cand = cand.reshape(n_h, n_v) * (mult if mult > 0 else 1.0)
    return Ies(lumens, mult, vert, horiz, cand, int(ptype), watts)
