"""EA Sports EBO objects (EAGL 2005+: NHL 2005/06, NBA Live 2005/06, FIFA Soccer 05,
2006 FIFA World Cup, UEFA Champions League): a little-endian container around big-endian
GameCube payloads.

Layout: header (``EBO\\0``, version, size, data offset, four table offsets) | typed field
records + serialised objects | type-name table | import table | export table | string
table.  The type table names the serialised classes (``Geometry``, ``GcDisplayList``,
``GCVertexStream``, ``Float3``, ``Short2`` ... or, for animation banks, ``EaglAnim::*``),
the export table names the objects a file publishes (``Geometry "clothShape1ShapeShape"``,
987 ``SkelAnim`` clips in a body bank).  Geometry decoding is in :func:`geometry`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"EBO\0"
PRIM_OPS = {0x80, 0x90, 0x98, 0xA0}
UV_SCALE = 1.0 / 1024.0


class EboError(ValueError):
    pass


@dataclass
class Export:
    type: str
    name: str
    offset: int


@dataclass
class Record:
    at: int  # file offset of the record
    offset: int
    flag: int
    type: str
    count: int
    extra: int


@dataclass
class Ebo:
    version: int
    size: int
    data_off: int
    types: list[str]
    exports: list[Export]
    imports: list[int]
    records: list[Record]
    strings: dict[int, str]
    data: bytes = field(repr=False)


def is_ebo(head: bytes) -> bool:
    return len(head) >= 0x30 and head[:4] == MAGIC


def _cstr(tab: bytes, off: int) -> str:
    end = tab.find(b"\0", off)
    return tab[off : end if end >= 0 else len(tab)].decode("latin-1")


def parse(data: bytes) -> Ebo:
    if not is_ebo(data[:0x30]):
        raise EboError("not an EBO object")
    version, size, _a, _b, data_off, t_types, t_imp, t_exp, t_str = struct.unpack_from(
        "<IIHHIIIII", data, 4
    )
    n = len(data)
    if not (0x30 <= data_off <= t_types <= t_imp <= t_exp <= t_str <= n):
        raise EboError("table offsets out of order")
    strtab = data[t_str:]
    type_offs = struct.unpack_from(f"<{(t_imp - t_types) // 4}I", data, t_types)
    types = [_cstr(strtab, o) for o in type_offs]
    exports = []
    for i in range((t_str - t_exp) // 12):
        ty, name, off = struct.unpack_from("<III", data, t_exp + i * 12)
        exports.append(Export(_cstr(strtab, ty), _cstr(strtab, name), off & 0xFFFF))
    imports = list(struct.unpack_from(f"<{(t_exp - t_imp) // 4}I", data, t_imp))
    # typed field records: 16 bytes, type index into the table, small flag, plausible count
    records = []
    o = data_off
    while o + 16 <= t_types:
        off, flag, ty, count, extra = struct.unpack_from("<IHHII", data, o)
        if flag in (0, 1) and ty < len(types) and 0 < count < 1 << 24 and off < n and extra < 16:
            records.append(Record(o, off, flag, types[ty], count, extra))
        o += 4
    strings = {}
    o = 0
    while o < len(strtab):
        end = strtab.find(b"\0", o)
        if end < 0:
            break
        if end > o:
            strings[o] = strtab[o:end].decode("latin-1")
        o = end + 1
    return Ebo(version, size, data_off, types, exports, imports, records, strings, data)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


@dataclass
class Mesh:
    name: str
    positions: np.ndarray  # (N,3) f32
    indices: np.ndarray  # (M,) u32 triangles
    uvs: np.ndarray | None = None
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None


def _chain(buf: bytes, stride: int) -> tuple[list[tuple[int, int, int]], int]:
    """GX primitives (opcode, count, offset) at one stride; NOP padding allowed; stops at
    the first byte that is not a primitive.  Returns the primitives and the bytes used."""
    prims: list[tuple[int, int, int]] = []
    p, n = 0, len(buf)
    while p + 3 <= n:
        op = buf[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in PRIM_OPS:
            break
        count = (buf[p + 1] << 8) | buf[p + 2]
        if count == 0 or p + 3 + count * stride > n:
            break
        prims.append((op & 0xF8, count, p + 3))
        p += 3 + count * stride
    return prims, p


def _triangulate(prims, idx: np.ndarray) -> np.ndarray:
    from gcrip.formats.eagl import _triangulate as tri

    return tri(prims, idx)


@dataclass
class Stream:
    rec: Record
    data_off: int  # file offset of the bytes
    size: int
    stride: int  # from the 12-byte {size, stride, offset} header before the data (0 if none)


def _streams(obj: Ebo) -> list[Stream]:
    """Byte buffers of the file: ``i8`` records with flag 1, data at record + offset.  Real
    vertex streams carry a big-endian ``{size, stride, data offset}`` header right before
    the bytes; the display list's command buffer does not."""
    d = obj.data
    out = []
    for r in obj.records:
        if r.type != "i8" or r.flag != 1 or r.count < 64:
            continue
        off = r.at + r.offset
        if off + r.count > len(d):
            continue
        stride = 0
        if off >= 12:
            size, stride_, off_ = struct.unpack_from(">III", d, off - 12)
            if off_ == off and size == r.count and 1 <= stride_ <= 64:
                stride = stride_
        out.append(Stream(r, off, r.count, stride))
    return out


