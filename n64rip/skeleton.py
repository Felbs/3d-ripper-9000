"""Zelda actor skeletons: the limb hierarchy that makes a character riggable.

An actor's model is not one mesh.  It is a tree of *limbs*, each holding a translation
relative to its parent and its own display list, drawn by walking the tree with a matrix
stack.  That is why the F3DEX2 interpreter takes a starting matrix: give it the limb's world
matrix and the limb's geometry lands in the right place, and recording which limb produced
which vertices gives rigid skinning for free.

Structures, all big-endian:

``SkeletonHeader``   ``u32 limbsSegment; u8 limbCount; u8 pad[3]``  (8 bytes)
``FlexSkeletonHeader`` adds ``u8 dListCount; u8 pad[3]``            (12 bytes)
``StandardLimb``     ``s16 x, y, z; u8 child; u8 sibling; u32 dList``  (12 bytes)

``limbsSegment`` points at an array of ``limbCount`` pointers, one per limb.  ``child`` and
``sibling`` are limb indices with ``0xFF`` meaning none, which is what makes the hierarchy
recoverable without any names: the tree structure is explicit even though the limbs are
anonymous.

Anonymity is the catch for mocap.  gcrip's ``humanoid.py`` maps a rig onto Mixamo bones by
reading joint *names*, and these limbs have none, so it returns nothing.  The bone mapping
has to come from structure instead - see :func:`limb_roles`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

NO_LIMB = 0xFF
LIMB = struct.Struct(">3hBBI")
LIMB_SIZE = 12
HEADER = struct.Struct(">IB3x")
HEADER_SIZE = 8


@dataclass
class Limb:
    index: int
    x: int
    y: int
    z: int
    child: int
    sibling: int
    dlist: int
    parent: int | None = None
    #: a second display list, present on far-model (LOD) skeletons
    dlist_far: int = 0

    @property
    def translation(self) -> tuple[float, float, float]:
        return (float(self.x), float(self.y), float(self.z))


@dataclass
class Skeleton:
    offset: int  # where the header sits in its file
    limbs: list[Limb] = field(default_factory=list)
    flex: bool = False
    dlist_count: int = 0

    @property
    def count(self) -> int:
        return len(self.limbs)

    def order(self) -> list[int]:
        """Limb indices in draw order: depth-first, child before sibling.

        Implemented as the actual DFS rather than assuming index order.  On these ROMs the
        two coincide for every skeleton measured, but they are not the same thing and a
        skeleton where they diverge would silently mis-parent every limb.
        """
        out: list[int] = []
        seen = set()

        def walk(i: int) -> None:
            while i != NO_LIMB and i < len(self.limbs) and i not in seen:
                seen.add(i)
                out.append(i)
                walk(self.limbs[i].child)
                i = self.limbs[i].sibling

        walk(0)
        for i in range(len(self.limbs)):  # anything unreachable still belongs to the rig
            if i not in seen:
                out.append(i)
        return out


def _read_limb(data: bytes, off: int, index: int, lod: bool) -> Limb | None:
    stride = LIMB_SIZE + (4 if lod else 0)
    if off + stride > len(data):
        return None
    x, y, z, child, sibling, dl = LIMB.unpack_from(data, off)
    far = struct.unpack_from(">I", data, off + LIMB_SIZE)[0] if lod else 0
    return Limb(index, x, y, z, child, sibling, dl, dlist_far=far)


def read_skeleton(data: bytes, offset: int, segment: int = 6, lod: bool = False) -> Skeleton | None:
    """Read the skeleton whose header sits at *offset* in *data*, or None if it is not one."""
    if offset + HEADER_SIZE > len(data):
        return None
    limbs_addr, count = HEADER.unpack_from(data, offset)
    if not 1 <= count <= 127:
        return None
    if (limbs_addr >> 24) & 0x0F != segment:
        return None
    table = limbs_addr & 0x00FFFFFF
    if table + count * 4 > len(data):
        return None
    limbs: list[Limb] = []
    for i in range(count):
        ptr = struct.unpack_from(">I", data, table + i * 4)[0]
        if (ptr >> 24) & 0x0F != segment:
            return None
        limb = _read_limb(data, ptr & 0x00FFFFFF, i, lod)
        if limb is None:
            return None
        if limb.child != NO_LIMB and limb.child >= count:
            return None
        if limb.sibling != NO_LIMB and limb.sibling >= count:
            return None
        # limb 0 is the root, so it can never be another limb's child or sibling - a real
        # table writes 0xFF for "none".  This rejects exactly one data table in the ROM that
        # otherwise reads as a 14-limb skeleton.
        if limb.child == 0 or limb.sibling == 0:
            return None
        limbs.append(limb)
    skel = Skeleton(offset=offset, limbs=limbs)
    _assign_parents(skel)
    return skel


def _assign_parents(skel: Skeleton) -> None:
    """Every limb reachable along a child's sibling chain shares that child's parent.

    The chain needs a cycle guard: the indices come from the ROM, and a candidate that is not
    really a skeleton can have limb A's sibling point at B and B's back at A.  Without the
    guard that spins forever, which is exactly what it did - one Ocarina of Time file hung the
    whole scan for minutes before this was found.
    """
    for limb in skel.limbs:
        c = limb.child
        seen: set[int] = set()
        while c != NO_LIMB and c < len(skel.limbs) and c not in seen:
            seen.add(c)
            skel.limbs[c].parent = limb.index
            c = skel.limbs[c].sibling


def _candidates(data: bytes, segment: int) -> "np.ndarray":
    """Offsets that could be a skeleton header, found with numpy rather than a Python loop.

    A header is ``u32 limbsSegment; u8 limbCount; u8 pad[3]``, so at a 4-byte-aligned offset
    the first byte is the segment number, byte 4 is a plausible limb count and bytes 5-7 are
    zero.  Validating every offset in Python instead costs minutes per ROM; this narrows a
    megabyte to a handful of candidates before any of the expensive checks run.
    """
    import numpy as np

    n = (len(data) - HEADER_SIZE) // 4 * 4
    if n <= 0:
        return np.empty(0, dtype=np.int64)
    buf = np.frombuffer(data[:n + HEADER_SIZE], dtype=np.uint8)
    off = np.arange(0, n, 4)
    ok = buf[off] == segment  # the segment byte of limbsSegment
    ok &= (buf[off + 4] >= 1) & (buf[off + 4] <= 127)  # limbCount
    ok &= buf[off + 5] == 0
    ok &= buf[off + 6] == 0
    ok &= buf[off + 7] == 0
    return off[ok]


def find_skeletons(data: bytes, segment: int = 6) -> list[Skeleton]:
    """Every skeleton header in a file.

    The header is only 8 bytes, so it is found by validating what it points at rather than by
    the header alone: the limb table must be in-segment, in-bounds, and every limb's child and
    sibling must be a real limb index.  That chain is what rules out coincidence.
    """
    out: list[Skeleton] = []
    seen: set[int] = set()
    for off in _candidates(data, segment):
        skel = read_skeleton(data, int(off), segment)
        if skel is None or skel.count < 2:
            continue
        key = HEADER.unpack_from(data, int(off))[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(skel)
    return out


def limb_roles(skel: Skeleton) -> dict[int, str]:
    """Guess a Mixamo-ish role per limb from the tree's shape, since limbs have no names.

    Only the structure is available: which limbs branch, how deep they sit, and the sign of
    their sideways offset.  This is a hint for the retargeter to check, not an authority - it
    is recorded as ``inferred`` in the exported rig exactly like gcrip's structural mapper.
    """
    roles: dict[int, str] = {}
    if not skel.limbs:
        return roles
    order = skel.order()
    roles[order[0]] = "Hips"
    # limbs whose x offset is strongly signed are the sided ones
    for limb in skel.limbs:
        if limb.index == order[0]:
            continue
        if abs(limb.x) > 4:
            roles.setdefault(limb.index, "Left" if limb.x > 0 else "Right")
    return roles
