"""EA Los Angeles' 2002 engine on the GameCube - Medal of Honor: Frontline ``.msh`` static
meshes and ``.cpt`` level compartments (inside ``level.viv`` / ``comp.viv``).

Read with the shipped ``Moh2RelGC.elf`` symbol table: ``CStaticMesh::Init`` and
``CCompartment::Init`` relocate every table (``offsetPtr<T>``), build the GX display-list
header in place and initialise the material textures from embedded ``SHPG`` shapes.  All
offsets are from the file start, big-endian.

``.msh`` (version 9)::

    u32 9, u32 file bytes, u32 materials A, u32 count, u32 materials B, u32 count,
    u32 chunks, u32 count, u32 nodes, u32 count, u32 attach nodes, u32 count
    material (0x70)  ... +0x60 SHPG shape offset, +0x64 flags
    chunk (0x20)     u32 node, u32 material, u32 data, ...
    data             u32 flags (bit 0: u8 indices, bit 2: strip), u32, u32, u32 vertices,
                     u32 positions (f32 xyz), u32 colours (RGBA8), u32 normals (s8 xyz),
                     u32 uvs (f32 st), u32 display list: 0x34 bytes of CP header the
                     game fills in, then vertices x (position, normal, colour, uv) as
                     u16 (or u8) indices

``.cpt`` (version 0x11)::

    u32 0x11, u32 file bytes, u32 materials A, u32 count, u32 materials B, u32 count,
    u32 chunks, u32 count, u32 nodes, u32 count, u32 texture swaps, u32 count
    chunk (0x14)     u32 node, u32, u32 material, u32 data, u32
    data             u16 flags (bit 0: u16 indices), u16 vertices, u32 positions,
                     u32 colours, u32 normals, u32 uvs (f32), u32 display list (as above,
                     strips only)

The ``_Art.cpt`` of a level holds the materials with no chunks; the geometry sits in the
``_c<n>.cpt`` compartments beside it, whose materials point back into the art file's
tables (+0x64 bit 1, index at +0x6c).  Positions are in level space already.  Both
material tables carry an embedded ``SHPG`` (``gcrip.formats.ea_shape``) at +0x60.

The 2003 / 2004 engine (Medal of Honor: Rising Sun, GoldenEye: Rogue Agent) keeps the file
names but wraps **EAGL** objects (``gcrip.formats.eagl``, the EA LA packet layout)::

    .msh (0x12)   u32 0x12, u32 file bytes, u32, u32, u32 ELF offset, u32 ELF bytes, ...,
                  +0x34 u32 hash: the ELF is ``.ord``-style (header + .data, no tables) and
                  its symbol / relocation tail is the entry of that hash in the level's
                  ``symbols.rtc`` (``TLT_GetRelocationTable`` -> ``CRtcFile``)
    .cpt (0x25)   u32 0x25, u32 file bytes, u32 SHPG offset, u32 SHPG bytes, ...; the
                  compartment's models are the ELFs embedded in the file, their tails the
                  entries 0, 1, ... of the ``<name>.rtc`` beside it
    .rtc          "RTC\0", u32, u32 2, u32 bytes, u32 count, u32 count, then count x
                  (u32 id, u32 offset, u32 bytes) sorted by id

Rising Sun's 5,141 ``.msh`` / 1,286 ``.cpt`` and GoldenEye's 1,264 / 172 are this shape.

Frontline's characters are ``.dmf`` cluster-skinned meshes drawn over a ``.skl`` skeleton
(``CDMesh::Init`` / ``BindSkeleton`` / ``DMClusterSynthesizeMatrices``), textured from the
level's ``.tpk`` (``TPAC``) packs - see the ``dmf`` section below.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import ea_shape, j3d

MSH_VERSION = 9
CPT_VERSION = 0x11
MATERIAL = 0x70
MSH_CHUNK = 0x20
CPT_CHUNK = 0x14
DL_HEADER = 0x34
MAX_COUNT = 1 << 16


class EalaError(ValueError):
    pass


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def _header_ok(head: bytes, size: int, version: int) -> bool:
    if len(head) < 48 or size < 48:
        return False
    w = struct.unpack_from(">12I", head, 0)
    if w[0] != version or w[1] != size:
        return False
    for ptr, count in zip(w[2::2], w[3::2], strict=True):
        if count > MAX_COUNT or (count and (ptr < 48 or ptr >= size)):
            return False
    return w[3] + w[5] + w[7] + w[9] > 0


def is_msh(head: bytes, size: int) -> bool:
    return _header_ok(head, size, MSH_VERSION)


def is_cpt(head: bytes, size: int) -> bool:
    return _header_ok(head, size, CPT_VERSION)


@dataclass
class Material:
    shape: int  # SHPG offset, 0 for none
    flags: int
    table: int = 0  # 0: the A table, 1: the B table
    shared: int | None = None  # flags bit 1: index into the level's ``_Art.cpt`` same table


@dataclass
class Chunk:
    material: int  # index into materials (A then B)
    positions: np.ndarray
    triangles: np.ndarray
    normals: np.ndarray | None
    colors: np.ndarray | None
    uvs: np.ndarray | None


@dataclass
class Model:
    materials: list[Material]
    chunks: list[Chunk]
    warnings: list[str] = field(default_factory=list)


def _materials(d: bytes, w: tuple) -> tuple[list[Material], dict[int, int]]:
    mats: list[Material] = []
    index: dict[int, int] = {}
    for t, (table, count) in enumerate(((w[2], w[3]), (w[4], w[5]))):
        for i in range(count):
            m = table + MATERIAL * i
            if m + MATERIAL > len(d):
                break
            index[m] = len(mats)
            flags = _u32(d, m + 0x64)
            shared = _u32(d, m + 0x6C) if flags & 2 else None
            mats.append(Material(_u32(d, m + 0x60), flags, t, shared))
    return mats, index


def _decode(d: bytes, data: int, msh: bool, warn: list[str]) -> tuple | None:
    if msh:
        flags, _, _, nverts = struct.unpack_from(">4I", d, data)
        pos, clr, nrm, uv, dl = struct.unpack_from(">5I", d, data + 0x10)
        wide = not flags & 1
        strip = bool(flags & 4)
    else:
        flags, nverts = struct.unpack_from(">HH", d, data)
        pos, clr, nrm, uv, dl = struct.unpack_from(">5I", d, data + 4)
        wide = bool(flags & 1)
        strip = True
    if nverts < 3:
        return None  # legitimate: nothing to draw
    corners = dl + DL_HEADER
    width = 8 if wide else 4
    if corners + nverts * width > len(d):
        warn.append(f"chunk at {data:#x}: display list past the file")
        return None
    v = np.frombuffer(d, ">u2" if wide else "u1", nverts * 4, corners).reshape(nverts, 4)
    v = v.astype(np.int64)
    tri = j3d.triangulate(0x98 if strip else 0x90, nverts)

    def array(ptr: int, col: int, dtype: str, n: int, scale: float) -> np.ndarray | None:
        if not ptr:
            return None  # legitimate: the attribute is absent
        count = int(v[:, col].max()) + 1
        size = np.dtype(dtype).itemsize * n
        if ptr + count * size > len(d):
            warn.append(f"chunk at {data:#x}: array past the file")
            return None
        arr = np.frombuffer(d, dtype, count * n, ptr).reshape(count, n)
        return (arr.astype(np.float32) / scale if scale else arr.copy())[v[:, col]]

    p = array(pos, 0, ">f4", 3, 1.0)
    if p is None:
        warn.append(f"chunk at {data:#x}: no positions")
        return None
    normals = array(nrm, 1, "i1", 3, 64.0)
    colors = array(clr, 2, "u1", 4, 0)
    uvs = array(uv, 3, ">f4", 2, 1.0)
    a, b, c = p[tri[:, 0]], p[tri[:, 1]], p[tri[:, 2]]
    good = ~(np.all(a == b, axis=1) | np.all(b == c, axis=1) | np.all(a == c, axis=1))
    return p, tri[good], normals, colors, uvs


def parse(d: bytes) -> Model:
    """A .msh or .cpt file."""
    w = struct.unpack_from(">12I", d, 0)
    msh = w[0] == MSH_VERSION
    if not msh and w[0] != CPT_VERSION:
        raise EalaError(f"version {w[0]}")
    mats, index = _materials(d, w)
    model = Model(mats, [])
    chunks, count = w[6], w[7]
    stride = MSH_CHUNK if msh else CPT_CHUNK
    for i in range(min(count, MAX_COUNT)):
        ch = chunks + stride * i
        if ch + stride > len(d):
            break
        if msh:
            _node, mat, data = struct.unpack_from(">3I", d, ch)
        else:
            _node, _x, mat, data = struct.unpack_from(">4I", d, ch)
        if not data or data + 0x28 > len(d):
            continue
        try:
            out = _decode(d, data, msh, model.warnings)
        except (struct.error, ValueError) as e:
            model.warnings.append(f"chunk {i}: {e}")
            continue
        if out is None:
            continue
        model.chunks.append(Chunk(index.get(mat, -1), *out))
    return model


def material_texture(d: bytes, m: Material) -> np.ndarray | None:
    """The first image of a material's embedded SHPG, or None."""
    if not m.shape or m.shape + 16 > len(d) or not ea_shape.is_shape(d[m.shape : m.shape + 16]):
        return None
    for img in ea_shape.parse(d[m.shape :]):
        if img.rgba is not None:
            return img.rgba
    return None


