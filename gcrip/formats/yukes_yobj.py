"""Yuke's ``YOBJ`` meshes - the ``.ymg`` files of the WWE discs.

WrestleMania X8 carries 732 of them (31 MB) and WrestleMania XIX 1,464 (28 MB); the two Day of
Reckoning discs have 1,099 and 207, though nearly all of theirs are ``DUMY`` wrappers rather
than ``YOBJ`` (see the note).  All four discs produced no models at all.

Big-endian::

    +0    char magic[4]   "YOBJ"
    +12   u32 table offset
    +16   u32

The table holds one record per mesh, but **the record length is not constant** - it drifts by
four bytes between records because the trailing float block varies - so records are found by
the constant word ``0x0a000000`` that every one contains rather than by a stride.  Relative to
that marker at ``m``::

    m-8   u16 vertex count
    m+4   u32 -> positions
    m+8   u32 -> normals
    m+16  u32 -> the index block

**Every offset in this format points eight bytes before its data.**  That is the whole trick:
read the arrays at the offset itself and the first normal comes out with a length of 7.05
instead of 1, while the other eleven are exactly 1 - which reads like an off-by-one in the
count rather than a block header.  At ``offset + 8`` all of them are unit vectors.

Positions and normals are ``count`` triples of big-endian ``f32``, and ``normals - positions ==
count * 12`` has to hold.  The index block is a run of ``u32 count`` followed by that many
``u16`` triangle-strip indices, packed with no padding, starting at ``C + 16`` - the extra
eight bytes past the usual ``+8`` being a small header the strips follow.

## How well it checks out

The positions and normals are confirmed on both variants and are not in doubt: **981 of 981
records** in X8's ``dummy_x8.ymg`` and **10,445 of 10,445** normals in XIX's ``0_2.ymg`` come
out unit length at ``+8``, which no wrong layout does.

On X8 the index lists read too - 8,104 meshes, 125,428 vertices and 47,090 triangles from ten
files, with an unsigned normal agreement of **0.983 and 98% of meshes above 0.9**.  Winding is
inconsistent as it is in Terminal Reality's ``_smf`` and A2M's ``.gc``, so triangles are flipped
to agree with their own stored normals and the figure quoted is the unsigned one taken before
the flip.

**XIX's index block is laid out differently** and is not read here: it opens with a table of
eight-byte entries (``u16``, ``u16``, ``u32`` pointer) rather than going straight into strips.
A reader for that was tried and produced 97 triangles at 0.451 agreement while also cutting
X8 from 8,104 meshes to 5,480, so it is left out and the files are declined instead of being
turned into rubbish.

## Day of Reckoning (version 4, 2026-09-03)

The ``u16`` at +8 is a version: 3 on X8 / XIX, **4 on both Day of Reckoning discs**, whose
``.ymg`` wrap the YOBJ in a 24-byte ``DUMY`` stamp (``"DUMY", u32 16, zeros``) and end with a
``POF0`` pointer-offset table.  Read against the renderer in DoR's ``main.dol`` (the loop at
``0x800bdb2c`` that writes ``GX_TRIANGLESTRIP`` corners to the write-gather pipe: the same
u16 index for position and normal, then ``s16 u, v``; four corner layouts by two flag bits,
this one being uv-without-colour).  Every offset again points eight bytes before its data::

    +0x08  u16 4 (version), u16 meshes, u32 0x40
    +0x10  u32 bones, ptr        64-byte: char name[16], i32 parent, f32 translation[3],
                                 f32 rotation[3] (radians), f32 length, zeros
    +0x18  u32 materials, ptr    20-byte: rgba diffuse, rgba, rgba, u16 flags, u16, ptr
    +0x20  u32 names, ptr        16-byte texture names, the "." of ".bmp" written as NUL
    +0x28  u32, ptr              hair / accessory records (0x68 bytes)
    +0x48  mesh records, 0x30 bytes each:
           u16 vertices, u16, u8, u8 skin runs, u8 groups, u8, u32 0x0a000000, ptr data,
           u32 0, ptr skin runs, ptr groups, f32 centre[3], f32 radius, u16[4]

    data     vertices x 12 bytes: s16 position[3] / 64, s16 normal[3] / 4096 - stored in
             the order (nz, nx, ny) against the positions: read as (n1, n2, n0) they agree
             with the face normals at 0.97-0.998, in any other order below 0.6
    groups   8 bytes: u8 material, u8 strips, u16 strips, ptr - strips of ``u32 corners``
             then 6-byte corners ``u16 index, s16 u, s16 v`` (uv / 1024), one group per
             material, so a wrestler's head is eleven groups (face, hair, mouth, eyes ...)
    runs     16 bytes: ptr weights, u32, u8 bone[3] (0xff none), u8 bones, u32 vertices -
             consecutive vertex runs and the bones that move them; the weights behind the
             pointer are not decoded (the runs cover all but a few vertices of each mesh)

A material's pointer leads (+8) to ``u16 stages, u16, u8[4], u8[16], ptr, ptr`` and then
20-byte TEV stages whose last byte is a texture-name index (0xff none) - a face is g_skin,
m_face, face, blood in that order.  The textures themselves are the ``.tpl`` members of the
sibling ``.tex`` pack (``plugins/yukes_tex.py``), by those names.  Vertices are in the bind
pose, y down: the head of a wrestler sits at y = -175 with the Biped root at -102.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"YOBJ"
MARKER = 0x0A000000
COUNT_AT = -8
POS_AT = 4
NRM_AT = 8
IDX_AT = 16
BLOCK_SKIP = 8  # every offset points eight bytes before its data
INDEX_SKIP = 16
STRIDE = 12  # one f32 triple
MIN_COUNT = 3
MAX_COUNT = 1 << 16
MAX_STRIP = 8192
UNIT_TOLERANCE = 1e-2


CORNER = 10  # WrestleMania XIX: u16 index, RGBA8 colour, s16 uv / 32768
MAX_GROUPS = 4096
UV_SCALE = 1.0 / 32768.0


@dataclass
class Mesh:
    positions: np.ndarray
    normals: np.ndarray
    indices: np.ndarray
    unsigned_agreement: float
    uvs: np.ndarray | None = None
    colors: np.ndarray | None = None
    groups: list[int] | None = None  # WrestleMania XIX: the group a triangle came from


def _xix_groups(data: bytes, idx_at: int, count: int):
    """WrestleMania XIX's index block: a table of 8-byte entries - ``u8, u8, u16 strips, u32
    ptr`` - each pointing 8 bytes before its strips, every strip ``u32 corners`` then that
    many 10-byte corners (``u16 index, RGBA8, s16 u, s16 v``).  A single-entry table is the
    entry itself pointing at itself.  Returns (triangles, group ids, uvs, colours) or None
    when it does not read that way (X8's block starts with a strip count instead)."""
    t = idx_at + BLOCK_SKIP
    if t + 8 > len(data):
        return None
    first = struct.unpack_from(">I", data, t + 4)[0]
    n = (first - t) // 8 if first > t else 1
    if not 0 < n <= MAX_GROUPS or (first > t and (first - t) % 8):
        return None
    tris: list[tuple[int, int, int]] = []
    group_of: list[int] = []
    uv = np.zeros((count, 2), np.float32)
    col = np.full((count, 4), 255, np.uint8)
    for g in range(n):
        _a, _b, nstrips, ptr = struct.unpack_from(">BBHI", data, t + 8 * g)
        if nstrips == 0 or ptr + 8 > len(data) or (g == 0 and ptr != (first if n > 1 else t)):
            return None
        p = ptr + 8
        for _ in range(nstrips):
            if p + 4 > len(data):
                return None
            nv = struct.unpack_from(">I", data, p)[0]
            p += 4
            if not 1 <= nv <= MAX_STRIP or p + CORNER * nv > len(data):
                return None
            raw = np.frombuffer(data, np.uint8, CORNER * nv, p).reshape(nv, CORNER)
            ids = raw[:, :2].copy().view(">u2").reshape(nv)
            if int(ids.max()) >= count:
                return None
            uv[ids] = raw[:, 6:10].copy().view(">i2").reshape(nv, 2).astype(np.float32) * UV_SCALE
            col[ids] = raw[:, 2:6]
            p += CORNER * nv
            for k in range(nv - 2):
                a, b, c = int(ids[k]), int(ids[k + 1]), int(ids[k + 2])
                tris.append((a, b, c) if k % 2 == 0 else (b, a, c))
                group_of.append(g)
    if not tris:
        return None
    return tris, group_of, uv, col


def is_yobj(head: bytes) -> bool:
    return head[:4] == MAGIC or (head[:4] == DUMY and head[DUMY_SKIP : DUMY_SKIP + 4] == MAGIC)


# -- Day of Reckoning (version 4) -------------------------------------------------------------

DUMY = b"DUMY"
DUMY_SKIP = 24
VERSION_DOR = 4
MESH_TABLE = 0x48
MESH_RECORD = 0x30
VERTEX_DOR = 12
CORNER_DOR = 6
GROUP = 8
RUN = 16
MATERIAL = 20
STAGE = 20
NAME = 16
BONE = 64
POS_SCALE = 1.0 / 64.0
NRM_SCALE = 1.0 / 4096.0
UV_SCALE_DOR = 1.0 / 1024.0
NRM_ORDER = (1, 2, 0)  # the stored normal is (nz, nx, ny)
NO_TEXTURE = 0xFF


@dataclass
class DorMaterial:
    diffuse: tuple[int, int, int, int]
    textures: list[str]  # the TEV stages' texture names, in stage order


@dataclass
class DorGroup:
    mesh: int
    material: int
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray
    agreement: float


@dataclass
class DorBone:
    name: str
    parent: int
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float]


