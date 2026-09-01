"""The ``.gc`` resource files - Teen Titans, Monster House, Ed Edd n Eddy, The Ant Bully and
Happy Feet.  Five discs that produced nothing at all, and no note anywhere on the format.

The same engine ships the files raw as ``.gc`` on four discs and zlib-compressed as ``.cp`` on
Happy Feet (:func:`decompress`).  ``.as``, ``.sbk`` and ``.str`` on these discs are audio -
cutscene streams, sound banks and music - and they are most of the bytes, which is what an
extension census points at first.

Big-endian throughout::

    +0    u32 version        0x0301081f (Teen Titans) / 0x03020bc2 (Monster House)
    +16   char name[12]      "ppdusk", "lu_ch10"
    +28   char project[16]   "tt06", "mhouse"
    +56   char "Build"
    +64   256 slots of 8 bytes: u32 count, u32 offset (0xffffffff when the type is absent)
    +2112 the payloads

**A slot's index is the resource type.**  Each populated slot points at ``count`` entries of
``u32 handle, u32 offset``, where the handle is ``(type << 24) | (file id << 8) | index`` - its
top byte repeats the slot index and its middle two bytes are constant per file, which is what
confirms the reading.  ``0xfffffffb`` means the resource has no payload.

A resource is a guard word, the file version, a subtype, its handle, a 32-byte name and a
sixteen-byte ``0xef`` guard, then the payload.  Everything is named, so meshes come out under
the artists' own names: ``barrel_explosif``, ``slade_minion_ref``, ``sentry_turret_ref``.

Geometry is an ordinary **GX indexed triangle strip**, which ``gxscan`` cannot find because the
vertex array lives elsewhere in the resource and the scanner has nothing to point it at.  The
mesh header is::

    u32 vertex count
    u32 0xffffffff        a sentinel
    u32 vertex array offset
    ... 40 bytes
    u32 display list start
    u32 display list end

and the vertex is 56 bytes: ``f32 x,y,z``, ``RGBA8`` colour, ``f32 nx,ny,nz``, ``f32 u,v``.
The display list is ``0x98 | u16 count | count * 8``, each vertex four ``u16`` attribute indices
(position, normal, colour, texcoord - equal on every vertex seen, so the array is unified).

**Four independent checks place a mesh**, none of which is the winding metric used to judge the
result afterwards: every stored normal is unit length (mean 0.9999, standard deviation 0.0000),
the display list walks to its declared end give or take zero padding, every index is inside the
vertex count, and the list references **every** vertex.  On Teen Titans' ``ppdusk.gc`` that
finds 49 meshes in 972 resources and never fires on the other 21 resource types.

**The winding is not consistent**, exactly as in Terminal Reality's ``_smf``.  Raw, the face
normals agree with the stored ones at a mean cosine of 0.41 - which reads like half the meshes
being wrong until you take the absolute value, where it is **0.90 to 1.00 on all 49**.  The
triangles are right and their orientation is not, so each one is flipped to agree with its own
stored normals.  That makes the signed agreement 1.0 by construction, so the honest figure to
quote is the unsigned one *before* the flip.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

MAGIC_AT = 56
MAGIC = b"Build"
NAME_AT = 16
NAME_LEN = 12
TABLE_AT = 64
SLOTS = 256
SLOT = 8
NO_TYPE = 0xFFFFFFFF
NO_PAYLOAD = 0xFFFFFFFB
RES_NAME_AT = 16
RES_NAME_LEN = 32
STRIDE = 56
COLOUR_AT = 12
NORMAL_AT = 16
UV_AT = 28
SENTINEL = 0xFFFFFFFF
DL_AT = 52
STRIP_OP = 0x98
INDEX_STRIDE = 8
PAD_BYTES = (0x00, 0xEF)
MAX_PAD = 32
MAX_VERTICES = 1 << 16
MIN_STRIP = 3
ZLIB_FLAGS = (0x01, 0x5E, 0x9C, 0xDA)
BLOCK = 53248  # what one .cp block inflates to


@dataclass
class Resource:
    kind: int
    index: int
    name: str
    offset: int
    size: int


@dataclass
class Mesh:
    name: str
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    colours: np.ndarray
    indices: np.ndarray
    unsigned_agreement: float


def is_gc(head: bytes) -> bool:
    """``Build`` sits at +56, so the whole signature is inside the 64 bytes classify sniffs."""
    if len(head) < TABLE_AT or head[MAGIC_AT : MAGIC_AT + len(MAGIC)] != MAGIC:
        return False
    name = head[NAME_AT : NAME_AT + NAME_LEN]
    return bool(name.split(b"\x00", 1)[0]) and all(c == 0 or 32 <= c < 127 for c in name)


def is_cp(head: bytes) -> bool:
    """Happy Feet's ``.cp``: a u32 size then a chain of zlib streams."""
    return len(head) >= 6 and head[4] == 0x78 and head[5] in ZLIB_FLAGS


def decompress(data: bytes, limit: int = 256 << 20) -> bytes | None:
    """Inflate the block chain: ``u32 compressed size`` then a zlib stream, repeated.

    Each block inflates to :data:`BLOCK` bytes bar the last.  Reading it as one continuous
    chain instead - letting each stream end and starting the next where it stopped - recovers
    only the first block, because the four-byte size of the next block sits in between.  That
    still yields a valid-looking file header, so it fails quietly: `dr_final.cp` gives 53,248
    bytes that pass every header check and contain no meshes, rather than 4,712,576 that do.
    """
    if not is_cp(data[:8]):
        return None
    out = bytearray()
    at = 0
    while at + 4 <= len(data) and len(out) < limit:
        size = struct.unpack_from(">I", data, at)[0]
        if size == 0 or at + 4 + size > len(data):
            break
        try:
            out += zlib.decompress(data[at + 4 : at + 4 + size])
        except zlib.error:
            break
        at += 4 + size
    return bytes(out) or None