# ---------------------------------------------------------------------------
# 2003-04: EAGL objects wrapped in .msh (0x12) / .cpt (0x25), tails in .rtc files
# ---------------------------------------------------------------------------

MSH_EAGL_VERSION = 0x12
CPT_EAGL_VERSION = 0x25
RTC_MAGIC = b"RTC\0"
ELF_MAGIC = b"\x7fELF"


def is_eagl_msh(head: bytes, size: int) -> bool:
    if len(head) < 0x38 or size < 0x38:
        return False
    w = struct.unpack_from(">6I", head, 0)
    return (
        w[0] == MSH_EAGL_VERSION
        and w[1] == size
        and 0x40 <= w[4] < size
        and w[5] >= 0x34
        and w[4] + w[5] <= size
    )


def is_eagl_cpt(head: bytes, size: int) -> bool:
    if len(head) < 16 or size < 16:
        return False
    w = struct.unpack_from(">4I", head, 0)
    return w[0] == CPT_EAGL_VERSION and w[1] == size and w[2] + w[3] <= size


def is_rtc(head: bytes) -> bool:
    return head[:4] == RTC_MAGIC


def rtc_tables(data: bytes) -> dict[int, bytes]:
    """id -> ELF tail (section-name / symbol / relocation tables plus section headers)."""
    if not is_rtc(data) or len(data) < 0x18:
        return {}
    count = _u32(data, 0x10)
    out: dict[int, bytes] = {}
    for i in range(min(count, MAX_COUNT)):
        at = 0x18 + 12 * i
        if at + 12 > len(data):
            break
        ident, off, size = struct.unpack_from(">3I", data, at)
        if off + size <= len(data) and size:
            out[ident] = data[off : off + size]
    return out


