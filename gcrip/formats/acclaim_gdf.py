"""Acclaim ``.GDF`` / ``.SKN`` meshes - All-Star Baseball 2002, 2003 and 2004.

``docs/OPEN.md`` recorded this as blocked on the index data: ``StickBat.GDF`` ended in ordinary
GX display lists but ``brewers.GDF`` had "none at any stride".  It has 182 of them.  They were
being looked for in the wrong place, because the attribute block was located by
``len(file) - attributes - trailing`` - right on the small files by coincidence, and landing in
the middle of the vertices on the big one.

Big-endian::

    +0    char name[20]
    +20   u32 materials
    +24   u32
    +28   u32 meshes
    +32   u32 groups
    +36   u32 attribute bytes
    +40   u32 display-list bytes
    +44   materials x char name[32]
          meshes x { char name[16]; u32 flags; u32 first group; u32 groups;
                     u32 vertices; f32 radius; u32 code; u32 offset }
          groups x 88 { ...; u32 material; u32 offset; u32 size; u32 vertices; u32 triangles }
    base  the attribute block
    base + attributes   the display lists

with ``base = 44 + materials * 32 + meshes * 44 + groups * 88`` - 340, 340 and 448 on the three
samples, the first two matching the offset the old note reached another way.

**The identity that settles the vertex layout is the radius.**  Each mesh record carries a
bounding radius, and the largest ``|v|`` over the decoded positions equals it to the last digit
on 5 of 5 meshes - 30.5068, 43.9925, 15.9865.  One number fixes the offset, the stride and the
byte order together, and a wrong reading cannot satisfy it.

The vertex stride comes from the mesh's ``code``:

===== ======  ====================================================
code  stride  layout
===== ======  ====================================================
1     12      ``f32`` position
2     32      ``f32`` position, ``f32`` normal, ``f32`` uv
3     24      ``f32`` position, packed ``u32`` normal, ``f32`` uv
===== ======  ====================================================

and the number of ``u16`` indices a display list spends per vertex follows it: **one** for the
position-only code and **three** for the others - and where there are three they hold the same
value every time, so the attributes are interleaved rather than separately indexed.

The second identity is the declared triangle count: summed over the groups it is what the
display lists actually produce, **1,274 of 1,274** on ``brewers.GDF`` and exact on the other two.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.identities import Identity

#: (name field, header size) - ``.GDF`` files use the first, ``.SKN`` the second.  In both the
#: counts sit at `name`, `name + 8`, `name + 12` and the two block sizes are the last two words.
SHAPES = ((20, 44), (36, 76))
NAME_LEN = 20
MATERIAL_NAME = 32
MESH_RECORD = 44
GROUP_RECORD = 88
HEADER = 44
#: mesh code -> bytes a vertex
STRIDES = {1: 12, 2: 32, 3: 24}
#: ... and u16 indices a vertex in the display list
INDEX_WIDTH = {1: 1, 2: 3, 3: 3}
#: GX primitive opcodes this format uses
STRIP, TRIANGLES, FAN, QUADS = 0x98, 0x90, 0xA0, 0x80
MAX_COUNT = 1 << 20


class GdfError(ValueError):
    """The file does not read as an Acclaim mesh."""


@dataclass(frozen=True)
class Mesh:
    name: str
    flags: int
    first_group: int
    groups: int
    vertices: int
    radius: float
    code: int
    offset: int

    @property
    def stride(self) -> int:
        return STRIDES.get(self.code, 0)


@dataclass(frozen=True)
class Group:
    material: int
    offset: int
    size: int
    vertices: int
    triangles: int


@dataclass(frozen=True)
class Model:
    name: str
    materials: list
    meshes: list
    groups: list
    base: int
    attributes: int
    display: int

    @property
    def display_at(self) -> int:
        return self.base + self.attributes


def _fields(head: bytes, shape):
    name_len, header = shape
    if len(head) < header or not head[:1].isalnum() or 0 not in head[:name_len]:
        return None
    mats = struct.unpack_from(">I", head, name_len)[0]
    meshes, groups = struct.unpack_from(">2I", head, name_len + 8)
    attr, disp = struct.unpack_from(">2I", head, header - 8)
    if not (0 < meshes <= MAX_COUNT and mats <= MAX_COUNT and groups <= MAX_COUNT):
        return None
    if not (0 < attr <= 1 << 28 and 0 < disp <= 1 << 28):
        return None
    return mats, meshes, groups, attr, disp


def shape_of(head: bytes, size: int | None = None):
    """Which header shape this file uses, or ``None``.

    Both are tried and the one whose block sizes fit the file wins; a `.SKN` read as a `.GDF`
    puts the counts in the middle of its name, which is what the sizes then say.
    """
    for shape in SHAPES:
        got = _fields(head, shape)
        if got is None:
            continue
        mats, meshes, groups, attr, disp = got
        base = shape[1] + mats * MATERIAL_NAME + meshes * MESH_RECORD + groups * GROUP_RECORD
        if size is not None and base + attr + disp > size:
            continue
        if len(head) >= base and not _mesh_table_reads(head, shape, mats, meshes, attr):
            continue
        return shape
    return None


def _mesh_table_reads(data: bytes, shape, mats: int, meshes: int, attr: int) -> bool:
    """Do the mesh records read as mesh records?

    Without this a ``.SKN`` is accepted on its header alone and its **bone name table** is read
    as meshes, which produces four-billion-triangle counts rather than an error.  `.SKN` carries
    a skeleton - 23 bones, 32-byte name slots, `ROOT`, `L_UP_LEG`, `L_FOOT` - between the
    materials and whatever follows, and its vertex records are not the ones below, so it is
    declined here rather than half-read.
    """
    at = shape[1] + mats * MATERIAL_NAME
    for i in range(meshes):
        o = at + i * MESH_RECORD
        if o + MESH_RECORD > len(data):
            return False
        verts, _radius, code, off = struct.unpack_from(">IfII", data, o + 28)
        if code not in STRIDES or not 0 < verts <= MAX_COUNT:
            return False
        if off + verts * STRIDES[code] > attr:
            return False
    return True


def is_gdf(head: bytes, size: int | None = None) -> bool:
    return shape_of(head, size) is not None


def _cstr(raw: bytes) -> str:
    return raw.split(bytes(1))[0].decode("latin-1", "replace")


def model(data: bytes) -> Model:
    shape = shape_of(data, len(data))
    if shape is None:
        raise GdfError("not an Acclaim .GDF / .SKN header")
    name_len, header = shape
    name = _cstr(data[:name_len])
    mats, n_meshes, n_groups, attr, disp = _fields(data, shape)
    at = header
    materials = []
    for _ in range(mats):
        materials.append(_cstr(data[at : at + MATERIAL_NAME]))
        at += MATERIAL_NAME
    meshes = []
    for _ in range(n_meshes):
        nm = _cstr(data[at : at + 16])
        flags, first, count, verts, radius, code, off = struct.unpack_from(">3IIfII", data, at + 16)
        meshes.append(Mesh(nm, flags, first, count, verts, radius, code, off))
        at += MESH_RECORD
    groups = []
    for _ in range(n_groups):
        w = struct.unpack_from(">7I", data, at)
        groups.append(Group(w[2], w[3], w[4], w[5], w[6]))
        at += GROUP_RECORD
    base = at
    if base + attr + disp > len(data):
        raise GdfError(f"the blocks run past the file ({base} + {attr} + {disp} > {len(data)})")
    return Model(name, materials, meshes, groups, base, attr, disp)


def positions(data: bytes, m: Model, mesh: Mesh):
    """A mesh's vertex positions.  Raises when the attribute code is one this does not know."""
    import numpy as np

    stride = mesh.stride
    if not stride:
        raise GdfError(f"mesh {mesh.name!r} has attribute code {mesh.code}, which is unread")
    at = m.base + mesh.offset
    if at + mesh.vertices * stride > len(data):
        raise GdfError(f"mesh {mesh.name!r} runs past the attribute block")
    words = stride // 4
    return np.frombuffer(data, ">f4", mesh.vertices * words, at).reshape(-1, words)[:, :3]


