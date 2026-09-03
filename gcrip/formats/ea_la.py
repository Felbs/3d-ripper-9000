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
