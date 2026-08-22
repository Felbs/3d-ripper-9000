"""Radiance .hdr (RGBE) reader, plus the one analysis an HDRI-lit scene needs:
where the sun is, so the shadow-casting light can point there.

Format: a text header ending in a blank line, then `-Y h +X w`, then scanlines.  New-style
RLE scanlines start with 0x02 0x02 <w hi> <w lo> and store the four channels separately, each
run-length encoded; old-style scanlines are raw RGBE quads.  RGBE -> float:
value = mantissa * 2^(e - 128 - 8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Hdr:
    width: int
    height: int
    rgb: np.ndarray  # (h, w, 3) float32, linear radiance

    @property
    def luminance(self) -> np.ndarray:
        r, g, b = self.rgb[..., 0], self.rgb[..., 1], self.rgb[..., 2]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def sun(self) -> tuple[tuple[float, float, float], float, float]:
        """(direction xyz in Godot's frame, peak luminance, sun-to-sky ratio).

        The sun is the brightest blob; its centre is taken as the luminance-weighted mean of
        every pixel above 1% of the peak, so a few hot pixels do not decide it.  The direction
        uses the equirect convention Godot's PanoramaSky uses: u = 0.5 is -Z (forward), u grows
        toward +X... in Godot the panorama's centre column faces -Z and u increases to the
        right, so azimuth = (u - 0.5) * 2pi measured from -Z toward +X.  v = 0 is straight up.
        Returned as the direction the LIGHT travels (from the sun toward the scene).
        """
        lum = self.luminance
        peak = float(lum.max())
        if peak <= 0.0:
            return (0.0, -1.0, 0.0), 0.0, 0.0
        mask = lum >= peak * 0.01
        ys, xs = np.nonzero(mask)
        w = lum[ys, xs]
        # weight by the pixel's solid angle too: rows near the poles are oversampled
        lat = (0.5 - (ys + 0.5) / self.height) * math.pi
        w = w * np.cos(lat)
        u = float(np.sum((xs + 0.5) / self.width * w) / np.sum(w))
        v = float(np.sum((ys + 0.5) / self.height * w) / np.sum(w))
        az = (u - 0.5) * 2.0 * math.pi
        el = (0.5 - v) * math.pi
        # a point ON the sky in that direction (Godot: -Z forward, +X right, +Y up)
        sx = math.cos(el) * math.sin(az)
        sy = math.sin(el)
        sz = -math.cos(el) * math.cos(az)
        # the whole-sky average for the ratio, solid-angle weighted
        rows = np.cos((0.5 - (np.arange(self.height) + 0.5) / self.height) * math.pi)
        sky_mean = float(np.sum(lum * rows[:, None]) / (np.sum(rows) * self.width))
        ratio = peak / sky_mean if sky_mean > 0 else 0.0
        return (-sx, -sy, -sz), peak, ratio


def parse(data: bytes) -> Hdr:
    if not data.startswith(b"#?"):
        raise ValueError("not a Radiance HDR file")
    pos = data.find(b"\n\n")
    if pos < 0:
        raise ValueError("no header terminator")
    pos += 2
    end = data.find(b"\n", pos)
    res = data[pos:end].decode("latin-1").split()
    if len(res) != 4 or res[0] != "-Y" or res[2] != "+X":
        raise ValueError(f"unsupported orientation {res}")
    h, w = int(res[1]), int(res[3])
    pos = end + 1
    buf = np.frombuffer(data, dtype=np.uint8)
    out = np.empty((h, w, 4), dtype=np.uint8)
    for y in range(h):
        if (
            w >= 8
            and w < 32768
            and buf[pos] == 2
            and buf[pos + 1] == 2
            and ((int(buf[pos + 2]) << 8) | int(buf[pos + 3])) == w
        ):
            pos += 4
            for c in range(4):
                x = 0
                row = out[y, :, c]
                while x < w:
                    n = int(buf[pos])
                    pos += 1
                    if n > 128:
                        n -= 128
                        row[x : x + n] = buf[pos]
                        pos += 1
                    else:
                        row[x : x + n] = buf[pos : pos + n]
                        pos += n
                    x += n
        else:
            out[y] = buf[pos : pos + w * 4].reshape(w, 4)
            pos += w * 4
    e = out[..., 3].astype(np.int32)
    scale = np.where(e > 0, np.ldexp(1.0, e - 136), 0.0).astype(np.float32)
    rgb = out[..., :3].astype(np.float32) * scale[..., None]
    return Hdr(w, h, rgb)