def triangles(data: bytes, m: Model, mesh: Mesh, group: Group) -> list:
    """One group's display list, flattened to triangles indexing the mesh's vertices."""
    width = INDEX_WIDTH.get(mesh.code, 3)
    at = m.display_at + group.offset
    end = min(at + group.size, len(data))
    out = []
    while at < end:
        op = data[at]
        if op == 0:  # the lists are padded with NOPs
            at += 1
            continue
        if op not in (STRIP, TRIANGLES, FAN, QUADS):
            break
        count = struct.unpack_from(">H", data, at + 1)[0]
        at += 3
        span = count * width * 2
        if at + span > end:
            break
        idx = [struct.unpack_from(">H", data, at + k * width * 2)[0] for k in range(count)]
        at += span
        if op == STRIP:
            out += [
                (idx[i], idx[i + 1], idx[i + 2]) if i % 2 == 0 else (idx[i + 1], idx[i], idx[i + 2])
                for i in range(count - 2)
            ]
        elif op == FAN:
            out += [(idx[0], idx[i], idx[i + 1]) for i in range(1, count - 1)]
        elif op == TRIANGLES:
            out += [tuple(idx[i : i + 3]) for i in range(0, count - 2, 3)]
        else:
            for i in range(0, count - 3, 4):
                out.append((idx[i], idx[i + 1], idx[i + 2]))
                out.append((idx[i], idx[i + 2], idx[i + 3]))
    return [t for t in out if t[0] != t[1] and t[1] != t[2] and t[0] != t[2]]


def all_triangles(data: bytes, m: Model, mesh: Mesh) -> list:
    out = []
    for gi in range(mesh.first_group, min(mesh.first_group + mesh.groups, len(m.groups))):
        out += triangles(data, m, mesh, m.groups[gi])
    return out


# -- identities ---------------------------------------------------------------------------


def _radius_matches(data: bytes):
    import numpy as np

    try:
        m = model(data)
    except (GdfError, struct.error) as exc:
        return None, str(exc)
    held = total = 0
    for mesh in m.meshes:
        if not mesh.stride or not mesh.vertices:
            continue
        total += 1
        v = positions(data, m, mesh)
        if abs(float(np.linalg.norm(v, axis=1).max()) - mesh.radius) <= 1e-4 * max(1.0, mesh.radius):
            held += 1
    if not total:
        return None, "no meshes with a known attribute code"
    return held == total, f"{held} of {total} meshes have max |v| equal to their declared radius"


def _triangles_match(data: bytes):
    try:
        m = model(data)
    except (GdfError, struct.error) as exc:
        return None, str(exc)
    if not m.groups:
        return None, "no groups"
    declared = sum(g.triangles for g in m.groups)
    got = sum(len(all_triangles(data, m, mesh)) for mesh in m.meshes)
    return got == declared, f"{got} triangles decoded against {declared} declared"


IDENTITIES = [
    Identity(
        "the bounding radius is the largest vertex",
        "max |v| over a mesh's decoded positions == the f32 radius in its record",
        _radius_matches,
    ),
    Identity(
        "the display lists produce the declared triangles",
        "triangles decoded over a file's groups == the sum of their declared counts",
        _triangles_match,
    ),
]
