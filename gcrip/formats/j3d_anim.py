"""J3D animation files.

BCK (``J3D1bck1`` / ANK1) - joint (skeletal) animation. Per joint, per axis, three
keyframe tracks (scale, rotation, translation). Keys are hermite splines with
tangents expressed in units per frame. Rotations are s16 scaled by
``(1 << rotation_shift) * 180 / 32768`` degrees.

BTP (``J3D1btp1`` / TPT1) - texture pattern animation: per material, per frame,
which TEX1 texture index sits in a given texture slot. This is how facial
expressions work in J3D games (eyes/mouth textures swapped per frame).

BVA (``J3D1bva1`` / VAF1) - per-shape visibility per frame.

Layouts follow the community documentation of the J3D formats
(noclip.website, SuperBMD, wiki.cloudmodding.com) and were verified against
Wind Waker / Twilight Princess files.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats.j3d import J3DError, _read_string_table

LOOP_ONCE = 0
LOOP_ONCE_RESET = 1
LOOP_REPEAT = 2
LOOP_MIRROR_ONCE = 3
LOOP_MIRROR_REPEAT = 4
LOOP_NAMES = {0: "once", 1: "once_reset", 2: "loop", 3: "mirror_once", 4: "mirror_loop"}


@dataclass
class Track:
    """Keyframes as an (N, 4) float array: frame time, value, in-tangent, out-tangent."""

    keys: np.ndarray

    @property
    def constant(self) -> bool:
        return len(self.keys) <= 1 or bool(np.allclose(self.keys[:, 1], self.keys[0, 1]))

    def sample(self, t: float) -> float:
        k = self.keys
        n = len(k)
        if n == 0:
            return 0.0
        if n == 1 or t <= k[0, 0]:
            return float(k[0, 1])
        if t >= k[-1, 0]:
            return float(k[-1, 1])
        i = int(np.searchsorted(k[:, 0], t, side="right")) - 1
        i = max(0, min(i, n - 2))
        t0, v0, _, out0 = k[i]
        t1, v1, in1, _ = k[i + 1]
        dur = t1 - t0
        if dur <= 0:
            return float(v1)
        s = (t - t0) / dur
        return float(_hermite(s, v0, v1, out0 * dur, in1 * dur))

    def sample_frames(self, frames: np.ndarray) -> np.ndarray:
        """Vectorised hermite sampling at many frame times."""
        k = self.keys
        n = len(k)
        f = np.asarray(frames, dtype=np.float64)
        if n == 0:
            return np.zeros(len(f), np.float32)
        if n == 1:
            return np.full(len(f), k[0, 1], np.float32)
        i = np.searchsorted(k[:, 0], f, side="right") - 1
        i = np.clip(i, 0, n - 2)
        t0, v0, out0 = k[i, 0], k[i, 1], k[i, 3]
        t1, v1, in1 = k[i + 1, 0], k[i + 1, 1], k[i + 1, 2]
        dur = t1 - t0
        safe = np.where(dur > 0, dur, 1.0)
        s = np.clip((f - t0) / safe, 0.0, 1.0)
        s2, s3 = s * s, s * s * s
        val = (
            (2 * s3 - 3 * s2 + 1) * v0
            + (s3 - 2 * s2 + s) * out0 * dur
            + (-2 * s3 + 3 * s2) * v1
            + (s3 - s2) * in1 * dur
        )
        val = np.where(f <= k[0, 0], k[0, 1], val)
        val = np.where(f >= k[-1, 0], k[-1, 1], val)
        return val.astype(np.float32)


def _hermite(s: float, p0: float, p1: float, m0: float, m1: float) -> float:
    s2 = s * s
    s3 = s2 * s
    return (
        (2 * s3 - 3 * s2 + 1) * p0
        + (s3 - 2 * s2 + s) * m0
        + (-2 * s3 + 3 * s2) * p1
        + (s3 - s2) * m1
    )


@dataclass
class JointAnim:
    scale: list[Track]  # x, y, z
    rotation: list[Track]  # x, y, z, degrees
    translation: list[Track]  # x, y, z

    def animated(self) -> bool:
        return any(not t.constant for t in self.scale + self.rotation + self.translation)


@dataclass
class Bck:
    name: str
    loop_mode: int
    duration: int  # frames
    joints: list[JointAnim]

    @property
    def joint_count(self) -> int:
        return len(self.joints)

    @property
    def loops(self) -> bool:
        return self.loop_mode in (LOOP_REPEAT, LOOP_MIRROR_REPEAT)


def _read_track(
    data: bytes,
    entry_off: int,
    values: np.ndarray,
    value_scale: float,
) -> Track:
    count, index, tangent_type = struct.unpack_from(">HHH", data, entry_off)
    if count == 0:
        return Track(np.zeros((0, 4), np.float64))
    if count == 1:
        v = float(values[index]) * value_scale
        return Track(np.array([[0.0, v, 0.0, 0.0]], np.float64))
    stride = 4 if tangent_type == 1 else 3
    end = index + count * stride
    if end > len(values):
        raise J3DError("animation track runs past its data table")
    raw = values[index:end].astype(np.float64).reshape(count, stride)
    keys = np.zeros((count, 4), np.float64)
    keys[:, 0] = raw[:, 0]
    keys[:, 1] = raw[:, 1] * value_scale
    keys[:, 2] = raw[:, 2] * value_scale
    keys[:, 3] = (raw[:, 3] if stride == 4 else raw[:, 2]) * value_scale
    return Track(keys)


def parse_bck(data: bytes, name: str = "") -> Bck:
    if data[:8] != b"J3D1bck1":
        raise J3DError("not a BCK file")
    off = 0x20
    if data[off : off + 4] != b"ANK1":
        raise J3DError("BCK missing ANK1 section")
    (
        _size,
        loop_mode,
        rot_shift,
        duration,
        joint_count,
        scale_count,
        rot_count,
        trans_count,
        joint_off,
        scale_off,
        rot_off,
        trans_off,
    ) = struct.unpack_from(">IBBHHHHHIIII", data, off + 4)
    scales = np.frombuffer(data, ">f4", scale_count, off + scale_off)
    rots = np.frombuffer(data, ">i2", rot_count, off + rot_off)
    trans = np.frombuffer(data, ">f4", trans_count, off + trans_off)
    rot_scale = float(1 << rot_shift) * 180.0 / 32768.0
    joints = []
    p = off + joint_off
    for _ in range(joint_count):
        sc, ro, tr = [], [], []
        for _axis in range(3):
            sc.append(_read_track(data, p, scales, 1.0))
            ro.append(_read_track(data, p + 6, rots, rot_scale))
            tr.append(_read_track(data, p + 12, trans, 1.0))
            p += 18
        joints.append(JointAnim(sc, ro, tr))
    return Bck(name, loop_mode, duration, joints)


# ---------------------------------------------------------------- BTP


@dataclass
class BtpTrack:
    material: str
    tex_slot: int
    frames: np.ndarray  # texture index per frame (len == duration, or 1 if constant)

    def at(self, frame: int) -> int:
        if len(self.frames) == 0:
            return -1
        return int(self.frames[min(frame, len(self.frames) - 1)])


@dataclass
class Btp:
    name: str
    loop_mode: int
    duration: int
    tracks: list[BtpTrack] = field(default_factory=list)

    @property
    def material_names(self) -> list[str]:
        return [t.material for t in self.tracks]

    def states(self) -> list[tuple[int, tuple[tuple[str, int, int], ...]]]:
        """Distinct texture assignments over the animation, in first-appearance order:
        [(first frame, ((material, slot, texture index), ...)), ...]."""
        seen: dict[tuple, int] = {}
        out = []
        for f in range(max(1, self.duration)):
            key = tuple((t.material, t.tex_slot, t.at(f)) for t in self.tracks)
            if key not in seen:
                seen[key] = f
                out.append((f, key))
        return out


def parse_btp(data: bytes, name: str = "") -> Btp:
    if data[:8] != b"J3D1btp1":
        raise J3DError("not a BTP file")
    off = 0x20
    if data[off : off + 4] != b"TPT1":
        raise J3DError("BTP missing TPT1 section")
    (
        _size,
        loop_mode,
        _pad,
        duration,
        mat_count,
        index_count,
        anim_off,
        index_off,
        _remap_off,
        name_off,
    ) = struct.unpack_from(">IBBHHHIIII", data, off + 4)
    indices = np.frombuffer(data, ">u2", index_count, off + index_off)
    names = _read_string_table(data, off + name_off) if name_off else []
    tracks = []
    for i in range(mat_count):
        count, first, slot = struct.unpack_from(">HHB", data, off + anim_off + i * 8)
        frames = indices[first : first + count].astype(np.int32)
        mat_name = names[i] if i < len(names) else f"material{i}"
        tracks.append(BtpTrack(mat_name, slot, frames))
    return Btp(name, loop_mode, duration, tracks)


# ---------------------------------------------------------------- BVA


@dataclass
class Bva:
    name: str
    loop_mode: int
    duration: int
    shapes: list[np.ndarray]  # per shape: visibility per frame (bool)

    def visible(self, shape: int, frame: int) -> bool:
        v = self.shapes[shape]
        if len(v) == 0:
            return True
        return bool(v[min(frame, len(v) - 1)])


def parse_bva(data: bytes, name: str = "") -> Bva:
    if data[:8] != b"J3D1bva1":
        raise J3DError("not a BVA file")
    off = 0x20
    if data[off : off + 4] != b"VAF1":
        raise J3DError("BVA missing VAF1 section")
    _size, loop_mode, _pad, duration, shape_count, val_count, show_off, val_off = (
        struct.unpack_from(">IBBHHHII", data, off + 4)
    )
    values = np.frombuffer(data, ">u1", val_count, off + val_off)
    shapes = []
    for i in range(shape_count):
        count, first = struct.unpack_from(">HH", data, off + show_off + i * 4)
        shapes.append(values[first : first + count] != 0)
    return Bva(name, loop_mode, duration, shapes)


def euler_xyz_to_quat(rx: float, ry: float, rz: float) -> np.ndarray:
    """Quaternion (x, y, z, w) for R = Rz * Ry * Rx with angles in degrees."""
    hx, hy, hz = math.radians(rx) / 2, math.radians(ry) / 2, math.radians(rz) / 2
    cx, sx = math.cos(hx), math.sin(hx)
    cy, sy = math.cos(hy), math.sin(hy)
    cz, sz = math.cos(hz), math.sin(hz)
    # q = qz * qy * qx
    return np.array(
        [
            sx * cy * cz - cx * sy * sz,
            cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz,
            cx * cy * cz + sx * sy * sz,
        ],
        dtype=np.float64,
    )