def _with_tail(elf: bytes, tail: bytes | None) -> bytes:
    """The wrapped ELF is the front of the object; its tables follow in the .rtc entry and
    the section headers sit at the very end, so the join is a plain append."""
    return elf + tail if tail else elf


def eagl_msh_object(data: bytes, tables: dict[int, bytes]) -> bytes:
    w = struct.unpack_from(">6I", data, 0)
    ident = _u32(data, 0x34)
    return _with_tail(data[w[4] : w[4] + w[5]], tables.get(ident))


def eagl_cpt_objects(data: bytes, tables: dict[int, bytes]) -> list[bytes]:
    """Every ELF embedded in a version-0x25 compartment, joined with the tail of the same
    index; the ELF's length is what the section-header offset leaves after the tail."""
    out: list[bytes] = []
    p = 0
    while True:
        p = data.find(ELF_MAGIC, p)
        if p < 0 or p + 0x34 > len(data):
            break
        e_shoff = struct.unpack_from("<I", data, p + 0x20)[0]
        e_shentsize, e_shnum = struct.unpack_from("<HH", data, p + 0x2E)
        tail = tables.get(len(out))
        n = e_shoff + e_shnum * e_shentsize - (len(tail) if tail else 0)
        if n < 0x34 or p + n > len(data):
            break
        out.append(_with_tail(data[p : p + n], tail))
        p += n
    return out


def cpt_shapes(data: bytes) -> bytes | None:
    """The SHPG bundle embedded in a version-0x25 file (a level's ``_Art.cpt`` carries the
    level textures), or None."""
    w = struct.unpack_from(">4I", data, 0)
    if w[0] != CPT_EAGL_VERSION or not w[3] or w[2] + w[3] > len(data):
        return None
    blob = data[w[2] : w[2] + w[3]]
    return blob if ea_shape.is_shape(blob[:16]) else None


