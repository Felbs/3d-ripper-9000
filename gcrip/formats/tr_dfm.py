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

import numpy as np

from gcrip.identities import Identity

HEADER = 104  # version 2 with one LOD: 16 + 8 + the 80-byte skeleton name
NAME = 30
STRIDE = 58
MAX_PARTS = 1 << 12
VERSIONS = (2, 5)  # BloodRayne; Blowout (a material count, a u16 after each part's box)
SKELETON_NAME = 80
LOD_PAIR = 8
STRIDE_V5 = 60
MATERIAL_V5 = 4 + 0x164  # u32 version 7, then CMaterial's 356 bytes


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
    lods: int = 1
    materials: int = 0  # version 5 counts its CMaterial records
    parts_end: int = 0  # file offset just past the part table


def is_dfm(head: bytes) -> bool:
    if len(head) < 20:
        return False
    version, lods, parts, bones, extra = struct.unpack_from("<5I", head, 0)
    if version not in VERSIONS or not 0 < parts <= MAX_PARTS or not 0 < bones <= MAX_PARTS:
        return False
    return 0 < lods <= 8 and (version == 2 or 0 < extra <= MAX_PARTS)


def mesh(data: bytes) -> Mesh | None:
    """The header and part table, or ``None`` when the table does not check out."""
    if not is_dfm(data[:20]):
        return None
    version, lods, count, bones, extra = struct.unpack_from("<5I", data, 0)
    materials = extra if version == 5 else 0
    name_at = (20 if version == 5 else 16) + LOD_PAIR * lods
    stride = STRIDE_V5 if version == 5 else STRIDE
    first = name_at + SKELETON_NAME
    if first + count * stride > len(data):
        return None
    skel = data[name_at:first].split(b"\0", 1)[0].decode("latin-1", "replace")
    parts: list[Part] = []
    for i in range(count):
        at = first + i * stride
        raw = data[at : at + NAME].split(b"\0", 1)[0]
        bone = struct.unpack_from("<I", data, at + NAME)[0]
        box = struct.unpack_from("<6f", data, at + NAME + 4)
        # a wrong stride shows up here first: the box stops being a box
        if bone >= bones or any(box[k] > box[k + 3] for k in range(3)):
            return None
        parts.append(Part(raw.decode("latin-1", "replace"), bone, box[:3], box[3:]))
    return Mesh(version, bones, skel, parts, lods, materials, first + count * stride)


# -- identities ---------------------------------------------------------------------------


