"""Animations, and the rest pose that makes a rig usable.

A Zelda skeleton stores only limb *offsets*.  Every joint rotation lives in animation data, so
a model built straight from the skeleton has all its chains extended along one axis - arms
several times longer than the torso.  Frame 0 of an actor's animation is the pose the model
was authored in, and applying it is the difference between a heap and a character.

``AnimationHeader`` (16 bytes, big-endian)::

    s16 frameCount; s16 pad; u32 frameData; u32 jointIndices; s16 staticIndexMax; s16 pad

``jointIndices`` points at ``limbCount + 1`` ``JointIndex`` records of three ``u16`` - the
first is the root *translation*, the rest are per-limb *rotations*.  Each index selects into
``frameData``: below ``staticIndexMax`` the value is constant for the whole animation, at or
above it the track is ``frameData[index + frame]``.  That is the compression - a limb that
never moves costs three shorts.

Rotations are ``u16`` binary angles (65,536 = a full turn).

**The rotation order is not settled.**  The scoping run's statistical oracle scored
deliberately corrupted frames as well as good ones, so it proved nothing, and the decisive
route - disassembling the matrix routine - has not been taken.  So the order is a parameter
here, defaulting to ZYX, and :func:`pose_matrices` is written so a caller can render both and
choose by eye.  Nothing downstream should treat the default as established fact.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

HEADER = struct.Struct(">hhIIhh")
HEADER_SIZE = 16
JOINT_INDEX = struct.Struct(">3H")
JOINT_INDEX_SIZE = 6
BINANG = 2.0 * np.pi / 65536.0
MAX_FRAMES = 2048


@dataclass
class Animation:
    offset: int
    frames: int
    frame_data: int  # segmented address
    joint_indices: int  # segmented address
    static_max: int

    def __repr__(self) -> str:  # keeps scan output readable
        return f"Animation(@{self.offset:#x}, {self.frames} frames)"


def read_animation(data: bytes, offset: int, segment: int = 6) -> Animation | None:
    """Read an animation header, or None if this is not one."""
    if offset + HEADER_SIZE > len(data):
        return None
    frames, pad, frame_data, joint_indices, static_max, _pad2 = HEADER.unpack_from(data, offset)
    if not 1 <= frames <= MAX_FRAMES or pad != 0:
        return None
    if (frame_data >> 24) & 0x0F != segment or (joint_indices >> 24) & 0x0F != segment:
        return None
    if static_max < 0:
        return None
    if (frame_data & 0xFFFFFF) >= len(data) or (joint_indices & 0xFFFFFF) >= len(data):
        return None
    return Animation(offset, frames, frame_data, joint_indices, static_max)


def find_animations(data: bytes, segment: int = 6) -> list[Animation]:
    """Every animation header in a file, found by validating what it points at."""
    out: list[Animation] = []
    n = (len(data) - HEADER_SIZE) // 4 * 4
    if n <= 0:
        return out
    buf = np.frombuffer(data[: n + HEADER_SIZE], dtype=np.uint8)
    off = np.arange(0, n, 4)
    # frameCount is a small positive s16, so its high byte is 0; pad is zero; both pointers
    # start with the segment number
    ok = buf[off] == 0
    ok &= buf[off + 2] == 0
    ok &= buf[off + 3] == 0
    ok &= buf[off + 4] == segment
    ok &= buf[off + 8] == segment
    for o in off[ok]:
        a = read_animation(data, int(o), segment)
        if a is not None:
            out.append(a)
    return out


def frame_values(
    data: bytes, anim: Animation, limb_count: int, frame: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """(root translation xyz, per-limb rotations as radians) for one frame.

    Returns rotations shaped ``(limb_count, 3)``.  A track whose index sits below
    ``staticIndexMax`` is constant; the rest advance one short per frame.
    """
    fd = anim.frame_data & 0xFFFFFF
    ji = anim.joint_indices & 0xFFFFFF
    frame = max(0, min(frame, anim.frames - 1))

    def value(index: int) -> int:
        pos = fd + 2 * (index if index < anim.static_max else index + frame)
        if pos + 2 > len(data):
            return 0
        return struct.unpack_from(">H", data, pos)[0]

    def signed(index: int) -> int:
        pos = fd + 2 * (index if index < anim.static_max else index + frame)
        if pos + 2 > len(data):
            return 0
        return struct.unpack_from(">h", data, pos)[0]

    if ji + (limb_count + 1) * JOINT_INDEX_SIZE > len(data):
        return np.zeros(3), np.zeros((limb_count, 3))

    ix, iy, iz = JOINT_INDEX.unpack_from(data, ji)
    root = np.array([signed(ix), signed(iy), signed(iz)], dtype=np.float64)

    rots = np.zeros((limb_count, 3), dtype=np.float64)
    for i in range(limb_count):
        ix, iy, iz = JOINT_INDEX.unpack_from(data, ji + (i + 1) * JOINT_INDEX_SIZE)
        rots[i] = (value(ix) * BINANG, value(iy) * BINANG, value(iz) * BINANG)
    return root, rots


def _rot(axis: str, a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    m = np.eye(4)
    if axis == "x":
        m[1:3, 1:3] = [[c, -s], [s, c]]
    elif axis == "y":
        m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    else:
        m[0:2, 0:2] = [[c, -s], [s, c]]
    return m


def rotation_matrix(xyz: np.ndarray, order: str = "zyx") -> np.ndarray:
    """A limb rotation.  *order* names the order the game multiplies the axes in - which is
    NOT established for these ROMs, so it is a parameter rather than a constant."""
    m = np.eye(4)
    for axis in order:
        m = m @ _rot(axis, xyz["xyz".index(axis)])
    return m


def pose_matrices(
    skel,
    rotations: np.ndarray | None,
    root_translation: np.ndarray | None = None,
    order: str = "zyx",
) -> dict[int, np.ndarray]:
    """World matrix per limb: the skeleton's offsets composed with a frame's rotations.

    With *rotations* None this is the un-posed rig - offsets only - which is what produces
    arms several times longer than the torso, because each offset is applied in an unrotated
    frame instead of its parent's rotated one.
    """
    world: dict[int, np.ndarray] = {}
    for i in skel.order():
        limb = skel.limbs[i]
        local = np.eye(4)
        local[:3, 3] = limb.translation
        if i == 0 and root_translation is not None:
            local[:3, 3] = np.asarray(root_translation, dtype=np.float64)
        if rotations is not None and i < len(rotations):
            local = local @ rotation_matrix(rotations[i], order)
        parent = world.get(limb.parent) if limb.parent is not None else None
        world[i] = local if parent is None else parent @ local
    return world