@dataclass
class DorModel:
    bones: list[DorBone] = field(default_factory=list)
    materials: list[DorMaterial] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    groups: list[DorGroup] = field(default_factory=list)
    meshes: int = 0
    warnings: list[str] = field(default_factory=list)


def yobj_at(data: bytes) -> int:
    """Where the YOBJ starts: 0, or past a ``DUMY`` stamp; -1 when neither."""
    if data[:4] == MAGIC:
        return 0
    if data[:4] == DUMY and data[DUMY_SKIP : DUMY_SKIP + 4] == MAGIC:
        return DUMY_SKIP
    return -1


def version(data: bytes) -> int:
    at = yobj_at(data)
    if at < 0 or at + 12 > len(data):
        return 0
    return struct.unpack_from(">H", data, at + 8)[0]


def is_dor(data: bytes) -> bool:
    return version(data) == VERSION_DOR


def _name(data: bytes, at: int) -> str:
    return data[at : at + NAME].split(b"\0", 1)[0].decode("latin-1", "replace")


def _table(data: bytes, at: int) -> tuple[int, int]:
    """A (count, pointer) pair, the pointer resolved to where its data starts."""
    count, ptr = struct.unpack_from(">2I", data, at)
    return count, ptr + BLOCK_SKIP


def _dor_materials(y: bytes, out: DorModel) -> None:
    count, at = _table(y, 0x18)
    ncount, nat = _table(y, 0x20)
    if ncount and nat + ncount * NAME <= len(y):
        out.names = [_name(y, nat + i * NAME) for i in range(ncount)]
    for i in range(min(count, MAX_GROUPS)):
        m = at + i * MATERIAL
        if m + MATERIAL > len(y):
            out.warnings.append("material table past the file")
            break
        diffuse = tuple(int(c) for c in y[m : m + 4])
        ptr = struct.unpack_from(">I", y, m + 16)[0] + BLOCK_SKIP
        textures: list[str] = []
        if ptr + 32 <= len(y):
            stages = struct.unpack_from(">H", y, ptr)[0]
            for k in range(min(stages, 16)):
                s = ptr + 32 + k * STAGE
                if s + STAGE > len(y):
                    break
                t = y[s + STAGE - 1]
                if t != NO_TEXTURE and t < len(out.names):
                    textures.append(out.names[t])
        out.materials.append(DorMaterial(diffuse, textures))


