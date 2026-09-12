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

**The rotation order is ZYX**, and it is read out of the game rather than guessed.
``Matrix_TranslateRotateZYX`` sits at VRAM ``0x800AAA4C`` - that is ``code``, ROM file index
27, VRAM base ``0x80010EE0``, file offset ``0x99B6C``.  It folds the translation into its first
block (``col3 += col0*tx + col1*ty + col2*tz``) and then right-multiplies Rz (``lh 4($a1)``),
Ry (``lh 2($a1)``, skipped by a ``beql`` when zero) and Rx (``lh 0($a1)``), so

    M_new = M_parent * T * Rz * Ry * Rx

with ``Math_SinS`` at ``0x80063364`` and ``Math_CosS`` at ``0x80063324`` (= ``sins(a + 0x4000)``)
pinning the signs.  ``SkelAnime_DrawLimb`` at ``0x80088B40`` is the caller and passes the limb's
own ``s16 jointPos`` and the animation's 6-byte ``Vec3s``.  All three axis blocks match
:func:`_rot` term for term, disassembled independently twice.

Rendering agrees: object 163 comes out a correctly standing Zora under ``zyx`` and garbage
under ``xyz``, ``xzy`` and ``yxz``.  ``zxy`` and ``yzx`` also look right on that model, because
a rig whose limbs rotate about one axis each cannot tell the orders apart - judge the order
only on a rig with many multi-axis limbs (Link, 12 of 21; object 163, 11 of 16; object 193,
14 of 26), never on the 38-limb townsfolk, where only 6 of 38 limbs use two axes and all six
orders render identically.

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

#: ``link_animetion`` stores Link's frames as a flat array with no header: three shorts of
#: root translation then one binang triple per limb.  Frame 0 is his standing pose - its
#: translation is byte-identical to limb 0's own offset, which is how the layout was
#: confirmed against this ROM rather than assumed.
LINK_STRIDE = 67


