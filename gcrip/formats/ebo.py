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
    joints: np.ndarray | None = None  # (N,4) u16 skeleton bone indices (skinned lists)
    weights: np.ndarray | None = None  # (N,4) f32


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
    rec: Record | None
    data_off: int  # file offset of the bytes
    size: int
    stride: int  # from the 12-byte {size, stride, offset} header before the data (0 if none)


KNOWN_STRIDES = {2, 3, 4, 6, 8, 12, 16}


def _streams(obj: Ebo) -> list[Stream]:
    """Vertex streams of the file: every 12-byte big-endian ``{size, stride, data
    offset}`` header whose offset points right after itself (NHL 2005 references them
    through ``i8`` records, NBA Live 2005 through typed ``Short3``/``Short2`` records;
    the header is the same)."""
    d = obj.data
    out = []
    hi = min(len(d) - 12, obj.data_off + (len(d) - obj.data_off))
    words = np.frombuffer(d, ">u4", (hi - obj.data_off) // 4, obj.data_off)
    base = obj.data_off
    cand = np.flatnonzero(words[2:] == (np.arange(len(words) - 2) * 4 + base + 12))
    for i in cand:
        size, stride = int(words[i]), int(words[i + 1])
        off = base + i * 4 + 12
        if stride in KNOWN_STRIDES and 0 < size <= len(d) - off and size % stride == 0:
            out.append(Stream(None, off, size, stride))
    return out


def _command_buffers(obj: Ebo, streams: list[Stream]) -> list[Stream]:
    """Command-buffer candidates: header-less ``i8`` records (NHL) and the targets of
    ``GcDisplayList`` / ``GcCommandBuffer`` records with flag 1 (NBA).  Each is a Stream
    with stride 0 whose size runs to the next stream header or candidate."""
    d = obj.data
    header_offs = {s.data_off - 12 for s in streams}
    data_offs = {s.data_off for s in streams}
    starts = set()
    for r in obj.records:
        tgt = r.at + r.offset
        if tgt >= len(d):
            continue
        raw_i8 = r.type == "i8" and r.flag == 1 and r.count >= 64 and tgt not in data_offs
        if raw_i8 or (r.type in ("GcDisplayList", "GcCommandBuffer") and r.flag == 1):
            starts.add(tgt)
    bounds = sorted(header_offs | starts | {len(d)})
    out = []
    for s in sorted(starts):
        nxt = next((b for b in bounds if b > s), len(d))
        if nxt - s >= 64:
            out.append(Stream(None, s, nxt - s, 0))
    return out


def _list_streams(d: bytes, c: Stream, streams: list[Stream], cmds: list[Stream], nxt_cmd: int):
    """The streams a command buffer draws with.  The GcDisplayList's pointer table holds
    the stream-header offsets and, 0x10 before the buffer, the display-list object; take
    the header pointers in the table window around that word (NBA Live shares normal
    streams between far-apart lists).  Without a table: the streams laid out between this
    buffer and the next one (NHL 2005)."""
    by_hdr = {s.data_off - 12: s for s in streams}
    found: list[Stream] = []
    for delta in (0x10, 0, 0x18):
        key = struct.pack(">I", c.data_off - delta)
        pos = d.find(key)
        while pos >= 0 and not found:
            for o in range(max(0, pos - 13 * 4), min(len(d) - 4, pos + 9 * 4), 4):
                s = by_hdr.get(struct.unpack_from(">I", d, o)[0])
                if s is not None and s not in found:
                    found.append(s)
            if len(found) < 2:
                found = []
                pos = d.find(key, pos + 4)
        if found:
            break
    if found:
        return found
    return [s for s in streams if c.data_off < s.data_off < nxt_cmd]


def _unit_like(d: bytes, s: Stream) -> bool:
    """True when the xyz stream holds unit vectors (normals) rather than positions."""
    n = s.size // s.stride
    if s.stride == 6:
        v = np.frombuffer(d, ">i2", n * 3, s.data_off).reshape(n, 3) / 32767.0
    elif s.stride == 3:
        v = np.frombuffer(d, np.int8, n * 3, s.data_off).reshape(n, 3) / 127.0
    elif s.stride == 12:
        v = np.frombuffer(d, ">f4", n * 3, s.data_off).reshape(n, 3)
    else:
        return False
    if not np.isfinite(v).all():
        return False
    ln = np.linalg.norm(v.astype(np.float64), axis=1)
    return bool(np.mean(np.abs(ln - 1.0) < 0.08) > 0.9)


_BBOX_TAG = bytes.fromhex("ffffffff00000000")


def _bbox(obj: Ebo, start: int | None = None, end: int | None = None):
    """The first BoundingInfo box in [start, end): ``-1, 0`` then min xyz, max xyz as
    big-endian floats."""
    d = obj.data
    lo_ = obj.data_off if start is None else start
    hi_ = len(d) if end is None else min(end, len(d))
    for o in range(lo_, hi_ - 40, 4):
        if d[o : o + 4] == _BBOX_TAG[:4]:
            f = np.frombuffer(d, ">f4", 6, o + 8).astype(np.float64)
            ok = np.isfinite(f).all() and (f[:3] <= f[3:]).all() and np.abs(f).max() < 1e7
            if ok and (f[3:] - f[:3]).max() > 0:
                return f[:3], f[3:]
    return None


GX_ORDER = {"pos": 0, "nrm": 1, "col": 2, "uv": 3}


Layout = tuple[int, list[tuple[str, int, int]]]


def _layout(kinds: list[tuple[str, int]], stride: int) -> Layout | None:
    """(matrix prefix bytes, [(kind, byte offset, width)]) of a display-list vertex: the
    streams in GX attribute order, each index u8 when the stream has at most 256 entries
    and u16 otherwise, after an optional 1-2 byte position/texture matrix prefix.  Bytes
    the known streams do not account for are an index into a stream the file describes
    elsewhere (a colour, typically) and sit in its GX slot, after the normals."""
    ordered = sorted(kinds, key=lambda kn: GX_ORDER[kn[0]])
    widths = [1 if n <= 256 else 2 for _, n in ordered]
    base = sum(widths)
    extra = stride - base
    if extra < 0 or extra > 4:
        return None
    prefix = min(extra, 2)
    unknown = extra - prefix
    out = []
    k = prefix
    placed_unknown = unknown == 0
    for (kind, _n), w in zip(ordered, widths, strict=True):
        if not placed_unknown and GX_ORDER[kind] >= GX_ORDER["col"]:
            k += unknown
            placed_unknown = True
        out.append((kind, k, w))
        k += w
    return prefix, out


def _column(rows: np.ndarray, off: int, width: int) -> np.ndarray:
    if width == 2:
        return (rows[:, off].astype(np.uint32) << 8) | rows[:, off + 1]
    return rows[:, off].astype(np.uint32)


def _decode_stream(d: bytes, s: Stream, bbox, kind: str) -> np.ndarray | None:
    """Elements of a vertex stream as float rows.  Positions: f32 xyz (stride 12) or
    s16 / s8 xyz normalised to the bounding box (stride 6 / 3).  Normals: s8 xyz.  UVs:
    s16 / 1024 (stride 4) or f32 (stride 8).  Colours: RGB565 (stride 2) -> RGBA 0..1."""
    n = s.size // s.stride
    if kind == "pos":
        if s.stride == 12:
            return np.frombuffer(d, ">f4", n * 3, s.data_off).reshape(n, 3).astype(np.float32)
        if bbox is None:
            return None
        lo, hi = bbox
        half, ctr = (hi - lo) / 2, (hi + lo) / 2
        if s.stride == 6:
            raw = np.frombuffer(d, ">i2", n * 3, s.data_off).reshape(n, 3) / 32767.0
        elif s.stride == 3:
            raw = np.frombuffer(d, np.int8, n * 3, s.data_off).reshape(n, 3) / 127.0
        else:
            return None
        return (raw * half + ctr).astype(np.float32)
    if kind == "nrm" and s.stride == 3:
        return np.frombuffer(d, np.int8, n * 3, s.data_off).reshape(n, 3) / np.float32(127.0)
    if kind == "nrm" and s.stride == 6:
        return np.frombuffer(d, ">i2", n * 3, s.data_off).reshape(n, 3) / np.float32(32767.0)
    if kind == "nrm" and s.stride == 12:
        return np.frombuffer(d, ">f4", n * 3, s.data_off).reshape(n, 3).astype(np.float32)
    if kind == "uv":
        if s.stride == 4:
            uv = np.frombuffer(d, ">i2", n * 2, s.data_off).reshape(n, 2).astype(np.float32)
            return uv * UV_SCALE
        if s.stride == 8:
            return np.frombuffer(d, ">f4", n * 2, s.data_off).reshape(n, 2).astype(np.float32)
    if kind == "col" and s.stride == 4:
        return np.frombuffer(d, np.uint8, n * 4, s.data_off).reshape(n, 4) / np.float32(255.0)
    if kind == "col" and s.stride == 2:
        c = np.frombuffer(d, ">u2", n, s.data_off).astype(np.uint32)
        rgba = np.empty((n, 4), np.float32)
        rgba[:, 0] = ((c >> 11) & 31) / 31.0
        rgba[:, 1] = ((c >> 5) & 63) / 63.0
        rgba[:, 2] = (c & 31) / 31.0
        rgba[:, 3] = 1.0
        return rgba
    return None


def _find_list(d: bytes, c: Stream, strides=range(2, 17)):
    """(start, stride, used, prims) of the GX list inside a command buffer: the first
    opcode whose chain, at one of the strides, consumes most of the buffer."""
    best = None
    for p in range(c.data_off, min(c.data_off + 0x200, len(d) - 3)):
        if (d[p] & 0xF8) not in PRIM_OPS or d[p + 1] != 0:
            continue
        for stride in strides:
            prims, used = _chain(d[p : c.data_off + c.size], stride)
            enough = prims and used >= (c.data_off + c.size - p) * 0.75
            if enough and (best is None or used > best[2]):
                best = (p, stride, used, prims)
        if best is not None:
            break
    return best


def _kinds(streams: list[Stream], d: bytes | None = None) -> list[tuple[str, Stream]]:
    """Attribute kind of each vertex stream in a group, in GX order.  Positions are the
    first xyz stream (stride 12 / 6 / 3) that is not made of unit vectors; a unit-vector
    xyz stream is normals; the UV stream is the last stride-8 (f32) or the biggest
    stride-4 (s16) stream; a stride-2 (RGB565) or remaining stride-4 (RGBA) stream is
    colours."""
    out: list[tuple[str, Stream]] = []
    rest = list(streams)
    xyz = [s for s in rest if s.stride in (12, 6, 3)]
    if not xyz:
        return []
    unit = [s for s in xyz if d is not None and _unit_like(d, s)]
    pos = next((s for s in xyz if s not in unit), xyz[0])
    out.append(("pos", pos))
    rest.remove(pos)
    nrm = next((s for s in unit if s is not pos), None)
    if nrm is None:
        nrm = next((s for s in rest if s.stride in (12, 3)), None)
    if nrm is not None:
        out.append(("nrm", nrm))
        rest.remove(nrm)
    uv = next((s for s in reversed(rest) if s.stride == 8), None)
    if uv is None:
        fours = [s for s in rest if s.stride == 4]
        uv = max(fours, key=lambda s: s.size) if fours else None
    if uv is not None:
        rest.remove(uv)
    col = next((s for s in rest if s.stride in (2, 4)), None)
    if col is not None:
        out.append(("col", col))
    if uv is not None:
        out.append(("uv", uv))
    return out


def _list_object(d: bytes, streams: list[Stream]) -> int:
    """File offset of the pointer array inside the GcDisplayList object that owns these
    streams (the big-endian offsets of the first two stream headers, back to back)."""
    if len(streams) < 2:
        return -1
    key = b"".join(struct.pack(">I", s.data_off - 12) for s in streams[:2])
    return d.find(key)


def _list_box(d: bytes, pos: int):
    """(min, max) of the list's own normalisation box: the object stores ``extent xyz``
    and ``-min xyz`` as big-endian floats 36 bytes before its pointer array."""
    if pos < 36:
        return None
    f = np.frombuffer(d, ">f4", 6, pos - 36).astype(np.float64)
    ext, neg_lo = f[:3], f[3:]
    if not np.isfinite(f).all() or (ext <= 0).any() or ext.max() > 1e6:
        return None
    lo = -neg_lo
    return lo, lo + ext


def _skin_table(d: bytes, pos: int, slots: int):
    """(bones, weights) rows of a list's matrix-slot table: the pointer right before the
    stream pointers, ``slots`` rows of four big-endian f32 weights whose low mantissa byte
    is the bone."""
    if pos < 4 or slots < 1:
        return None
    ptr = struct.unpack_from(">I", d, pos - 4)[0]
    if ptr < 0x40 or ptr + slots * 16 > len(d):
        return None
    raw = np.frombuffer(d, ">u4", slots * 4, ptr).reshape(slots, 4)
    bones = (raw & 0xFF).astype(np.uint16)
    weights = (raw & 0xFFFFFF00).astype(">u4").view(">f4").astype(np.float32)
    weights[~np.isfinite(weights)] = 0.0
    weights = np.clip(weights, 0.0, 1.0)
    tot = weights.sum(1, keepdims=True)
    if not (tot > 0.5).all() or (tot > 1.5).any():
        return None
    return bones, weights / tot


def _per_vertex(decoded, kind: str, width: int, nv: int, pidx: np.ndarray) -> np.ndarray | None:
    """A stream re-indexed per position (glTF needs one attribute set per vertex)."""
    if kind not in decoded:
        return None
    arr, idx = decoded[kind]
    out = np.zeros((nv, width), np.float32)
    out[pidx] = arr[idx]
    return out


def geometry(obj: Ebo) -> list[Mesh]:
    """Meshes of a geometry EBO.  Every ``GcCommandBuffer`` record opens a group: its
    command buffer (a GX strip list) and the vertex streams that follow it in GX attribute
    order - positions (f32 / s16 / s8 xyz, the integer kinds normalised to the bounding
    box), optional s8 normals, RGB565 colours, then UVs.  A display-list vertex is one
    index per stream (u16, or u8 for streams up to 256 entries)."""
    if "GcDisplayList" not in obj.types:
        return []
    d = obj.data
    arrays = _streams(obj)
    cmd = _command_buffers(obj, arrays)
    if not cmd or not arrays:
        return []
    bbox = _bbox(obj)
    names = [e.name for e in obj.exports if e.type == "Geometry"]
    # Geometry objects are laid out as blocks (a `Geometry` record with offset 1 and the
    # block size as count opens each); a list belongs to the block it sits in, and the
    # blocks come in export order
    blocks = [r.at for r in obj.records if r.type == "Geometry" and r.flag == 1 and r.offset == 1]
    block_box = [
        _bbox(obj, b, blocks[i + 1] if i + 1 < len(blocks) else None) or bbox
        for i, b in enumerate(blocks)
    ]
    meshes: list[Mesh] = []
    for mi, c in enumerate(cmd):
        nxt = min((x.data_off for x in cmd if x.data_off > c.data_off), default=len(d))
        bi = max((i for i, b in enumerate(blocks) if b <= c.data_off), default=-1)
        box = (block_box[bi] if bi >= 0 else None) or bbox
        near = [s for s in arrays if c.data_off < s.data_off < nxt]
        table = _list_streams(d, c, arrays, cmd, nxt)
        candidates = [near, table] if table != near else [near]
        best = None
        for mine in candidates:
            mesh = _decode_list(d, c, mine, box, bbox)
            if mesh is None:
                continue
            score = sum(x is not None for x in (mesh.uvs, mesh.normals, mesh.colors))
            if best is None or score > best[0]:
                best = (score, mesh)
        if best is None:
            continue
        mesh = best[1]
        name = names[bi] if 0 <= bi < len(names) else (names[0] if names else "geometry")
        mesh.name = f"{name}#{mi}" if len(cmd) > 1 else name
        meshes.append(mesh)
    return meshes


def _decode_list(d: bytes, c: Stream, mine: list[Stream], box, bbox) -> Mesh | None:
    """One display list against a candidate stream set: None unless the vertex layout
    fits the chain stride and every index column stays inside its stream."""
    kinds = _kinds(mine, d)
    if not kinds or kinds[0][0] != "pos":
        return None
    counts = [(k, s.size // s.stride) for k, s in kinds]
    base = sum(1 if n <= 256 else 2 for _, n in counts)
    found = _find_list(d, c, (base, base + 1, base + 2, base + 3))
    if found is None:
        return None
    p0, stride, _used, prims = found
    dl = d[p0 : c.data_off + c.size]
    rows = np.concatenate(
        [np.frombuffer(dl, np.uint8, cnt * stride, o).reshape(cnt, stride)
         for _, cnt, o in prims]
    )
    lay = _layout(counts, stride)
    if lay is None:
        return None
    prefix, cols = lay
    obj_pos = _list_object(d, [s for _, s in kinds])
    if box is None:
        box = _list_box(d, obj_pos) or bbox
    decoded: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    by_kind = dict(kinds)
    for kind, off, w in cols:
        arr = _decode_stream(d, by_kind[kind], box, kind)
        if arr is None:
            continue
        idx = _column(rows, off, w)
        if idx.max() >= len(arr):
            if kind == "pos":
                return None
            continue
        decoded[kind] = (arr, idx)
    if "pos" not in decoded:
        return None
    pos, pidx = decoded["pos"]
    if not np.isfinite(pos).all():
        return None
    tri = _triangulate(prims, pidx)
    if len(tri) < 3:
        return None
    joints = weights = None
    if prefix >= 1:
        slot = rows[:, 0] // 3
        table = _skin_table(d, obj_pos, int(slot.max()) + 1)
        if table is not None:
            bones, w = table
            joints = np.zeros((len(pos), 4), np.uint16)
            weights = np.zeros((len(pos), 4), np.float32)
            joints[pidx] = bones[slot]
            weights[pidx] = w[slot]
    return Mesh(
        "",
        pos.astype(np.float32),
        tri,
        _per_vertex(decoded, "uv", 2, len(pos), pidx),
        _per_vertex(decoded, "nrm", 3, len(pos), pidx),
        _per_vertex(decoded, "col", 4, len(pos), pidx),
        joints,
        weights,
    )


# ---------------------------------------------------------------------------
# skeletons (EaglAnim::Skeleton_0 objects: preload/gmisc.viv/bodyskel.ebo and friends)
# ---------------------------------------------------------------------------

_SKEL_MAGIC = bytes.fromhex("eaea")


@dataclass
class Skeleton:
    matrices: np.ndarray  # (n,4,4) f32 row-major, translation in row 3: bone -> model
    names: list[str]
    parents: list[int | None]


def skeleton(obj: Ebo) -> Skeleton | None:
    """Bone matrices of a Skeleton_0 object: header ``ea ea | u16 bone count | u32 end
    offset`` then, 0x38 bytes on, one 4x4 matrix per bone (row-vector convention,
    translation in the last row - the inverse bind / rest matrices)."""
    if not any(ty.startswith("EaglAnim::Skeleton") for ty in obj.types):
        return None
    d = obj.data
    o = obj.data_off
    while True:
        o = d.find(_SKEL_MAGIC, o)
        if o < 0 or o + 8 > len(d):
            return None
        count, end = struct.unpack_from(">HI", d, o + 2)
        start = o + 0x38
        if 1 <= count <= 512 and end == start + count * 64 and end <= len(d):
            break
        o += 2
    m = np.frombuffer(d, ">f4", count * 16, start).reshape(count, 4, 4).astype(np.float32)
    if not np.isfinite(m).all():
        return None
    # parents: u16 per bone right after the matrices (0xffff = root)
    parents: list[int | None] = []
    for i in range(count):
        v = struct.unpack_from(">H", d, end + i * 2)[0] if end + i * 2 + 2 <= len(d) else 0xFFFF
        parents.append(v if v < count and v != i else None)
    # names: the Dictionary that follows - (u32 string offset, u32 bone index) pairs
    names = [f"bone{i}" for i in range(count)]
    o = end + count * 2
    o += -o % 4
    strtab = {off: s for off, s in obj.strings.items()}
    for _ in range(64):
        if o + 8 > len(d):
            break
        a, b = struct.unpack_from(">II", d, o)
        if a in strtab and b < count:
            break
        o += 4
    seen = 0
    while o + 8 <= len(d) and seen < count:
        a, b = struct.unpack_from(">II", d, o)
        if a not in strtab or b >= count:
            break
        names[b] = strtab[a]
        seen += 1
        o += 8
    return Skeleton(m, names, parents)


def _quat(r: np.ndarray) -> tuple[float, float, float, float]:
    """Unit quaternion (x, y, z, w) of a 3x3 rotation matrix (column convention)."""
    m = r
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x, y, z = (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        x = 0.25 * s
        w, y, z = (m[2, 1] - m[1, 2]) / s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        y = 0.25 * s
        w, x, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        z = 0.25 * s
        w, x, y = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s
    q = np.array([x, y, z, w], np.float64)
    q /= np.linalg.norm(q) or 1.0
    return tuple(float(v) for v in q)


def joints(sk: Skeleton) -> list[tuple[str, int | None, tuple, tuple, tuple]]:
    """(name, parent, translation, rotation xyzw, scale) per bone: the local rest
    transforms, from the bone->model matrices (the stored matrices are model->bone in
    row-vector form) composed against each parent."""
    n = len(sk.matrices)
    world = []
    for i in range(n):
        m = sk.matrices[i].astype(np.float64).T  # column convention: model->bone
        try:
            world.append(np.linalg.inv(m))  # bone->model
        except np.linalg.LinAlgError:
            world.append(np.eye(4))
    out = []
    for i in range(n):
        pi = sk.parents[i]
        local = world[i] if pi is None else np.linalg.inv(world[pi]) @ world[i]
        r = local[:3, :3]
        scale = np.linalg.norm(r, axis=0)
        scale[scale == 0] = 1.0
        rot = r / scale
        if np.linalg.det(rot) < 0:
            scale[0] *= -1
            rot[:, 0] *= -1
        out.append(
            (
                sk.names[i] if i < len(sk.names) else f"bone{i}",
                pi,
                tuple(float(v) for v in local[:3, 3]),
                _quat(rot),
                tuple(float(v) for v in scale),
            )
        )
    return out