def _fields(rows: np.ndarray, stride: int) -> list[tuple[int, int, np.ndarray]]:
    """(byte offset, width, values) for every field of a vertex: u16 columns that look
    like indices (< 0x4000 and varying) and single u8 columns."""
    out = []
    k = 0
    while k < stride:
        if k + 1 < stride:
            v16 = (rows[:, k].astype(np.uint32) << 8) | rows[:, k + 1]
            if v16.max() < 0x4000 and len(np.unique(v16)) > 1:
                out.append((k, 2, v16))
                k += 2
                continue
        out.append((k, 1, rows[:, k].astype(np.uint32)))
        k += 1
    return out


def geometry(obj: Ebo) -> list[Mesh]:
    """Meshes of a geometry EBO.  Every ``GcDisplayList`` owns one command buffer (a GX
    strip list) and vertex streams (``Float3`` positions at stride 12, ``Short2`` UVs at
    stride 4, ...); a display-list vertex is a run of u16 (or u8) indices, one per stream,
    matched to the streams by index range."""
    if "GcDisplayList" not in obj.types:
        return []
    d = obj.data
    streams = _streams(obj)
    cmd = [s for s in streams if s.stride == 0]
    arrays = [s for s in streams if s.stride > 0]
    if not cmd or not arrays:
        return []
    names = [e.name for e in obj.exports if e.type == "Geometry"]
    meshes: list[Mesh] = []
    for mi, c in enumerate(cmd):
        # the command buffer may start with a small struct / padding: find the first opcode
        # whose chain (at some stride) consumes most of the buffer
        best = None
        for p in range(c.data_off, min(c.data_off + 0x60, len(d) - 3)):
            if (d[p] & 0xF8) not in PRIM_OPS or d[p + 1] != 0:
                continue
            for stride in range(2, 17):
                prims, used = _chain(d[p : c.data_off + c.size], stride)
                enough = prims and used >= (c.data_off + c.size - p) * 0.9
                if enough and (best is None or used > best[2]):
                    best = (p, stride, used, prims)
            if best is not None:
                break
        if best is None:
            continue
        p0, stride, used, prims = best
        dl = d[p0 : c.data_off + c.size]
        rows = np.concatenate(
            [np.frombuffer(dl, np.uint8, cnt * stride, o).reshape(cnt, stride)
             for _, cnt, o in prims]
        )
        fields = _fields(rows, stride)
        # the streams this list uses: those laid out after this command buffer and before
        # the next one
        nxt = min((x.data_off for x in cmd if x.data_off > c.data_off), default=len(d))
        mine = [s for s in arrays if c.data_off < s.data_off < nxt]
        pos_s = next((s for s in mine if s.stride == 12), None)
        if pos_s is None:
            continue
        nv = pos_s.size // 12
        pos = np.frombuffer(d, ">f4", nv * 3, pos_s.data_off).reshape(nv, 3).astype(np.float32)
        if not np.isfinite(pos).all():
            continue
        # position index = the u16 field whose max fits the position count, first such
        pidx = next((v for _, w, v in fields if w == 2 and v.max() < nv), None)
        if pidx is None:
            continue
        tri = _triangulate(prims, pidx)
        if len(tri) < 3:
            continue
        uvs = None
        uv_s = next((s for s in mine if s.stride == 4), None)
        if uv_s is not None:
            nuv = uv_s.size // 4
            uidx = next(
                (v for _, w, v in fields if w == 2 and v is not pidx and v.max() < nuv), None
            )
            if uidx is not None:
                uv_all = np.frombuffer(d, ">i2", nuv * 2, uv_s.data_off).reshape(nuv, 2)
                uv_all = uv_all.astype(np.float32) * UV_SCALE
                uvs = np.zeros((nv, 2), np.float32)
                uvs[pidx] = uv_all[uidx]
        normals = None
        n_s = next((s for s in mine if s.stride == 3), None)
        if n_s is not None:
            nn = n_s.size // 3
            nidx = next(
                (v for _, w, v in fields if v is not pidx and v.max() < nn
                 and (uvs is None or v is not uidx)),
                None,
            )
            if nidx is not None:
                n_all = np.frombuffer(d, np.int8, nn * 3, n_s.data_off).reshape(nn, 3)
                n_all = n_all.astype(np.float32) / 127.0
                normals = np.zeros((nv, 3), np.float32)
                normals[pidx] = n_all[nidx]
        name = names[mi] if mi < len(names) else (names[0] if names else "geometry")
        meshes.append(Mesh(f"{name}#{mi}" if len(cmd) > 1 else name, pos, tri, uvs, normals))
    return meshes