def link_frame(raw: bytes, limb_count: int, frame: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """(root translation, per-limb rotations) from ``link_animetion``.

    Link keeps no animations in his object file; they live in their own uncompressed file,
    which is why posing him needs a separate path from every other actor.
    """
    off = frame * LINK_STRIDE * 2
    if off + LINK_STRIDE * 2 > len(raw):
        return np.zeros(3), np.zeros((limb_count, 3))
    signed = np.frombuffer(raw, ">h", LINK_STRIDE, off)
    unsigned = np.frombuffer(raw, ">H", LINK_STRIDE, off)
    root = signed[:3].astype(np.float64)
    want = limb_count * 3
    vals = unsigned[3 : 3 + want].astype(np.float64)
    if len(vals) < want:
        vals = np.pad(vals, (0, want - len(vals)))
    return root, (vals * BINANG).reshape(limb_count, 3)


def stands_up(unposed: np.ndarray, posed: np.ndarray) -> bool:
    """Did the pose make the model taller than it is wide?

    A standing character is tallest in Y.  An actor authored with its limbs strung along one
    axis is not, and applying the right frame flips that - Link goes from 45.9 x 23.3 x 21.8
    to 33.4 x 62.2 x 21.2.  A cheap, honest gate on whether a pose helped, used instead of
    trusting that any given animation is the rest pose.
    """
    return float(posed[1]) > float(unposed[1]) and float(posed[1]) >= float(posed.max()) * 0.95


# -- clips: whole animations, not just frame 0 ---------------------------------------------

#: the game advances animations at 20 frames a second
FPS = 20.0
LINK_FRAME_BYTES = LINK_STRIDE * 2


def plausible(data: bytes, anim: Animation, limb_count: int) -> bool:
    """Does this header's data actually fit the file for a rig of *limb_count* limbs?

    :func:`read_animation` checks only the first pad, the two segment bytes and a non-negative
    ``staticIndexMax``, which a run of ``0x0600xxxx`` limb pointers satisfies - object 393's
    "third animation" was exactly that, and it collapsed the figure into a lump.  For a clip
    the joint-index block must lie in the file and every animated track must have *frames*
    shorts of room after its index.
    """
    fd = anim.frame_data & 0xFFFFFF
    ji = anim.joint_indices & 0xFFFFFF
    need = (limb_count + 1) * JOINT_INDEX_SIZE
    if ji + need > len(data):
        return False
    idx = np.frombuffer(data, dtype=">u2", count=(limb_count + 1) * 3, offset=ji)
    animated = idx[idx >= anim.static_max]
    top = int(idx.max()) if len(idx) else 0
    if animated.size:
        top = max(top, int(animated.max()) + anim.frames - 1)
    return fd + 2 * (top + 1) <= len(data)


def quaternion(xyz, order: str = "zyx") -> tuple[float, float, float, float]:
    """``(x, y, z, w)`` for a limb rotation, matching :func:`rotation_matrix`."""
    m = rotation_matrix(np.asarray(xyz, dtype=np.float64), order)[:3, :3]
    tr = m.trace()
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    return float(x), float(y), float(z), float(w)


def _clip_from_frames(name: str, frames, scale: float, root_offset, order: str = "zyx"):
    """Build a Clip from an iterable of (root translation, per-limb rotations) frames.

    Joint 0's translation is the animation's root translation - the same substitution
    :func:`pose_matrices` makes - so a walk cycle actually walks.
    """
    from ripcore.scene import Clip

    roots, rots = [], []
    for root, r in frames:
        roots.append(root)
        rots.append(r)
    if not rots:
        return None
    rots = np.stack(rots)                       # (F, limbs, 3)
    roots = np.stack(roots) * scale             # (F, 3)
    clip = Clip(name=name, frames=len(rots), fps=FPS)
    clip.translation[0] = roots.astype(np.float32)
    for j in range(rots.shape[1]):
        clip.rotation[j] = np.array([quaternion(rots[f, j], order) for f in range(len(rots))],
                                    dtype=np.float32)
    return clip


def clip(data: bytes, anim: Animation, limb_count: int, name: str, scale: float = 1.0):
    """One object-file animation as a Clip, or None if it does not fit the rig."""
    if not plausible(data, anim, limb_count):
        return None
    return _clip_from_frames(
        name, (frame_values(data, anim, limb_count, f) for f in range(anim.frames)),
        scale, None,
    )


@dataclass(frozen=True)
class LinkAnimation:
    index: int      # record number; its segment-4 address on Ocarina is 0x04002310 + 8*index
    offset: int     # byte offset of the 8-byte header inside gameplay_keep
    frames: int
    start: int      # byte offset of frame 0 inside link_animetion


LINK_DATA_SEGMENT = 7


def find_link_animations(keep: bytes, link_size: int) -> list[LinkAnimation]:
    """Link's animation headers - in **gameplay_keep** (object 1), not in ``code``.

    ``link_animetion`` is a bare run of frames; the headers that cut it into animations are
    573 eight-byte ``{s16 frameCount; s16 0; u32 0x07000000 | byteOffset}`` records at
    ``keep+0x2310..0x34F8``, addressed by the game as segment-4 pointers.  Read by
    ``LinkAnimation_Load`` (code VRAM 0x8008B23C: ``lw 4(hdr)``, then VROM 0x556000 + offset +
    frame*134 through the DMA manager - the only construction of 0x556000 in ``code``) and
    ``Animation_GetLength`` (0x80089EC0: ``lh 0(hdr)``).  Segment 7 is never bound; the frames
    are DMA'd one at a time.

    The offsets are all 16-aligned and, sorted, tile the file exactly: ``next_start ==
    align16(start + frames*134)`` for all 572 adjacent pairs, 18,733 frames, 3,744 bytes of
    zero padding, 2 tail bytes.  So "18,760 frames of 134 bytes" was a division artefact - a
    global 134-byte grid is valid only inside the clip at byte 0.

    An earlier finder looked in ``code`` and found a 1,391-record run at code+0xFD0EC whose
    second words are also ``0x07xxxxxx``: that is the game's MESSAGE table (segment 7 there
    is ``nes_message_data_static``), and its first halfword counts up because it is a text id.
    """
    def rec(off):
        if off + 8 > len(keep):
            return None
        frames, pad, seg = struct.unpack_from(">hhI", keep, off)
        if pad or frames < 1 or (seg >> 24) != LINK_DATA_SEGMENT:
            return None
        start = seg & 0xFFFFFF
        if start % 16 or start + frames * LINK_FRAME_BYTES > link_size:
            return None
        return frames, start

    best: list[LinkAnimation] = []
    off = 0
    while off + 8 <= len(keep):
        r = rec(off)
        if r is None:
            off += 4
            continue
        run, k = [], off
        while (r := rec(k)) is not None:
            run.append(LinkAnimation(len(run), k, r[0], r[1]))
            k += 8
        if len(run) > len(best):
            best = run
        off = k + 4
    return best


def link_clip(raw: bytes, start: int, frames: int, limb_count: int, name: str,
              scale: float = 1.0):
    """One of Link's animations as a Clip: *frames* consecutive frames from byte *start*."""
    def gen():
        for f in range(frames):
            off = start + f * LINK_FRAME_BYTES
            if off + LINK_FRAME_BYTES > len(raw):
                return
            signed = np.frombuffer(raw, ">h", LINK_STRIDE, off)
            unsigned = np.frombuffer(raw, ">H", LINK_STRIDE, off)
            want = limb_count * 3
            vals = unsigned[3:3 + want].astype(np.float64)
            if len(vals) < want:
                vals = np.pad(vals, (0, want - len(vals)))
            yield signed[:3].astype(np.float64), (vals * BINANG).reshape(limb_count, 3)
    return _clip_from_frames(name, gen(), scale, None)