# ---------------------------------------------------------------------------
# Frontline characters: .dmf cluster-skinned meshes, .skl skeletons, .tpk texture packs
# ---------------------------------------------------------------------------
#
# ``.dmf`` (``"DMF\0"``, version 0x06010003 big-endian; the 0x05010000 files are the PS2
# layout the disc still carries) is a fixed header of offsets from the file start
# (``CDMesh::Init`` relocates every one by adding the base)::
#
#     +0x0c name (16)     +0x20 clusters count, +0x24 table of u8 bone, u8 parent bone,
#     u16 weight / 4096   +0x28 render objects count, +0x2c table (0x38 each: +0x28 texture
#     index, +0x2c part count, +0x30 parts, +0x34 display lists)
#     +0x30 texture names count, +0x34 table (16 each)   +0x48 bone names count, +0x4c
#     table (16 each)   +0x50 bone rest angles (s16 xyz, 65536 a turn)
#     +0x5c/+0x60 positions s16 xyz (14 fraction bits)   +0x64/+0x68 normals s16 xyz
#     +0x6c/+0x70 texcoords s16 st (14 fraction bits)
#     part (18): u32 display list, u16 size / 32, u16 bone count, u8 cluster x 10
#     display list: GX strips of 7-byte corners: u8 matrix slot (3 x the part's cluster
#     index), u16 position, u16 normal, u16 texcoord
#
# A cluster is a frame between a bone and its parent (``DMClusterSynthesizeMatrices``: the
# parent's world matrix, rotated by the bone's angles blended towards the pose by the
# weight, at the parent's position); at rest the pose equals the rest angles, so a cluster
# is ``world[parent] x rot_yzx(rest[bone])`` at ``world[parent]``'s origin.  The skeleton
# (``.skl``, ``"1LKS"``, little-endian: u16 bones at +6, u32 name table at +0xc; records at
# +0x20 of f32 xyz + i32 depth) is walked depth-first (``DMClusterSkelTraverseHeirarchy``)
# with the same rotation, angles taken from the mesh's rest table by bone name.
# ``_matrix_rot_yzx`` rotates a right / front / up row matrix about its own front (y), up
# (z), then right (x) axes; angles are s16 turns / 65536 (the ELF converts with 2 pi / 65536).
#
# ``.tpk`` (``"TPAC"``, u32 count, u32 name width 16, u32 table offset; names, then u32
# entry offsets, each entry's first word the offset of its ``SHPG``) supplies the textures
# by name.

DMF_MAGIC = b"DMF\0"
DMF_VERSION = 0x06010003
DMF_VERSION_PS2 = 0x05010000
SKL_MAGIC = b"1LKS"
TPK_MAGIC = b"TPAC"
DMF_POS_SCALE = 1.0 / 16384.0
DMF_UV_SCALE = 1.0 / 16384.0
DMF_PART = 18
DMF_OBJECT = 0x38
DMF_CORNER = 7


def is_dmf(head: bytes) -> bool:
    return (
        len(head) >= 8 and head[:4] == DMF_MAGIC and _u32(head, 4) in (DMF_VERSION, DMF_VERSION_PS2)
    )


def is_skl(head: bytes) -> bool:
    return len(head) >= 8 and head[:4] == SKL_MAGIC


def is_tpk(head: bytes) -> bool:
    return len(head) >= 16 and head[:4] == TPK_MAGIC and _u32(head, 8) == 16


def rot_yzx(m: np.ndarray, ax: float, ay: float, az: float) -> np.ndarray:
    """``_matrix_rot_yzx``: the row matrix (right, front, up) rotated about its own axes -
    front (y) by ``ay``, then up (z) by ``az``, then right (x) by ``ax``; angles in turns /
    65536."""
    k = 2.0 * np.pi / 65536.0
    sx, cx = np.sin(ax * k), np.cos(ax * k)
    sy, cy = np.sin(ay * k), np.cos(ay * k)
    sz, cz = np.sin(az * k), np.cos(az * k)
    right, front, up = m[0], m[1], m[2]
    a = cy * right - sy * up
    c = cy * up + sy * right
    b = cz * front - sz * a
    a2 = cz * a + sz * front
    return np.array([a2, cx * b + sx * c, cx * c - sx * b], np.float32)