def _boxes_are_boxes(data: bytes) -> tuple[bool | None, str]:
    """min <= max on all three axes, on every part - the check that pins the 58-byte stride."""
    m = mesh(data)
    if m is None:
        return None, "not a readable _dfm"
    bad = sum(
        1 for p in m.parts if any(lo > hi for lo, hi in zip(p.box_min, p.box_max, strict=True))
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
    """One sub-mesh: its own vertices and its own triangle list.

    Version 2 keeps header, vertex bytes and a little-endian index list together; version 5
    (Blowout) writes every 36-byte header first and the payloads after, each payload holding
    its scale word, the offset of its big-endian index list, the records and the list.
    """

    offset: int
    a: int
    b: int
    payload: int
    vertices: int
    triangles: int
    scale_at: int = -1  # version 5: where the payload starts
    index_offset: int = 0  # version 5: the index list, from the payload start

    @property
    def vertex_at(self) -> int:
        if self.scale_at >= 0:
            return self.scale_at + 8
        return self.offset + BLOCK_HEADER

    @property
    def vertex_bytes(self) -> int:
        if self.scale_at >= 0:
            return self.index_offset - 8
        return self.payload - PAYLOAD_BIAS

    @property
    def index_at(self) -> int:
        if self.scale_at >= 0:
            return self.scale_at + self.index_offset
        return self.offset + BLOCK_HEADER + self.vertex_bytes

    @property
    def big_endian_indices(self) -> bool:
        return self.scale_at >= 0

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


BLOCK_HEADER_V5 = 36  # u32 2, a, b, 2, payload, type, vertices, triangles, bones


def blocks(data: bytes) -> list[Block]:
    """Every sub-mesh block.

    Version 2 blocks are found by the constant that ends each header - not by guessing at
    strides: the last header words end with a bone count the file already states and two
    constants, and the blocks then have to tile.  Version 5 lists its headers behind the bone
    tables and lays the payloads out after them in order.
    """
    head = mesh(data)
    if head is None:
        return []
    if head.version == 5:
        return _blocks_v5(data, head)
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


def _blocks_v5(data: bytes, head: Mesh) -> list[Block]:
    s = skin(data)
    if s is None:
        return []
    at = s.packets_at
    out: list[Block] = []
    for _lod in range(head.lods):
        if at + 4 > len(data):
            return []
        count = struct.unpack_from("<I", data, at)[0]
        at += 4
        heads = []
        for _ in range(min(count, MAX_BLOCKS)):
            if at + BLOCK_HEADER_V5 > len(data):
                return []
            w = struct.unpack_from("<9I", data, at)
            if w[0] != 2 or w[3] != 2:
                return []
            heads.append((at, w))
            at += BLOCK_HEADER_V5
        for offset, w in heads:
            if at + 8 > len(data) or at + w[4] > len(data):
                return []
            index_offset = struct.unpack_from(">I", data, at + 4)[0]
            out.append(Block(offset, w[1], w[2], w[4], w[6], w[7], at, index_offset))
            at += w[4]
    return out


def tiles(data: bytes, found: list[Block]) -> bool:
    """Do the blocks account for every byte from the first one to the end of the file?"""
    if not found:
        return False
    return all(a.end == b.offset for a, b in zip(found, found[1:], strict=False)) and found[
        -1
    ].end == len(data)


def indices(data: bytes, block: Block) -> np.ndarray:
    kind = ">u2" if block.big_endian_indices else "<u2"
    return np.frombuffer(data, kind, block.triangles * 3, block.index_at).reshape(-1, 3)


def _blocks_tile(data: bytes):
    found = blocks(data)
    if not found:
        return None, "no blocks"
    if found[0].big_endian_indices:
        last = found[-1]
        ok = last.scale_at + last.payload == len(data)
        return ok, f"{len(found)} payloads end {'exactly' if ok else 'short of'} the file"
    good = sum(1 for a, b in zip(found, found[1:], strict=False) if a.end == b.offset)
    good += 1 if found[-1].end == len(data) else 0
    return good == len(found), f"{good} of {len(found)} blocks reach the next one exactly"


def _indices_inside(data: bytes):
    found = blocks(data)
    if not found:
        return None, "no blocks"
    exact = 0
    for b in found:
        if b.index_at + b.triangles * INDEX_BYTES > len(data) or not b.triangles:
            continue
        top = int(indices(data, b).max())
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


# -- the vertex record and the bone tables, from the shipped ELF (2026-09-03) ----------------
#
# ``bloodrayne.elf`` keeps its symbol table.  ``CDeformableModel::loadStreamBinary`` reads the
# header above, then per bone a 12-byte home translation, a 24-byte box, a child count and a
# first-child index, and then the packets: ``CRenderPacket::loadHeader`` is the 40-byte block
# header (``a`` and ``b`` are the two words the model reads before it) and ``loadData`` takes
# the vertex bytes **raw** - it byte-swaps the u16 index list and nothing else, because the
# vertex payload is what ``APIDLLpolyListGCBoneVertex`` feeds the paired-single quantised
# loads from.  So the record is **big-endian** inside a little-endian file, and variable:
#
#     u8  bones                       1..4
#     s16 position[bones][3]          in that bone's space, / 2^scale (the payload word's byte)
#     s16 weight[bones]               / 2^scale, summing to one
#     s16 normal[3]                   / 32768
#     u8  bone[bones]                 indices into the skeleton
#     u16 uv[2]                       / 1024
#
# 20, 29, 38 and 47 bytes - the "0x0400" the byte statistics saw was the weight 1.0, the
# "0x01FE" the top of the first coordinate.  The home pose (``setToHomePose``) is identity
# rotations over the per-bone translations, so model space is the position plus the bone's
# accumulated translation, weighted.

SCALE_WORD = 36  # in the block header: the quantisation scale sits in its top byte (LE)
RECORD_SIZES = {1: 20, 2: 29, 3: 38, 4: 47}
MATERIAL_BLOCK = 0xF8
BONE_TRANSLATION = 12
BONE_BOX = 24


@dataclass
class BlockVertices:
    positions: np.ndarray  # (N, 4, 3) f32 per-bone positions, unused slots zero
    weights: np.ndarray  # (N, 4) f32
    bones: np.ndarray  # (N, 4) u16
    normals: np.ndarray  # (N, 3) f32
    uvs: np.ndarray  # (N, 2) f32


@dataclass
class Skin:
    translations: np.ndarray  # (bones, 3) f32 home translation to the parent
    boxes: np.ndarray  # (bones, 6) f32
    material: str  # the .TIF the material block names
    packets_at: int  # file offset of the packet count word


def scale_of(data: bytes, block: Block) -> float:
    at = block.scale_at + 3 if block.scale_at >= 0 else block.offset + SCALE_WORD + 3
    return 2.0 ** -(data[at] & 0x3F)


def vertices(data: bytes, block: Block) -> BlockVertices | None:
    """The block's vertex records decoded, or ``None`` when they do not tile to the index list."""
    scale = scale_of(data, block)
    n = block.vertices
    pos = np.zeros((n, 4, 3), np.float32)
    wgt = np.zeros((n, 4), np.float32)
    bon = np.zeros((n, 4), np.uint16)
    nrm = np.zeros((n, 3), np.float32)
    uv = np.zeros((n, 2), np.float32)
    p = block.vertex_at
    for i in range(n):
        if p >= len(data):
            return None
        k = data[p]
        size = RECORD_SIZES.get(k)
        if size is None or p + size > len(data):
            return None
        pos[i, :k] = np.frombuffer(data, ">i2", 3 * k, p + 1).reshape(k, 3) * scale
        wgt[i, :k] = np.frombuffer(data, ">i2", k, p + 1 + 6 * k) * scale
        nrm[i] = np.frombuffer(data, ">i2", 3, p + 1 + 8 * k) / 32768.0
        bon[i, :k] = np.frombuffer(data, np.uint8, k, p + 7 + 8 * k)
        uv[i] = np.frombuffer(data, ">u2", 2, p + 7 + 9 * k) / 1024.0
        p += size
    if p != block.index_at:
        return None
    return BlockVertices(pos, wgt, bon, nrm, uv)


def skin(data: bytes) -> Skin | None:
    """The per-bone tables between the material block and the packets."""
    m = mesh(data)
    if m is None:
        return None
    nb = m.bone_count
    at = m.parts_end
    if m.version == 5:
        # CMaterial records: u32 version 7, then 356 bytes with the .TIF name 12 bytes in
        if at + m.materials * MATERIAL_V5 > len(data):
            return None
        material = data[at + 16 : at + MATERIAL_V5].split(b"\0", 1)[0].decode("latin-1", "replace")
        at += m.materials * MATERIAL_V5
    else:
        if at + MATERIAL_BLOCK > len(data):
            return None
        material = data[at + 36 : at + 100].split(b"\0", 1)[0].decode("latin-1", "replace")
        at += MATERIAL_BLOCK
    need = nb * (BONE_TRANSLATION + BONE_BOX + 8) + 12
    if at + need + 4 > len(data):
        return None
    translations = np.frombuffer(data, "<f4", 3 * nb, at).reshape(nb, 3).copy()
    boxes = np.frombuffer(data, "<f4", 6 * nb, at + nb * BONE_TRANSLATION).reshape(nb, 6).copy()
    return Skin(translations, boxes, material, at + need)


def home_pose(translations, parents: list[int]):
    """World translation of every bone with identity rotations (``setToHomePose``)."""
    world = np.zeros_like(translations)
    for i, parent in enumerate(parents):
        world[i] = translations[i] + (world[parent] if 0 <= parent < i else 0)
    return world


def _packets_start_matches(data: bytes):
    s = skin(data)
    found = blocks(data)
    if s is None or not found:
        return None, "no skin tables or no blocks"
    count = struct.unpack_from("<I", data, s.packets_at)[0]
    ok = s.packets_at + 4 == found[0].offset and (count == len(found) or found[0].scale_at >= 0)
    return ok, f"packet count word at {s.packets_at} says {count}, {len(found)} blocks follow"


def _records_tile(data: bytes):
    found = blocks(data)
    if not found:
        return None, "no blocks"
    good = sum(1 for b in found if vertices(data, b) is not None)
    return good == len(found), f"{good} of {len(found)} blocks' records end on the index list"


def _weights_sum_to_one(data: bytes):
    found = blocks(data)
    if not found:
        return None, "no blocks"
    total = ok = 0
    for b in found:
        v = vertices(data, b)
        if v is None:
            continue
        s = v.weights.sum(1)
        total += len(s)
        ok += int(np.sum(np.abs(s - 1) < 0.01))
    return ok == total, f"{ok} of {total} vertices weigh 1.0"


IDENTITIES += [
    Identity(
        "the bone tables end on the packets",
        "bone tables + 4-byte packet count == the first block, count == blocks",
        _packets_start_matches,
    ),
    Identity(
        "vertex records tile",
        "1..4-bone records of 20/29/38/47 bytes end exactly on each block's index list",
        _records_tile,
    ),
    Identity(
        "weights sum to one", "the s16 / 2^scale weights of a vertex sum to 1", _weights_sum_to_one
    ),
]
