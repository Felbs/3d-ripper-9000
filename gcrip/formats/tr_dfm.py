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

from gcrip.identities import Identity

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

# -- identities ---------------------------------------------------------------------------


def _boxes_are_boxes(data: bytes) -> tuple[bool | None, str]:
    """min <= max on all three axes, on every part - the check that pins the 58-byte stride."""
    m = mesh(data)
    if m is None:
        return None, "not a readable _dfm"
    bad = sum(
        1 for p in m.parts if any(lo > hi for lo, hi in zip(p.box_min, p.box_max))
    )
    return bad == 0, f"{len(m.parts) - bad} of {len(m.parts)} boxes have min <= max"


def _bones_in_range(data: bytes) -> tuple[bool | None, str]:
    m = mesh(data)
    if m is None:
        return None, "not a readable _dfm"
    bad = sum(1 for p in m.parts if p.bone >= m.bone_count)
    return bad == 0, f"{len(m.parts) - bad} of {len(m.parts)} bone indices inside {m.bone_count}"


def _names_decode(data: bytes) -> tuple[bool | None, str]:
    m = mesh(data)
    if m is None:
        return None, "not a readable _dfm"
    ok = sum(1 for p in m.parts if p.name and all(32 <= ord(c) < 127 for c in p.name))
    return ok == len(m.parts), f"{ok} of {len(m.parts)} part names printable"


IDENTITIES = [
    Identity("every box is a box", "box_min[k] <= box_max[k] for k in 0..2", _boxes_are_boxes),
    Identity("bone indices resolve", "part.bone < header bone count", _bones_in_range),
    Identity("part names decode", "every part name is printable ASCII", _names_decode),
]


# -- the geometry blocks --------------------------------------------------------------------
#
# After the part table and the material table the file is a flat run of **sub-mesh blocks**,
# each a 40-byte header followed by its own vertices and its own triangle list::
#
#     u32 a, b          two small indices - a part or bone pair
#     u32 2             constant
#     u32 payload       the vertex bytes, plus four
#     u32 4             constant
#     u32 vertices
#     u32 triangles
#     u32 bone count    the same number the file header carries, and the .SKL holds
#     u32 0
#     u32 0x0A000000    constant
#     ... vertices ...  `payload - 4` bytes
#     ... triangles ... three u16 an entry
#
# Two identities pin it, and both are of the kind that cannot pass by accident:
#
# * **the blocks tile** - ``next block == this block + 36 + payload + 6 * triangles`` on
#   **106 of 106** blocks in `soldier.dfm` and **47 of 47** in `mentor.dfm`, the last one ending
#   exactly at the end of the file;
# * **every index is inside its own block's vertex array and the largest is exactly
#   `vertices - 1`** - again 106 of 106 and 47 of 47.  That is the one oracle this project has
#   proven on quantised geometry (see `gcrip/oracles.py`), and it fixes both the block
#   boundaries and the u16 index width at once.
#
# Which gives soldier.dfm 106 blocks, 4,215 vertices and 3,914 triangles, and mentor.dfm 47,
# 3,241 and 3,760.
#
# **The vertex record itself is still unread.**  75 of soldier's 106 blocks have
# ``payload == vertices * 20 + 4`` exactly - the 20-byte stride the byte autocorrelation found -
# and the rest are wider, which is what a variable-length skinning list looks like.  Inside a
# 20-byte record byte 3 is always `0x04`, byte 4 always `0x00` (the `0x0400` marker), byte 15
# always `0x44` and bytes 16-17 always `0x01FE` (510).  Read as little-endian `s16` the narrow
# columns are 1, 2 and 3; read big-endian they are 4, 8 and 9.  Neither triple behaves like a
# position: scored by how short a triangle's perimeter is against the block's own diagonal - a
# real surface scores near 0.1 - the best of all 240 column triples over 29 blocks reaches only
# 0.44, and the field is flat behind it.  With eleven of twenty bytes carrying about forty
# distinct values over 130 vertices, the reading that fits is packed bit fields rather than
# whole `s16` columns.