@dataclass
class Skeleton:
    names: list[str]
    records: list[tuple[float, float, float, int]]  # local translation, depth

    def world(self, angles: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
        """(rotation rows, position) per joint, walked depth-first with a matrix stack."""
        out: list[tuple[np.ndarray, np.ndarray]] = []
        stack: list[tuple[np.ndarray, np.ndarray]] = []
        for j, (x, y, z, depth) in enumerate(self.records):
            while len(stack) > depth + 1:
                stack.pop()
            rot, pos = (
                stack[-1] if stack else (np.eye(3, dtype=np.float32), np.zeros(3, np.float32))
            )
            p = np.array([x, y, z], np.float32) @ rot + pos
            rot2 = rot_yzx(rot, *angles[j])
            stack.append((rot2, p))
            out.append((rot2, p))
        return out


def parse_skl(d: bytes) -> Skeleton:
    if not is_skl(d[:8]):
        raise EalaError("not a skeleton")
    n = struct.unpack_from("<H", d, 6)[0]
    names_at = struct.unpack_from("<I", d, 0xC)[0]
    if n > MAX_COUNT or 0x20 + 16 * n > len(d) or names_at + 20 * n > len(d):
        raise EalaError("skeleton tables past the file")
    records = [struct.unpack_from("<3fi", d, 0x20 + 16 * i) for i in range(n)]
    names = [
        d[names_at + 20 * i + 4 : names_at + 20 * i + 20].split(b"\0")[0].decode("latin-1")
        for i in range(n)
    ]
    return Skeleton(names, records)


@dataclass
class DmfPart:
    texture: str
    positions: np.ndarray
    triangles: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray


@dataclass
class DmfModel:
    name: str
    bones: list[str]
    parts: list[DmfPart]
    warnings: list[str] = field(default_factory=list)


def _names(d: bytes, at: int, count: int) -> list[str]:
    return [
        d[at + 16 * i : at + 16 * i + 16].split(b"\0")[0].decode("latin-1") for i in range(count)
    ]


def _dmf_corners(d: bytes, dl: int, end: int) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    p, rows, prims = dl, [], []
    while p + 3 <= end:
        op = d[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in (0x80, 0x90, 0x98, 0xA0):
            break
        count = (d[p + 1] << 8) | d[p + 2]
        if count == 0 or p + 3 + count * DMF_CORNER > len(d):
            break
        prims.append((op & 0xF8, count, len(rows)))
        rows += [struct.unpack_from(">BHHH", d, p + 3 + DMF_CORNER * i) for i in range(count)]
        p += 3 + count * DMF_CORNER
    return np.array(rows, np.int64).reshape(-1, 4), prims


def parse_dmf(d: bytes, skeleton: Skeleton | None) -> DmfModel:
    """The mesh in its rest pose over ``skeleton`` (bone space with the skeleton's clusters
    at the origin when None)."""
    if not is_dmf(d[:8]):
        raise EalaError("not a DMF")
    if _u32(d, 4) != DMF_VERSION:
        raise EalaError("PS2 layout (version 0x05010000)")
    w = struct.unpack_from(">32I", d, 0)
    model = DmfModel(d[0xC:0x1C].split(b"\0")[0].decode("latin-1"), [], [])
    n_cl, p_cl = w[0x20 // 4], w[0x24 // 4]
    n_obj, p_obj = w[0x28 // 4], w[0x2C // 4]
    n_tex, p_tex = w[0x30 // 4], w[0x34 // 4]
    n_bone, p_bone, p_rest = w[0x48 // 4], w[0x4C // 4], w[0x50 // 4]
    n_pos, p_pos, n_nrm, p_nrm, n_uv, p_uv = w[0x5C // 4 : 0x74 // 4]
    for count, at, size in (
        (n_cl, p_cl, 4), (n_obj, p_obj, DMF_OBJECT), (n_tex, p_tex, 16), (n_bone, p_bone, 16),
        (n_bone, p_rest, 6), (n_pos, p_pos, 6), (n_nrm, p_nrm, 6), (n_uv, p_uv, 4),
    ):  # fmt: skip
        if count > MAX_COUNT or at + count * size > len(d):
            raise EalaError("DMF tables past the file")
    model.bones = _names(d, p_bone, n_bone)
    textures = _names(d, p_tex, n_tex)
    rest = np.frombuffer(d, ">i2", n_bone * 3, p_rest).reshape(n_bone, 3).astype(np.int32)
    pos = np.frombuffer(d, ">i2", n_pos * 3, p_pos).reshape(n_pos, 3).astype(np.float32)
    pos *= DMF_POS_SCALE
    nrm = np.frombuffer(d, ">i2", n_nrm * 3, p_nrm).reshape(n_nrm, 3).astype(np.float32) / 32767.0
    uv = np.frombuffer(d, ">i2", n_uv * 2, p_uv).reshape(n_uv, 2).astype(np.float32) * DMF_UV_SCALE
    # cluster frames at rest: the parent joint's world frame turned by the bone's rest angles
    joint = [-1] * n_bone
    world: list[tuple[np.ndarray, np.ndarray]] = []
    if skeleton is not None:
        joint = [skeleton.names.index(n) if n in skeleton.names else -1 for n in model.bones]
        angles = np.zeros((len(skeleton.records), 3), np.int32)
        for i, j in enumerate(joint):
            if j >= 0:
                angles[j] = rest[i]
        world = skeleton.world(angles)
        missing = [n for n, j in zip(model.bones, joint, strict=True) if j < 0]
        if missing:
            model.warnings.append(f"{len(missing)} bones not in the skeleton: {missing[:4]}")
    identity = (np.eye(3, dtype=np.float32), np.zeros(3, np.float32))
    clusters = []
    for i in range(n_cl):
        bone, parent, _weight = struct.unpack_from(">BBH", d, p_cl + 4 * i)
        rot, at = identity
        j = joint[parent] if parent < n_bone else -1
        if j >= 0:
            rot, at = world[j]
        if bone < n_bone:
            rot = rot_yzx(rot, *rest[bone])
        clusters.append((rot, at))
    morphs = 0
    for k in range(n_obj):
        o = p_obj + DMF_OBJECT * k
        tex, n_part, p_part, _ = struct.unpack_from(">4I", d, o + 0x28)
        if n_part > MAX_COUNT or p_part + n_part * DMF_PART > len(d):
            model.warnings.append(f"object {k}: parts past the file")
            continue
        for r in range(n_part):
            rec = d[p_part + DMF_PART * r : p_part + DMF_PART * (r + 1)]
            dl, size, n_b = struct.unpack_from(">IHH", rec, 0)
            part_clusters = list(rec[8 : 8 + min(n_b, 10)])
            if dl >= len(d):
                model.warnings.append(f"object {k} part {r}: display list past the file")
                continue
            rows, prims = _dmf_corners(d, dl, min(len(d), dl + size * 32))
            if not len(rows):
                # the heads' morph targets (DMMorphObject: u16 index, s16 delta pairs) sit in
                # objects of the same shape; they are not geometry
                morphs += 1
                continue
            if rows[:, 1].max() >= n_pos or rows[:, 2].max() >= n_nrm or rows[:, 3].max() >= n_uv:
                model.warnings.append(f"object {k} part {r}: corner index outside the arrays")
                continue
            p = pos[rows[:, 1]].copy()
            n = nrm[rows[:, 2]].copy()
            slots = rows[:, 0] // 3
            for c in np.unique(slots):
                if c >= len(part_clusters) or part_clusters[c] >= len(clusters):
                    continue
                rot, at = clusters[part_clusters[c]]
                sel = slots == c
                p[sel] = p[sel] @ rot + at
                n[sel] = n[sel] @ rot
            tri = j3d_triangles(prims)
            name = textures[tex] if tex < n_tex else f"texture_{tex}"
            model.parts.append(DmfPart(name, p, tri, n, uv[rows[:, 3]]))
    if morphs:
        model.warnings.append(f"{morphs} morph-target objects skipped")
    return model


def j3d_triangles(prims: list[tuple[int, int, int]]) -> np.ndarray:
    tris = []
    for op, count, start in prims:
        t = j3d.triangulate(op, count)
        if len(t):
            tris.append(t + start)
    return np.concatenate(tris) if tris else np.zeros((0, 3), np.int64)


def tpk_shapes(d: bytes) -> dict[str, bytes]:
    """upper-case texture name -> SHPG bytes of a TPAC pack."""
    if not is_tpk(d[:16]):
        return {}
    count, _width, table = struct.unpack_from(">3I", d, 4)
    if count > MAX_COUNT or table + 4 * count > len(d) or 16 + 16 * count > table:
        return {}
    out: dict[str, bytes] = {}
    for i, name in enumerate(_names(d, 16, count)):
        entry = _u32(d, table + 4 * i)
        if entry + 4 > len(d):
            continue
        at = _u32(d, entry)
        if at + 16 <= len(d) and ea_shape.is_shape(d[at : at + 16]):
            out.setdefault(name.upper(), d[at:])
    return out
