"""EA ``GCsk`` skinned characters - the meshes behind the ``Cact`` actors of The Lord of the
Rings: The Return of the King and The Third Age (the ``.scg`` SHOC streams,
:mod:`gcrip.formats.shoc`).

A ``Cact`` member itself is 172 bytes of descriptor - ``tACT`` (actor id) and ``aRSL``, a
resource list of ``(kind, index)`` pairs naming the members that make the actor up: its
``scbm`` mesh, ``txfs`` textures, ``bnk`` animations, ``rcb`` collision rig.  The geometry is
the **scbm** member, an ``OBG `` container at version ``01 05`` (terrain is ``01 04``) whose
single ``ELDA`` holds one ``GCsk`` model::

    OBG  01 05
    HEAD   declares 0x70 bytes but occupies 0x80 - the walk must resync
    ELHE x2  the second carries f32 bounding sphere (cx cy cz r), centre, full extents
    ELDA   u32 4, u32 0, then GCsk

    GCsk  u32 version(9) | u32 size | char name[12] "FROd.g3d" | u32 sections | u32 offsets[]

Section offsets are relative to the ``GCsk`` tag.  Each section is a mesh: ``char name[16]``
("01", "05", "01MELE000_SWD"...), then eight ``(count, offset, elem bytes)`` slot rows at
+0x10, a material count at +0x74 and 0x40-byte material entries from +0x84.  The slots:

    0  vertices, 10 bytes: s16 x y z (/1024), u8 weight (/128), u8 bone A, u8 bone B, u8 pad
    1  normals,   3 bytes: s8 x y z (/64)
    2  uvs,       4 bytes: s16 u v (/1024)
    4  skin groups, 12 bytes: f32 weight | u8 bone A | u8 bone B | u16 start | u16 count | pad
    7  shadow-volume records, 8 bytes (mesh "05" only; its one material has no display list)

A material entry is ``u32 triangles | u32 offset | u32 length``, ``ffffffff``, zero, then the
material name - which is exactly a texture name in the sibling ``txf*`` groups (``froface``,
``gimbody``).  The display list is GX triangle strips: opcode ``0x9d`` (DRAW_TRIANGLE_STRIP |
VAT 5), ``u16 corners``, then corners of three ``u16`` indices - position, normal, uv.

**Positions are model space at bind pose** (Frodo renders as a T-posed hobbit with no bone
composition), so a baked mesh needs no skeleton.  Bone bytes pair each vertex with up to two
bones - ``(A, 0xff)`` weight 1.0, else A at weight/128 and B at the rest - and the slot-4
groups run-length-encode the same assignment for the GX matrix palette.

Proven on Frodo + Gimli (six scbm, 16 display lists): every list walks to its last byte with
all three index columns in bounds; 4,927 of 4,928 normals are unit at /64; every uv lands in
[-4, 8] at /1024; and the emitted triangle count equals the material's declared count exactly
(2,990 over Frodo's four materials).  The scale is pinned by the sword scbm, whose ELHE
bounding sphere (0.2945) and extents (0.0809, 0.0317, 0.5825) match the /1024 mesh to three
decimals.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.identities import Identity

MAGIC = b"OBG "
CHARACTER_VERSION = b"\x01\x05"
GCSK = b"GCsk"
ELDA = b"ELDA"
TACT = b"tACT"
ARSL = b"aRSL"
POS_SCALE = 1.0 / 1024.0
NRM_SCALE = 1.0 / 64.0
UV_SCALE = 1.0 / 1024.0
WEIGHT_SCALE = 1.0 / 128.0
NO_BONE = 0xFF
STRIP = 0x98
OPCODE_MASK = 0xF8
NAME_AT = 0x14
MATERIALS_AT = 0x74
MATERIAL_STRIDE = 0x40
SLOTS = 8
VERTEX_SLOT, NORMAL_SLOT, UV_SLOT, SKIN_SLOT = 0, 1, 2, 4
MAX_SECTIONS = 256


@dataclass
class SkinGroup:
    weight: float
    bone_a: int
    bone_b: int
    start: int
    count: int


@dataclass
class Element:
    """One material: its display list read back as strips of (position, normal, uv) triples."""

    name: str
    declared: int  # the triangle count the header promises
    strips: list[np.ndarray]  # each (n, 3) u16

    @property
    def triangles(self) -> int:
        return sum(_strip_triangles(s) for s in self.strips)


@dataclass
class Mesh:
    name: str
    positions: np.ndarray  # (n, 3) f32, model space
    weights: np.ndarray  # (n,) f32 - bone A's share
    bones: np.ndarray  # (n, 2) u8 - bone A, bone B (0xff = none)
    normals: np.ndarray | None
    uvs: np.ndarray | None
    groups: list[SkinGroup] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)

    @property
    def shadow(self) -> bool:
        """Mesh "05" is a shadow volume: no normals, no uvs, no display list."""
        return not any(e.strips for e in self.elements)


@dataclass
class Model:
    name: str
    meshes: list[Mesh]


@dataclass
class Actor:
    """The ``Cact`` member: an id and the ``(kind, index)`` members that make the actor up."""

    index: int
    resources: list[tuple[str, int]]


def is_character(head: bytes) -> bool:
    return head[:4] == MAGIC and head[4:6] == CHARACTER_VERSION


def actor(data: bytes) -> Actor | None:
    """Parse a ``Cact`` member - ``tACT`` then ``aRSL``, both SHOC-sized (header included)."""
    if data[:4] != TACT or len(data) < 16:
        return None
    size = struct.unpack_from(">I", data, 4)[0]
    index = struct.unpack_from(">I", data, 8)[0]
    out = Actor(index, [])
    at = size
    if data[at : at + 4] != ARSL or at + 12 > len(data):
        return out
    end = min(at + struct.unpack_from(">I", data, at + 4)[0], len(data))
    at += 12  # header + the actor id repeated
    while at + 8 <= end:
        kind = data[at : at + 4].decode("latin-1").strip()
        out.resources.append((kind, struct.unpack_from(">I", data, at + 4)[0]))
        at += 8
    return out


def _gcsk_at(data: bytes) -> int | None:
    """The GCsk tag inside the ELDA - located by tag scan because HEAD declares 0x70 bytes
    but occupies 0x80, which desynchronises a sized-chunk walk 16 bytes in."""
    at = 0
    while True:
        at = data.find(ELDA, at)
        if at < 0:
            return None
        if data[at + 16 : at + 20] == GCSK:
            return at + 16
        at += 4


def model(data: bytes) -> Model | None:
    if not is_character(data):
        return None
    g = _gcsk_at(data)
    if g is None or g + 32 > len(data):
        return None
    name = data[g + 12 : g + 24].split(b"\0")[0].decode("latin-1")
    sections = struct.unpack_from(">I", data, g + 24)[0]
    if not 0 < sections <= MAX_SECTIONS or g + 28 + 4 * sections > len(data):
        return None
    offsets = struct.unpack_from(f">{sections}I", data, g + 28)
    meshes = [m for o in offsets if (m := _mesh(data, g, g + o)) is not None]
    return Model(name, meshes) if meshes else None


def _slot(data: bytes, base: int, mesh_at: int, n: int) -> tuple[int, int, int]:
    count, offset, elem = struct.unpack_from(">3I", data, mesh_at + 0x10 + 12 * n)
    if not count or base + offset + count * elem > len(data):
        return 0, 0, 0
    return count, base + offset, elem


def _mesh(data: bytes, base: int, at: int) -> Mesh | None:
    if at + MATERIALS_AT + 4 > len(data):
        return None
    name = data[at : at + 16].split(b"\0")[0].decode("latin-1")
    nv, ov, sv = _slot(data, base, at, VERTEX_SLOT)
    if not nv or sv != 10:
        return None
    raw = np.frombuffer(data, np.uint8, nv * 10, ov).reshape(nv, 10)
    positions = raw[:, :6].copy().view(">i2").reshape(nv, 3).astype(np.float32) * POS_SCALE
    weights = raw[:, 6].astype(np.float32) * WEIGHT_SCALE
    bones = raw[:, 7:9].copy()
    normals = uvs = None
    nn, on, sn = _slot(data, base, at, NORMAL_SLOT)
    if nn and sn == 3:
        normals = np.frombuffer(data, np.int8, nn * 3, on).reshape(nn, 3)
        normals = normals.astype(np.float32) * NRM_SCALE
    nu, ou, su = _slot(data, base, at, UV_SLOT)
    if nu and su == 4:
        uvs = np.frombuffer(data, ">i2", nu * 2, ou).reshape(nu, 2).astype(np.float32) * UV_SCALE
    groups = []
    ns, os_, ss = _slot(data, base, at, SKIN_SLOT)
    if ns and ss == 12:
        for i in range(ns):
            w = struct.unpack_from(">f", data, os_ + 12 * i)[0]
            a, b, start, count = struct.unpack_from(">2B2H", data, os_ + 12 * i + 4)
            groups.append(SkinGroup(w, a, b, start, count))
    counts = (nv, nn, nu)
    mats = struct.unpack_from(">I", data, at + MATERIALS_AT)[0]
    elements = []
    for m in range(mats):
        e = at + 0x84 + MATERIAL_STRIDE * m
        if e + MATERIAL_STRIDE > len(data):
            break
        declared, offset, length = struct.unpack_from(">3I", data, e)
        mat = data[e + NAME_AT : e + NAME_AT + 32].split(b"\0")[0].decode("latin-1")
        strips = _strips(data[base + offset : base + offset + length], counts) if length else []
        elements.append(Element(mat, declared, strips))
    return Mesh(name, positions, weights, bones, normals, uvs, groups, elements)


def _strips(dl: bytes, counts: tuple[int, int, int]) -> list[np.ndarray]:
    """GX display list: 0x9d + u16 count + count corners of (position, normal, uv) u16."""
    out: list[np.ndarray] = []
    at = 0
    while at + 3 <= len(dl):
        op = dl[at]
        if op == 0:  # padding to the 32-byte tail
            at += 1
            continue
        n = struct.unpack_from(">H", dl, at + 1)[0]
        if op & OPCODE_MASK != STRIP or at + 3 + n * 6 > len(dl):
            break
        corners = np.frombuffer(dl, ">u2", n * 3, at + 3).reshape(n, 3)
        if all(c == 0 or int(corners[:, i].max()) < c for i, c in enumerate(counts)):
            out.append(corners)
        at += 3 + n * 6
    return out


def _strip_triangles(corners: np.ndarray) -> int:
    if len(corners) < 3:
        return 0
    p = corners[:, 0].astype(np.int64)
    a, b, c = p[:-2], p[1:-1], p[2:]
    return int(np.sum((a != b) & (b != c) & (a != c)))


def strip_indices(corners: np.ndarray) -> np.ndarray:
    """(t, 3) row indices into the corner list - winding alternated, degenerates dropped."""
    if len(corners) < 3:
        return np.empty((0, 3), np.int64)
    p = corners[:, 0].astype(np.int64)
    a, b, c = p[:-2], p[1:-1], p[2:]
    keep = (a != b) & (b != c) & (a != c)
    rows = np.arange(len(a))[:, None] + np.array([[0, 1, 2]])
    odd = (np.arange(len(a)) & 1).astype(bool)
    rows = np.where(odd[:, None], np.arange(len(a))[:, None] + [[1, 0, 2]], rows)
    return rows[keep]


# -- identities ---------------------------------------------------------------------------


def _triangles_match_declared(data: bytes):
    """Each material's strips emit exactly the triangle count its header declares."""
    got = model(data)
    if got is None:
        return None, "not a GCsk character"
    es = [e for m in got.meshes for e in m.elements if e.strips]
    if not es:
        return None, "no display lists"
    ok = sum(1 for e in es if e.triangles == e.declared)
    return ok == len(es), f"{ok} of {len(es)} materials emit their declared triangle count"


def _normals_are_unit(data: bytes):
    """The slot-1 s8 triples are unit vectors at /64."""
    got = model(data)
    if got is None:
        return None, "not a GCsk character"
    ns = [m.normals for m in got.meshes if m.normals is not None]
    if not ns:
        return None, "no normals"
    mag = np.linalg.norm(np.concatenate(ns), axis=1)
    ok = int(np.sum(np.abs(mag - 1.0) < 0.05))
    return ok >= 0.99 * mag.size, f"{ok} of {mag.size} normals are unit at /64"


IDENTITIES = [
    Identity(
        "materials emit their declared triangle count",
        "sum over strips of non-degenerate windows == material.declared",
        _triangles_match_declared,
    ),
    Identity(
        "normals are unit at /64",
        "|s8 triple| / 64 == 1",
        _normals_are_unit,
    ),
]