#: u32 a, b, 2, payload, 4, vertices, triangles, bones, 0, 0x0A000000
BLOCK_HEADER = 40
#: the payload word counts the vertex bytes plus four
PAYLOAD_BIAS = 4
#: three u16 a triangle
INDEX_BYTES = 6
#: the constant that ends every block header, and the only reliable way to find one
BLOCK_TAIL = 0x0A000000
#: the rigid vertex record; wider blocks carry a variable-length skinning list instead
RIGID_STRIDE = 20
MAX_BLOCKS = 1 << 16


@dataclass(frozen=True)
class Block:
    """One sub-mesh: its own vertices and its own triangle list."""

    offset: int
    a: int
    b: int
    payload: int
    vertices: int
    triangles: int

    @property
    def vertex_at(self) -> int:
        return self.offset + BLOCK_HEADER

    @property
    def vertex_bytes(self) -> int:
        return self.payload - PAYLOAD_BIAS

    @property
    def index_at(self) -> int:
        return self.offset + BLOCK_HEADER + self.vertex_bytes

    @property
    def size(self) -> int:
        return BLOCK_HEADER - PAYLOAD_BIAS + self.payload + self.triangles * INDEX_BYTES

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def rigid(self) -> bool:
        """A 20-byte vertex record, rather than the wider skinned one."""
        return self.vertices and self.payload == self.vertices * RIGID_STRIDE + PAYLOAD_BIAS


def blocks(data: bytes) -> list[Block]:
    """Every sub-mesh block, found by the constant that ends each header.

    A block is not searched for by guessing at strides: the last ten header words end with a
    bone count the file already states and two constants, and the blocks then have to tile.
    """
    head = mesh(data)
    if head is None:
        return []
    tail = struct.pack("<3I", head.bone_count, 0, BLOCK_TAIL)
    out: list[Block] = []
    at = data.find(tail)
    while at >= 0 and len(out) < MAX_BLOCKS:
        start = at - 28  # the bone count sits at +28 in the header
        if start >= 0:
            w = struct.unpack_from("<10I", data, start)
            if w[2] == 2 and w[4] == PAYLOAD_BIAS and w[3] > PAYLOAD_BIAS:
                out.append(Block(start, w[0], w[1], w[3], w[5], w[6]))
        at = data.find(tail, at + 1)
    return out


def tiles(data: bytes, found: list[Block]) -> bool:
    """Do the blocks account for every byte from the first one to the end of the file?"""
    if not found:
        return False
    return all(a.end == b.offset for a, b in zip(found, found[1:])) and found[-1].end == len(data)


def indices(data: bytes, block: Block) -> "object":
    import numpy as np

    return np.frombuffer(data, "<u2", block.triangles * 3, block.index_at).reshape(-1, 3)


def _blocks_tile(data: bytes):
    found = blocks(data)
    if not found:
        return None, "no blocks"
    good = sum(1 for a, b in zip(found, found[1:]) if a.end == b.offset)
    good += 1 if found[-1].end == len(data) else 0
    return good == len(found), f"{good} of {len(found)} blocks reach the next one exactly"


def _indices_inside(data: bytes):
    import numpy as np

    found = blocks(data)
    if not found:
        return None, "no blocks"
    exact = 0
    for b in found:
        if b.index_at + b.triangles * INDEX_BYTES > len(data) or not b.triangles:
            continue
        top = int(np.frombuffer(data, "<u2", b.triangles * 3, b.index_at).max())
        exact += top == b.vertices - 1
    return exact == len(found), f"{exact} of {len(found)} blocks index exactly 0..vertices-1"


IDENTITIES += [
    Identity(
        "the geometry blocks tile",
        "block start + 36 + payload + 6 * triangles == the next block, and the last ends the file",
        _blocks_tile,
    ),
    Identity(
        "every triangle indexes its own block",
        "the largest index in a block is exactly its vertex count minus one",
        _indices_inside,
    ),
]
