"""Terminal Reality ``.SKL`` skeletons - BloodRayne, Blowout, RoadKill.

Cluster 6's blocker.  ``docs/OPEN.md`` recorded that *"`HERO.SKL`'s bone records are not
fixed-layout (the numeric fields do not line up beneath the names), so that has to be settled
first"*.  **They are fixed-layout.**  What hides it is that the padding after each name is not
zeroes but ``BAADF00D`` repeated - the debug fill - so a name shorter than the field is followed
by ``0d f0 ad ba 0d f0 ad ba ...`` and the numbers appear to sit at a different place in every
record.

Little-endian::

    +0    u32   version    2 on every sample
    +4    u32   bone count
    +8    count x { char name[32]; s32 parent }

The stride is **36 bytes**, and the name field is a fixed 32 whatever the name's length.

Four checks agree on the whole table, on two skeletons of different sizes - 82 bones in
``SOLDIER_DEFAULT.SKL`` and 68 in ``MENTOR.SKL``:

* **every name decodes**, 82 of 82 and 68 of 68, as printable ASCII;
* **every parent is in range**, and there is **exactly one root** - index 0, ``Bip01 Pelvis``,
  with parent ``-1``;
* **no parent points forward.**  Every parent index is smaller than its child's, so the table is
  already in topological order and can be walked in one pass.  A wrong stride would scatter that
  immediately;
* the tree is anatomically right where it can be read - ``Bip01 R Calf`` hangs off
  ``Bip01 R Thigh``, ``Bip01 Neck`` off ``Bip01 Spine2``, ``bip01 apron2`` off ``bip01 apron1``.

The table is small: 82 bones end at byte 2,960 of a 2,954,178-byte file.  **The rest is
animation**, which matches the earlier finding that `.SKL` is 99% clips.

**There are no bind transforms here** - a record is a name and a parent, nothing more.  So this
reads the hierarchy and does not by itself settle the ``_dfm`` vertex layout, which needs the
bind pose.  What it does remove is the reason that work was blocked.

The count cross-checks against the mesh: ``soldier.dfm``'s fourth word is 82 and
``mentor.dfm``'s is 68, each matching its skeleton's bone count exactly.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = 8
NAME = 32
STRIDE = 36
MAX_BONES = 1 << 12


@dataclass
class Bone:
    name: str
    parent: int


def is_skl(head: bytes) -> bool:
    """``u32 version == 2`` and a plausible bone count.  The magic is weak on purpose - these
    files are reached by name inside a ``.PKG``, not sniffed out of a disc."""
    if len(head) < HEADER:
        return False
    version, count = struct.unpack_from("<2I", head, 0)
    return version == 2 and 0 < count <= MAX_BONES


def bones(data: bytes) -> list[Bone]:
    """The bone table, or ``[]`` when it does not check out.

    Rejected rather than guessed at: a parent out of range, more than one root, or a parent
    pointing forward all mean the stride is wrong, and a half-read skeleton is worse than none.
    """
    if not is_skl(data[:HEADER]):
        return []
    count = struct.unpack_from("<I", data, 4)[0]
    if HEADER + count * STRIDE > len(data):
        return []
    out: list[Bone] = []
    roots = 0
    for i in range(count):
        at = HEADER + i * STRIDE
        raw = data[at : at + NAME].split(b"\0", 1)[0]
        parent = struct.unpack_from("<i", data, at + NAME)[0]
        if parent == -1:
            roots += 1
        elif not 0 <= parent < i:  # in range, and never forward
            return []
        out.append(Bone(raw.decode("latin-1", "replace"), parent))
    if roots != 1 or not out:
        return []
    return out
