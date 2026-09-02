"""Terminal Reality ``_dfm`` meshes - the header and part table.

Cluster 6.  The geometry itself is still unread; what this settles is the part table, and with
it **the per-part bounding box that the vertex work was missing**.  ``docs/OPEN.md`` recorded
that "both bounding-box tests come back empty" and that every normal-agreement fit was
planar-degenerate.  There is a box per part, sitting in plain sight in the table.

Little-endian::

    +0    u32   version        2 on every sample
    +8    u32   part count
    +12   u32   bone count     equal to the paired `.SKL`'s
    +24   char  skeleton file name, NUL then `BAADF00D` fill
    +104  count x { char name[30]; u32 bone; f32 box[6] }   stride 58

As in the skeletons (:mod:`gcrip.formats.tr_skl`), short names are padded with ``BAADF00D``
rather than zeroes, which is what made these records look variable-length.

Three checks agree across two meshes of very different sizes - 59 parts in ``soldier.dfm`` and
23 in ``mentor.dfm``:

* **every name decodes**, 59 of 59 and 23 of 23 - ``binoculars2``, ``canteen``, ``gasmask``,
  ``Lbladehilt``;
* **every bone index is inside the skeleton**, 59 of 59 and 23 of 23;
* **every box has `min <= max` on all three axes**, 59 of 59 and 23 of 23.  Six floats in a row
  satisfying that on every record is not something a wrong stride produces.

And the mesh names its skeleton twice over: the string at +24 is ``SOLDIER_DEFAULT.SKL``, and
the bone count at +12 is 82, exactly what that file holds (68 and ``MENTOR.SKL`` for the other).

**What is still open** is the geometry, which follows a material table - the first record after
the parts carries ``1.0, 1.0, 32.0`` and the texture name ``SOLDIER.TIF``.  The tail is only
9.9% plausible ``f32``, so the vertices are quantised, which agrees with the 20-byte vertex the
size arithmetic implied.  The boxes here are what a candidate layout should now be tested
against: decode a part's vertices, scale, and they must land inside that part's box.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = 104
NAME = 30
STRIDE = 58
MAX_PARTS = 1 << 12


@dataclass
class Part:
    name: str
    bone: int
    box_min: tuple[float, float, float]
    box_max: tuple[float, float, float]


@dataclass
class Mesh:
    version: int
    bone_count: int
    skeleton: str
    parts: list[Part]


def is_dfm(head: bytes) -> bool:
    if len(head) < 16:
        return False
    version, _one, parts, bones = struct.unpack_from("<4I", head, 0)
    return version == 2 and 0 < parts <= MAX_PARTS and 0 < bones <= MAX_PARTS


def mesh(data: bytes) -> Mesh | None:
    """The header and part table, or ``None`` when the table does not check out."""
    if not is_dfm(data[:16]):
        return None
    version, _one, count, bones = struct.unpack_from("<4I", data, 0)
    if HEADER + count * STRIDE > len(data):
        return None
    skel = data[24:HEADER].split(b"\0", 1)[0].decode("latin-1", "replace")
    parts: list[Part] = []
    for i in range(count):
        at = HEADER + i * STRIDE
        raw = data[at : at + NAME].split(b"\0", 1)[0]
        bone = struct.unpack_from("<I", data, at + NAME)[0]
        box = struct.unpack_from("<6f", data, at + NAME + 4)
        # a wrong stride shows up here first: the box stops being a box
        if bone >= bones or any(box[k] > box[k + 3] for k in range(3)):
            return None
        parts.append(Part(raw.decode("latin-1", "replace"), bone, box[:3], box[3:]))
    return Mesh(version, bones, skel, parts)