def resources(data: bytes) -> list[Resource]:
    """Every named resource, with the span each one occupies."""
    if not is_gc(data[:TABLE_AT]):
        return []
    found: list[Resource] = []
    for kind in range(SLOTS):
        at = TABLE_AT + kind * SLOT
        if at + SLOT > len(data):
            break
        count, where = struct.unpack_from(">2I", data, at)
        if where == NO_TYPE or count == 0 or where + count * SLOT > len(data):
            continue
        for i in range(count):
            handle, offset = struct.unpack_from(">2I", data, where + i * SLOT)
            if offset in (NO_PAYLOAD, 0) or offset + RES_NAME_AT >= len(data):
                continue
            if handle >> 24 != kind:  # the handle repeats its own slot index
                continue
            raw = data[offset + RES_NAME_AT : offset + RES_NAME_AT + RES_NAME_LEN]
            name = raw.split(b"\x00", 1)[0].decode("latin-1", "replace")
            found.append(Resource(kind, i, name, offset, 0))
    # a resource runs to the next payload; the last runs to the end of the file
    edges = sorted({r.offset for r in found} | {len(data)})
    nxt = dict(zip(edges, edges[1:], strict=False))
    for r in found:
        r.size = nxt.get(r.offset, len(data)) - r.offset
    return found


def _strips(rec: bytes, dl0: int, dl1: int) -> list[list[int]] | None:
    out: list[list[int]] = []
    at = dl0
    while at + 3 <= dl1 and rec[at] == STRIP_OP:
        count = struct.unpack_from(">H", rec, at + 1)[0]
        at += 3
        if count < MIN_STRIP or at + count * INDEX_STRIDE > dl1:
            return None
        out.append([struct.unpack_from(">H", rec, at + i * INDEX_STRIDE)[0] for i in range(count)])
        at += count * INDEX_STRIDE
    tail = rec[at:dl1]
    if not out or len(tail) > MAX_PAD or any(c not in PAD_BYTES for c in tail):
        return None
    return out


def _orient(positions, normals, tri):
    """Drop degenerate triangles and flip the rest to agree with their own stored normals.

    Returns the unsigned agreement measured *before* flipping; after it the signed figure is
    1.0 by construction and means nothing.
    """
    a, b, c = positions[tri[:, 0]], positions[tri[:, 1]], positions[tri[:, 2]]
    face = np.cross(b - a, c - a).astype(np.float64)
    length = np.linalg.norm(face, axis=1)
    keep = length > 1e-9
    if not keep.any():
        return None, 0.0
    tri, face, length = tri[keep], face[keep], length[keep]
    face /= length[:, None]
    vert = (normals[tri[:, 0]] + normals[tri[:, 1]] + normals[tri[:, 2]]).astype(np.float64) / 3
    vlen = np.linalg.norm(vert, axis=1)
    vert[vlen > 0] /= vlen[vlen > 0][:, None]
    cos = (face * vert).sum(1)
    flip = cos < 0
    tri[flip] = tri[flip][:, ::-1]
    return tri, float(np.abs(cos).mean())


def meshes(rec: bytes, name: str = "mesh") -> list[Mesh]:
    """Mesh headers are not at a fixed offset, so each is found by its own shape and then
    confirmed against the data it points at - see the module docstring."""
    out: list[Mesh] = []
    for p in range(4, max(0, len(rec) - DL_AT - 8), 4):
        if struct.unpack_from(">I", rec, p)[0] != SENTINEL:
            continue
        count = struct.unpack_from(">I", rec, p - 4)[0]
        vat = struct.unpack_from(">I", rec, p + 4)[0]
        if not (MIN_STRIP <= count < MAX_VERTICES) or vat < TABLE_AT:
            continue
        if vat + count * STRIDE > len(rec):
            continue
        dl0, dl1 = struct.unpack_from(">2I", rec, p + DL_AT - 4)
        if not (TABLE_AT < dl0 < dl1 <= len(rec)):
            continue
        strips = _strips(rec, dl0, dl1)
        if strips is None:
            continue
        arr = np.frombuffer(rec, ">f4", count * (STRIDE // 4), vat).reshape(count, STRIDE // 4)
        normals = np.ascontiguousarray(arr[:, NORMAL_AT // 4 : NORMAL_AT // 4 + 3], np.float32)
        lengths = np.linalg.norm(normals.astype(np.float64), axis=1)
        if not (lengths.min() > 0.95 and lengths.std() < 0.01):
            continue
        faces = []
        for ids in strips:
            for k in range(len(ids) - 2):
                faces.append(
                    (ids[k], ids[k + 1], ids[k + 2])
                    if k % 2 == 0
                    else (ids[k + 1], ids[k], ids[k + 2])
                )
        tri = np.array(faces, np.int64)
        if tri.max() >= count or len(set(tri.ravel().tolist())) != count:
            continue
        positions = np.ascontiguousarray(arr[:, :3], np.float32)
        uvs = np.ascontiguousarray(arr[:, UV_AT // 4 : UV_AT // 4 + 2], np.float32)
        raw = np.frombuffer(rec, np.uint8, count * STRIDE, vat).reshape(count, STRIDE)
        colours = raw[:, COLOUR_AT : COLOUR_AT + 4].astype(np.float32) / 255.0
        tri, agreement = _orient(positions, normals, tri)
        if tri is None:
            continue
        out.append(
            Mesh(name, positions, normals, uvs, colours, tri.ravel().astype(np.uint32), agreement)
        )
    return out