def _dor_bones(y: bytes, out: DorModel) -> None:
    count, at = _table(y, 0x10)
    for i in range(min(count, MAX_GROUPS)):
        b = at + i * BONE
        if b + BONE > len(y):
            out.warnings.append("bone table past the file")
            break
        parent = struct.unpack_from(">i", y, b + 16)[0]
        t = struct.unpack_from(">3f", y, b + 20)
        r = struct.unpack_from(">3f", y, b + 32)
        out.bones.append(DorBone(_name(y, b), parent, t, r))


def _dor_group(y: bytes, mesh: int, verts: np.ndarray, at: int, out: DorModel) -> bool:
    material, _n, strips, ptr = struct.unpack_from(">BBHI", y, at)
    p = ptr + BLOCK_SKIP
    corners: list[np.ndarray] = []
    tris: list[tuple[int, int, int]] = []
    base = 0
    for _ in range(strips):
        if p + 4 > len(y):
            return False
        n = struct.unpack_from(">I", y, p)[0]
        p += 4
        if not 1 <= n <= MAX_STRIP or p + n * CORNER_DOR > len(y):
            return False
        c = np.frombuffer(y, ">i2", n * 3, p).reshape(n, 3)
        if int(c[:, 0].max()) >= len(verts) or int(c[:, 0].min()) < 0:
            return False
        corners.append(c)
        p += n * CORNER_DOR
        for k in range(n - 2):
            a, b, cc = base + k, base + k + 1, base + k + 2
            # the stored normals want the opposite of the usual strip parity
            tris.append((b, a, cc) if k % 2 == 0 else (a, b, cc))
        base += n
    if not corners or not tris:
        return False
    raw = np.concatenate(corners)
    uniq, inverse = np.unique(raw, axis=0, return_inverse=True)
    tri = inverse.reshape(-1)[np.array(tris, np.int64)]
    idx = uniq[:, 0].astype(np.int64)
    positions = (verts[idx, :3] * POS_SCALE).astype(np.float32)
    normals = (verts[idx, 3:][:, NRM_ORDER] * NRM_SCALE).astype(np.float32)
    uvs = (uniq[:, 1:].astype(np.float32) * UV_SCALE_DOR).astype(np.float32)
    keep = tri[:, 0] != tri[:, 1]
    keep &= (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
    tri = tri[keep]
    if not len(tri):
        return False
    a, b, c = positions[tri[:, 0]], positions[tri[:, 1]], positions[tri[:, 2]]
    face = np.cross(b - a, c - a).astype(np.float64)
    length = np.linalg.norm(face, axis=1)
    ok = length > 1e-9
    agreement = 0.0
    if ok.any():
        vert = (normals[tri[ok, 0]] + normals[tri[ok, 1]] + normals[tri[ok, 2]]).astype(np.float64)
        agreement = float(((face[ok] / length[ok, None]) * vert).sum(1).mean() / 3)
    out.groups.append(
        DorGroup(mesh, material, positions, normals, uvs, tri.ravel().astype(np.uint32), agreement)
    )
    return True


def dor_model(data: bytes) -> DorModel | None:
    """A Day of Reckoning YOBJ: its groups (one per material), materials and bones."""
    at = yobj_at(data)
    if at < 0 or version(data) != VERSION_DOR:
        return None
    y = data[at:]
    size = struct.unpack_from(">I", y, 4)[0]
    if size <= len(y):
        y = y[:size]
    out = DorModel()
    out.meshes = struct.unpack_from(">H", y, 10)[0]
    _dor_bones(y, out)
    _dor_materials(y, out)
    for k in range(out.meshes):
        m = MESH_TABLE + k * MESH_RECORD
        if m + MESH_RECORD > len(y):
            out.warnings.append(f"mesh {k}: record past the file")
            break
        nverts = struct.unpack_from(">H", y, m)[0]
        groups = y[m + 6]
        marker, data_at, _z, _runs_at, groups_at = struct.unpack_from(">5I", y, m + 8)
        if marker != MARKER:
            out.warnings.append(f"mesh {k}: no {MARKER:#x} marker")
            continue
        data_at += BLOCK_SKIP
        groups_at += BLOCK_SKIP
        if nverts < MIN_COUNT or data_at + nverts * VERTEX_DOR > len(y):
            out.warnings.append(f"mesh {k}: {nverts} vertices past the file")
            continue
        verts = np.frombuffer(y, ">i2", nverts * 6, data_at).reshape(nverts, 6)
        for g in range(groups):
            at_g = groups_at + g * GROUP
            if at_g + GROUP > len(y) or not _dor_group(y, k, verts, at_g, out):
                out.warnings.append(f"mesh {k}: group {g} does not read")
    return out


def _strips(data: bytes, start: int, count: int) -> list[tuple[int, int, int]]:
    tris: list[tuple[int, int, int]] = []
    at = start
    while at + 4 <= len(data):
        n = struct.unpack_from(">I", data, at)[0]
        if not (MIN_COUNT <= n <= MAX_STRIP) or at + 4 + n * 2 > len(data):
            break
        ids = struct.unpack_from(f">{n}H", data, at + 4)
        if max(ids) >= count:
            break
        at += 4 + n * 2
        for k in range(n - 2):
            tris.append(
                (ids[k], ids[k + 1], ids[k + 2]) if k % 2 == 0 else (ids[k + 1], ids[k], ids[k + 2])
            )
    return tris


def _orient(positions, normals, tri):
    a, b, c = positions[tri[:, 0]], positions[tri[:, 1]], positions[tri[:, 2]]
    face = np.cross(b - a, c - a).astype(np.float64)
    length = np.linalg.norm(face, axis=1)
    keep = length > 1e-9
    if not keep.any():
        return None, 0.0, keep
    tri, face, length = tri[keep], face[keep], length[keep]
    face /= length[:, None]
    vert = (normals[tri[:, 0]] + normals[tri[:, 1]] + normals[tri[:, 2]]).astype(np.float64) / 3
    vlen = np.linalg.norm(vert, axis=1)
    vert[vlen > 0] /= vlen[vlen > 0][:, None]
    cos = (face * vert).sum(1)
    flip = cos < 0
    tri[flip] = tri[flip][:, ::-1]
    return tri, float(np.abs(cos).mean()), keep


def meshes(data: bytes) -> list[Mesh]:
    if not is_yobj(data[:4]):
        return []
    out: list[Mesh] = []
    for m in range(8, max(0, len(data) - 20), 4):
        if struct.unpack_from(">I", data, m)[0] != MARKER:
            continue
        count = struct.unpack_from(">H", data, m + COUNT_AT)[0]
        pos_at, nrm_at, idx_at = (
            struct.unpack_from(">I", data, m + o)[0] for o in (POS_AT, NRM_AT, IDX_AT)
        )
        if not (MIN_COUNT <= count <= MAX_COUNT):
            continue
        if not (0 < pos_at < nrm_at < idx_at < len(data)):
            continue
        if nrm_at - pos_at != count * STRIDE:
            continue
        if nrm_at + BLOCK_SKIP + count * STRIDE > len(data) or idx_at + INDEX_SKIP > len(data):
            continue
        normals = np.frombuffer(data, ">f4", count * 3, nrm_at + BLOCK_SKIP).reshape(count, 3)
        lengths = np.linalg.norm(normals.astype(np.float64), axis=1)
        if np.abs(lengths - 1.0).max() > UNIT_TOLERANCE:
            continue
        positions = np.frombuffer(data, ">f4", count * 3, pos_at + BLOCK_SKIP).reshape(count, 3)
        uvs = colors = groups = None
        xix = _xix_groups(data, idx_at, count)
        if xix is not None:
            tris, groups, uvs, colors = xix
        else:
            tris = _strips(data, idx_at + INDEX_SKIP, count)
        if not tris:
            continue
        tri_in = np.array(tris, np.int64)
        tri, agreement, keep = _orient(
            np.ascontiguousarray(positions),
            np.ascontiguousarray(normals),
            tri_in.copy(),
        )
        if tri is None:
            continue
        if groups is not None:
            # _orient drops zero-area triangles; keep the group ids of the survivors
            groups = [gid for gid, k in zip(groups, keep, strict=True) if k]
            if len(groups) != len(tri):
                groups = None
        out.append(
            Mesh(
                np.ascontiguousarray(positions, np.float32),
                np.ascontiguousarray(normals, np.float32),
                tri.ravel().astype(np.uint32),
                agreement,
                uvs,
                colors,
                groups,
            )
        )
    return out
