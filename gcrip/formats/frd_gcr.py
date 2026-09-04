"""Free Radical ``gcr`` character models - TimeSplitters 2's ``ob/chrs/chr*.gcr`` (314 in
``data/chr.pak``).  Read against the draw routine in the TS2 ``main.dol`` (no symbols: the
function at ``0x8024a454`` that calls ``GXSetArray`` nine times), 2026-09-03.

The file is the runtime image: pointers are offsets from byte 0, and the header the game
keeps is the **last 52 bytes** (``+4`` of the file says where: ``file length - 52``)::

    +0    u32 12              -> a table of 16-byte texture slots: u32 gct id
                                 (``textures/%04d.gct`` in the same pak), u32[3] zero,
                                 ended by 0xFFFFFFFF
    +4    u32 trailer offset  the last 52 bytes: u32 records, u32 bones, u32 1, ..., f32
    the records precede the trailer: ``records x 0xa0`` bytes, each a node

    node  +0   u8 kind         0 rigid (one bone, byte +1), 1 / 2 / 3 skinned pieces
          +1   u8 bone         +2 .. +5 more node bytes (parent / next, 0xff none)
          +0x14 + 4 * lod   -> batch table: 10-byte ``u16 texture slot, u16 index,
                               u16 first vertex, u16 vertices, u16 flags``, ended by an
                               entry whose flags are 0xFFFF (three LODs at most)
          +0x24 + 0x14 * lod   u32, ptr positions (f32 x3), ptr uvs (f32 x2, x3 when
                               bit ``lod`` of +0x67 is set), ptr colours (RGBA8, or 0),
                               ptr normals (s8 x3 + pad, / 64)
          +0x60 u16, +0x62 u16, +0x67 u8 uv flags, +0x8c f32 (1 / 0.5 / 0.3)
          +0x90 + 4 * lod   -> per batch ``u32 display list, u32 bytes`` (0, 0 = none)

A display list is GX: ``0x98 | fmt, u16 count`` strips of vertices that are big-endian
``u16`` indices - position, normal (only when the node has a normal array), colour, uv -
with, on the skinned kinds, a leading ``u8`` matrix (bone) index: 8 bytes on a rigid
character node, 9 on a skinned one, 6 on a level sector (no normals, vertex-lit).
Positions are the bind pose in model space (feet at y = 0, head at 1.86 on ``chr128``), so
a rigid node's bone is only metadata here.

**Future Perfect and Second Sight** (``parse_fp``) grow the record to 0xc0 bytes - the four
LOD array sub-records move to +0 (``u32, ptr positions, ptr uvs, ptr normals, ptr colours``:
normals and colours swap places), kind at +0x3c, batch tables at +0x54, uv flags at +0x6b,
pairs at +0xb0 - and the trailer at ``+4`` carries flags at +0xc: 0x10 positions are ``s16
/ 1024``, 0x40 normal indices name one of the 4096 unit vectors the DOL keeps (the
``frd_normals.npz`` palette - the same table in both games), 0x10000 every vertex leads
with a matrix byte.  A uv pointer with bit 1 set is ``s16 / 1024``.  Batch entries are 8
bytes in one of two orders (``_fp_batches``), the texture slots at 12 either embed a gct
(``ptr, hash, 0, 0x10000000``) or name one by hash (``hash, hash, 0, 0`` - the pak member
``HHHHHHHH_NNNN``).  Skinned characters keep one position array after the trailer that
every node's lists index.

**Array-block characters** (``parse_b``: TS2's ``chrinc.pak``, most Future Perfect / Second
Sight characters) are another shape: a header of pointers (TS2 ``slots, block``; FP
``slots, nodes, block``), the block ``ptr positions, ptr uvs, ptr normals, [u32 7], ptr
groups, ptr node tree, u32 groups, u32 nodes, ...`` with the positions right behind the
header words (f32 x3 + flag word, f32 uv pairs, f32 normal + pad on TS2; s16 / 1024, s16 /
1024, s16 / 16384 on FP), groups of ``[u32] ptr entries, u32 entries, ptr matrix slots, u32
matrices, u32 first`` and 20-byte entries ``u32 slot, u32 first, u32 count, ptr list, u32
bytes`` whose lists carry ``u8 matrix, u16 position, u16 normal, [u16 colour], u16 uv``.
Positions are model space; the strips do not keep one winding, so each triangle is turned to
face its own normals (0.91 / 0.92 agreement after that).

**Levels** (``bg/level*/level*.gcr``) reuse the node record without the trailer: ``+0`` is
0x20 (the texture slots follow the eight-word header: ``u32 gct id, u32 flags, 0, u32``),
``+4`` / ``+8`` / ``+0xc`` point at runtime scratch, 72-byte portal quads and entity
placements, and +0x14 / +0x18 are -1.  The geometry is a run of sector blocks, each its
batch table, arrays, display lists and pairs followed by the 0xa0 record - whose word at
+0x9c points four bytes before the record, which is how ``level_nodes`` finds them.  Level 11
(Chicago) is 51 sectors, 10,461 triangles in world space, 62 textures.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gcrip.formats.eagl import _triangulate

TRAILER = 52
RECORD = 0xA0
LODS = 3
BATCH = 10
TEXTURE_SLOT = 16
END = 0xFFFF
END32 = 0xFFFFFFFF
PRIM_MASK = 0xF8
PRIM_OPS = {0x80, 0x90, 0x98, 0xA0}
MAX_RECORDS = 1024
MAX_BATCHES = 256
MAX_VERTS = 1 << 16
NRM_SCALE = 1.0 / 64.0


@dataclass
class Batch:
    node: int
    kind: int
    bone: int
    slot: int  # texture slot -> Model.textures
    positions: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray
    colors: np.ndarray | None
    indices: np.ndarray
    bones: np.ndarray | None  # per-vertex matrix index on the skinned kinds


@dataclass
class Model:
    records: int = 0
    bones: int = 0
    textures: list[int] = field(default_factory=list)  # gct ids by slot
    batches: list[Batch] = field(default_factory=list)
    lods: int = 1
    warnings: list[str] = field(default_factory=list)


def is_gcr(head: bytes, size: int) -> bool:
    if len(head) < 12 or size < TRAILER + RECORD + 16:
        return False
    a, b, c = struct.unpack_from(">3I", head, 0)
    return a == 12 and b == size - TRAILER and c == 0


def _textures(data: bytes) -> list[int]:
    out = []
    p = 12
    while p + TEXTURE_SLOT <= len(data) and len(out) < MAX_BATCHES:
        gct = struct.unpack_from(">I", data, p)[0]
        if gct == END32:
            break
        out.append(gct)
        p += TEXTURE_SLOT
    return out


def _batches(data: bytes, at: int) -> list[tuple[int, int, int, int]] | None:
    out = []
    p = at
    while p + BATCH <= len(data) and len(out) < MAX_BATCHES:
        slot, index, first, count, flags = struct.unpack_from(">5H", data, p)
        if flags == END:
            return out
        out.append((slot, index, first, count))
        p += BATCH
    return None


def _strips(data: bytes, at: int, size: int, layout: tuple[bool, bool, bool, bool]):
    """(index rows (n, 4): position, normal, colour, uv; matrix bytes or None; triangles) of
    one display list.  ``layout`` says which optional fields a vertex carries: a leading
    matrix byte, a normal index, a colour index, a second colour index (skipped)."""
    has_mtx, has_nrm, has_clr, has_clr1 = layout
    stride = (1 if has_mtx else 0) + 2 + (2 if has_nrm else 0) + (2 if has_clr else 0)
    stride += (2 if has_clr1 else 0) + 2
    end = min(at + size, len(data))
    p = at
    rows, mtx, prims = [], [], []
    base = 0
    while p + 3 <= end:
        op = data[p]
        if op == 0:
            p += 1
            continue
        if op & PRIM_MASK not in PRIM_OPS:
            return None
        count = struct.unpack_from(">H", data, p + 1)[0]
        p += 3
        if count < 1 or p + count * stride > end:
            return None
        raw = np.frombuffer(data, np.uint8, count * stride, p).reshape(count, stride)
        if has_mtx:
            mtx.append(raw[:, 0].copy())
            raw = raw[:, 1:]
        cols = raw.copy().view(">u2").reshape(count, -1)
        k = 0
        pos = cols[:, k]
        k += 1
        if has_nrm:
            nrm = cols[:, k]
            k += 1
        else:
            nrm = np.zeros(count, ">u2")
        if has_clr:
            clr = cols[:, k]
            k += 1
        else:
            clr = np.zeros(count, ">u2")
        k += 1 if has_clr1 else 0
        tex = cols[:, k]
        rows.append(np.stack([pos, nrm, clr, tex], 1))
        prims.append((op & PRIM_MASK, count, base))
        base += count
        p += count * stride
    if not rows:
        return None
    tri = _triangulate(prims, np.arange(base, dtype=np.uint32)).reshape(-1, 3)
    return np.concatenate(rows), (np.concatenate(mtx) if mtx else None), tri


def _node(data: bytes, i: int, r: int, out: Model) -> None:
    """The finest LOD of the 0xa0-byte node record at ``r`` into ``out.batches``."""
    kind, bone = data[r], data[r + 1]
    uv_flags = data[r + 0x67]
    chosen = None
    for lod in range(LODS):
        table = struct.unpack_from(">I", data, r + 0x14 + 4 * lod)[0]
        pairs = struct.unpack_from(">I", data, r + 0x90 + 4 * lod)[0]
        if not table:
            continue
        if chosen is not None:
            out.lods = max(out.lods, lod + 1)
            continue  # the finest level present is the model; the others are the same shape
        chosen = lod
        arrays = r + 0x24 + 0x14 * lod
        _h, pos_at, uv_at, clr_at, nrm_at = struct.unpack_from(">5I", data, arrays)
        batches = _batches(data, table)
        if batches is None or not pos_at or not uv_at:
            out.warnings.append(f"node {i}: batch table unreadable")
            break
        nverts = batches[-1][2] + batches[-1][3] if batches else 0
        if not 0 < nverts <= MAX_VERTS or pos_at + nverts * 12 > len(data):
            out.warnings.append(f"node {i}: {nverts} vertices past the file")
            break
        uv_stride = 12 if uv_flags & (1 << lod) else 8
        # TimeSplitters 2 always carries a colour index (a white array stands in for none)
        layout = (kind != 0, nrm_at != 0, True, bool(uv_flags & (0x10 << lod)))
        positions = np.frombuffer(data, ">f4", nverts * 3, pos_at).reshape(nverts, 3)
        for k, (slot, _index, _first, _n) in enumerate(batches):
            if pairs + 8 * k + 8 > len(data):
                break
            dl_at, dl_size = struct.unpack_from(">2I", data, pairs + 8 * k)
            if not dl_at or not dl_size:
                continue
            got = _strips(data, dl_at, dl_size, layout)
            if got is None:
                out.warnings.append(f"node {i}: batch {k} display list unreadable")
                continue
            rows, mtx, tri = got
            if int(rows[:, 0].max()) >= nverts:
                out.warnings.append(f"node {i}: batch {k} indexes past {nverts} vertices")
                continue
            uniq, inverse = np.unique(rows, axis=0, return_inverse=True)
            tri = inverse.reshape(-1)[tri]
            keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2])
            tri = tri[keep & (tri[:, 0] != tri[:, 2])]
            if not len(tri):
                continue
            pi = uniq[:, 0].astype(np.int64)
            ni = uniq[:, 1].astype(np.int64)
            ti = uniq[:, 3].astype(np.int64)
            nmax, tmax = int(ni.max()), int(ti.max())
            if nrm_at and nrm_at + (nmax + 1) * 4 <= len(data):
                nrm = np.frombuffer(data, np.int8, (nmax + 1) * 4, nrm_at).reshape(-1, 4)[:, :3]
                normals = (nrm[ni].astype(np.float32) * NRM_SCALE).astype(np.float32)
            else:
                normals = None
            if uv_at + (tmax + 1) * uv_stride <= len(data):
                uv = np.frombuffer(data, ">f4", (tmax + 1) * uv_stride // 4, uv_at).reshape(
                    -1, uv_stride // 4
                )[:, :2]
                uvs = np.ascontiguousarray(uv[ti], np.float32)
            else:
                uvs = np.zeros((len(uniq), 2), np.float32)
            colors = None
            if clr_at:
                ci = uniq[:, 2].astype(np.int64)
                ncol = int(ci.max()) + 1
                if clr_at + ncol * 4 <= len(data):
                    c = np.frombuffer(data, np.uint8, ncol * 4, clr_at).reshape(-1, 4)
                    colors = np.ascontiguousarray(c[ci])
            per_vertex_bone = None
            if mtx is not None:
                # the matrix byte travels with the corner; take it from the first corner
                # that names each unique vertex
                first = np.zeros(len(uniq), np.int64)
                first[inverse.reshape(-1)[::-1]] = np.arange(len(inverse) - 1, -1, -1)
                per_vertex_bone = mtx[first].astype(np.uint16)
            out.batches.append(
                Batch(
                    i,
                    kind,
                    bone,
                    slot,
                    np.ascontiguousarray(positions[pi], np.float32),
                    normals,
                    uvs,
                    colors,
                    tri.ravel().astype(np.uint32),
                    per_vertex_bone,
                )
            )


def parse(data: bytes) -> Model | None:
    if not is_gcr(data[:12], len(data)):
        return None
    out = Model()
    trailer = len(data) - TRAILER
    count, bones = struct.unpack_from(">2I", data, trailer)
    if not 0 < count <= MAX_RECORDS or trailer - count * RECORD < 12:
        out.warnings.append(f"{count} records do not fit")
        return out
    out.records, out.bones = count, bones
    out.textures = _textures(data)
    base = trailer - count * RECORD
    for i in range(count):
        _node(data, i, base + i * RECORD, out)
    return out


# -- levels: bg/level*.gcr ---------------------------------------------------------------------

LEVEL_SLOTS = 0x20
LEVEL_NONE = 0xFFFFFFFF


def is_level(head: bytes, size: int) -> bool:
    """``+0`` is 0x20 - the texture slots start right after the eight-word header - and the
    words at +0x14 and +0x18 are -1."""
    if len(head) < 0x20 or size < 0x400:
        return False
    a, b, c, d_, _e, f, g = struct.unpack_from(">7I", head, 0)
    inside = 0 < b < size and 0 < c < size and 0 < d_ < size
    return a == LEVEL_SLOTS and f == LEVEL_NONE and g == LEVEL_NONE and inside


def _level_slots(data: bytes) -> list[int]:
    out = []
    p = LEVEL_SLOTS
    while p + TEXTURE_SLOT <= len(data) and len(out) < MAX_BATCHES:
        gct = struct.unpack_from(">I", data, p)[0]
        if gct == LEVEL_NONE:
            break
        out.append(gct)
        p += TEXTURE_SLOT
    return out


def level_nodes(data: bytes) -> list[int]:
    """Offsets of a level's sector records: each 0xa0-byte record closes its own block and
    its word at +0x9c points four bytes before itself."""
    n = len(data) // 4 * 4
    words = np.frombuffer(data, ">u4", n // 4)
    at = np.arange(0, n, 4, dtype=np.int64)
    ok = np.zeros(len(words), bool)
    span = 0x9C // 4
    ok[: len(words) - span] = words[span:] == (at[: len(words) - span] - 4)
    ok &= at >= 4
    out = []
    for x in at[ok].tolist():
        if x + RECORD > len(data):
            continue
        table = struct.unpack_from(">I", data, x + 0x14)[0]
        pairs = struct.unpack_from(">I", data, x + 0x90)[0]
        pos_at, uv_at = struct.unpack_from(">2I", data, x + 0x28)
        if 0 < table < x and 0 < pairs < x and 0 < pos_at < x and 0 < uv_at < x:
            out.append(x)
    return out


def parse_level(data: bytes) -> Model | None:
    if not is_level(data[:0x20], len(data)):
        return None
    out = Model()
    out.textures = _level_slots(data)
    nodes = level_nodes(data)
    out.records = len(nodes)
    for i, r in enumerate(nodes):
        _node(data, i, r, out)
    return out


# -- Future Perfect / Second Sight props: 0xc0-byte records ---------------------------------------

RECORD_FP = 0xC0
BATCH_FP = 8
END_FP = 0xFF
FP_S16_POS = 0x10  # trailer flags: positions are s16 / 1024
FP_PALETTE = 0x40  # trailer flags: normal indices go to the DOL's 4096-entry palette
FP_MATRIX = 0x10000  # trailer flags: every vertex leads with a matrix byte, whatever its kind
FP_UV_S16 = 2  # a uv pointer with bit 1 set is s16 / 1024
POS_SCALE_FP = 1.0 / 1024.0
UV_SCALE_FP = 1.0 / 1024.0
NRM_SCALE_FP = 1.0 / 32767.0
_PALETTE: dict[str, np.ndarray | None] = {}


def normal_palette(game: str = "fp") -> np.ndarray | None:
    """The 4096 unit vectors Future Perfect's DOL keeps at 0x80412740 (``GXSetArray`` of
    ``GX_VA_NRM`` with a 12-byte stride) - a vertex's normal index names one of them."""
    if game not in _PALETTE:
        path = Path(__file__).resolve().parent.parent / "data" / "frd_normals.npz"
        try:
            with np.load(path) as z:
                _PALETTE[game] = z[game].astype(np.float32) * NRM_SCALE_FP
        except (OSError, KeyError):
            _PALETTE[game] = None
    return _PALETTE[game]


def is_fp(head: bytes, size: int) -> bool:
    """``+0`` is 12 (the slot table) and ``+4`` a trailer inside the file with room for a
    record before it; ``fp_records`` does the real check on the whole file."""
    if len(head) < 12 or size < RECORD_FP + 16 + 12:
        return False
    a, trailer, _c = struct.unpack_from(">3I", head, 0)
    return a == 12 and trailer + 16 <= size and trailer - RECORD_FP >= 12 and trailer != size - 52


def fp_records(data: bytes) -> tuple[int, int, int] | None:
    """(trailer, count, flags) when the trailer and its records check out: the first
    record's batch table and position array lie inside the file before the trailer."""
    trailer = struct.unpack_from(">I", data, 4)[0]
    if trailer + 16 > len(data) or trailer < RECORD_FP + 12:
        return None
    count, _b, _c, flags = struct.unpack_from(">4I", data, trailer)
    if not 0 < count <= MAX_RECORDS or trailer - count * RECORD_FP < 12:
        return None
    base = trailer - count * RECORD_FP
    seen = False
    for i in range(count):
        r = base + i * RECORD_FP
        for lod in range(LODS):
            table = struct.unpack_from(">I", data, r + 0x54 + 4 * lod)[0]
            pos_at = struct.unpack_from(">I", data, r + 0x14 * lod + 4)[0]
            if table == 0 and pos_at == 0:
                continue  # an empty level (a bone with nothing to draw)
            # skinned characters keep their arrays after the trailer
            if not (0 < table < trailer and 0 < pos_at < len(data)):
                return None
            seen = True
    if not seen:
        return None
    return trailer, count, flags


FP_EMBEDDED = 0x10000000


def _fp_slots(data: bytes) -> list[int]:
    """By slot: the offset of an embedded gct (``u32 offset, u32 hash, 0, 0x10000000``), or
    the negated hash of one kept in another pak (``u32 hash, u32 hash, 0, 0``)."""
    out = []
    p = 12
    while p + TEXTURE_SLOT <= len(data) and len(out) < MAX_BATCHES:
        ptr, _h, _z, kind = struct.unpack_from(">4I", data, p)
        if ptr == END32:
            break
        out.append(ptr if kind & FP_EMBEDDED else -ptr)
        p += TEXTURE_SLOT
    return out


def _fp_batches(data: bytes, at: int) -> list[tuple[int, int, int, int]] | None:
    """8-byte entries in one of two field orders - Second Sight's ``u16 slot, u16 index,
    u16 first, u8 count, u8 flags`` or Future Perfect's ``u16 slot, u8 count, u8 flags, u16
    index, u16 first`` - each ended by an entry whose flags are 0xFF.  The order that reaches
    its terminator with small flags and a non-decreasing ``first`` is the one (a skinned
    character's ``first`` jumps, as it offsets into a shared array, so it need not run
    cumulatively)."""
    best = None
    for order in (">3HBB", ">HBBHH"):
        out = []
        p = at
        ended = False
        while p + BATCH_FP <= len(data) and len(out) < MAX_BATCHES:
            fields = struct.unpack_from(order, data, p)
            if order == ">3HBB":
                slot, index, first, count, flags = fields
            else:
                slot, count, flags, index, first = fields
            if flags == END_FP:
                ended = True
                break
            if flags > 15 or (out and first < out[-1][2]) or slot >= MAX_BATCHES:
                break
            out.append((slot, index, first, count))
            p += BATCH_FP
        if ended and out:
            cumulative = all(b[2] == a[2] + a[3] for a, b in zip(out, out[1:], strict=False))
            if cumulative:
                return out
            best = best or out
    return best


def _fp_node(data: bytes, i: int, r: int, flags: int, out: Model) -> None:
    kind, bone = data[r + 0x3C], data[r + 0x3D]
    uv_flags = data[r + 0x6B]
    palette = normal_palette() if flags & FP_PALETTE else None
    chosen = None
    for lod in range(LODS):
        table = struct.unpack_from(">I", data, r + 0x54 + 4 * lod)[0]
        pairs = struct.unpack_from(">I", data, r + 0xB0 + 4 * lod)[0]
        if not table:
            continue
        if chosen is not None:
            out.lods = max(out.lods, lod + 1)
            continue
        chosen = lod
        _h, pos_at, uv_at, nrm_at, clr_at = struct.unpack_from(">5I", data, r + 0x14 * lod)
        batches = _fp_batches(data, table)
        if batches is None or not pos_at or not uv_at:
            out.warnings.append(f"node {i}: batch table unreadable")
            break
        nverts = batches[-1][2] + batches[-1][3] if batches else 0
        s16_pos = bool(flags & FP_S16_POS)
        pos_stride = 6 if s16_pos else 12
        # skinned characters share one position array (kept after the trailer) whose
        # display lists index it globally, so the batch count is not the bound: read what
        # the file holds
        nverts = max(nverts, min((len(data) - pos_at) // pos_stride, MAX_VERTS))
        if not 0 < nverts <= MAX_VERTS or pos_at + nverts * pos_stride > len(data):
            out.warnings.append(f"node {i}: {nverts} vertices past the file")
            break
        if s16_pos:
            raw = np.frombuffer(data, ">i2", nverts * 3, pos_at).reshape(nverts, 3)
            positions = raw.astype(np.float32) * POS_SCALE_FP
        else:
            positions = np.frombuffer(data, ">f4", nverts * 3, pos_at).reshape(nverts, 3)
        s16_uv = bool(uv_at & FP_UV_S16)
        uv_at &= ~3
        comps = 3 if uv_flags & (1 << lod) else 2
        uv_stride = comps * (2 if s16_uv else 4)
        # Future Perfect only carries a colour index when the node has colours
        has_mtx = kind != 0 or bool(flags & FP_MATRIX)
        layout = (has_mtx, nrm_at != 0, clr_at != 0, bool(uv_flags & (0x10 << lod)))
        for k, (slot, _index, _first, _n) in enumerate(batches):
            if pairs + 8 * k + 8 > len(data):
                break
            dl_at, dl_size = struct.unpack_from(">2I", data, pairs + 8 * k)
            if not dl_at or not dl_size:
                continue
            got = _strips(data, dl_at, dl_size, layout)
            if got is None:
                out.warnings.append(f"node {i}: batch {k} display list unreadable")
                continue
            rows, mtx, tri = got
            if int(rows[:, 0].max()) >= nverts:
                out.warnings.append(f"node {i}: batch {k} indexes past {nverts} vertices")
                continue
            uniq, inverse = np.unique(rows, axis=0, return_inverse=True)
            tri = inverse.reshape(-1)[tri]
            keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2])
            tri = tri[keep & (tri[:, 0] != tri[:, 2])]
            if not len(tri):
                continue
            pi = uniq[:, 0].astype(np.int64)
            ni = uniq[:, 1].astype(np.int64)
            ti = uniq[:, 3].astype(np.int64)
            normals = None
            nmax = int(ni.max())
            if nrm_at and palette is not None and nmax < len(palette):
                normals = np.ascontiguousarray(palette[ni], np.float32)
            elif nrm_at and palette is None and nrm_at + (nmax + 1) * 4 <= len(data):
                nrm = np.frombuffer(data, np.int8, (nmax + 1) * 4, nrm_at).reshape(-1, 4)
                normals = (nrm[ni, :3].astype(np.float32) * NRM_SCALE).astype(np.float32)
            tmax = int(ti.max())
            if uv_at + (tmax + 1) * uv_stride <= len(data):
                if s16_uv:
                    uv = np.frombuffer(data, ">i2", (tmax + 1) * comps, uv_at).reshape(-1, comps)
                    uvs = (uv[ti, :2].astype(np.float32) * UV_SCALE_FP).astype(np.float32)
                else:
                    uv = np.frombuffer(data, ">f4", (tmax + 1) * comps, uv_at).reshape(-1, comps)
                    uvs = np.ascontiguousarray(uv[ti, :2], np.float32)
            else:
                uvs = np.zeros((len(uniq), 2), np.float32)
            colors = None
            if clr_at:
                ci = uniq[:, 2].astype(np.int64)
                ncol = int(ci.max()) + 1
                if clr_at + ncol * 4 <= len(data):
                    c = np.frombuffer(data, np.uint8, ncol * 4, clr_at).reshape(-1, 4)
                    colors = np.ascontiguousarray(c[ci])
            per_vertex_bone = None
            if mtx is not None:
                first = np.zeros(len(uniq), np.int64)
                first[inverse.reshape(-1)[::-1]] = np.arange(len(inverse) - 1, -1, -1)
                per_vertex_bone = mtx[first].astype(np.uint16)
            out.batches.append(
                Batch(
                    i,
                    kind,
                    bone,
                    slot,
                    np.ascontiguousarray(positions[pi], np.float32),
                    normals,
                    uvs,
                    colors,
                    tri.ravel().astype(np.uint32),
                    per_vertex_bone,
                )
            )


def parse_fp(data: bytes) -> Model | None:
    """A Future Perfect / Second Sight prop: 0xc0-byte records before the trailer at ``+4``,
    textures embedded behind the slot table (``Model.textures`` holds their offsets)."""
    if not is_fp(data[:12], len(data)):
        return None
    got = fp_records(data)
    if got is None:
        return None
    trailer, count, flags = got
    out = Model()
    out.records = count
    out.bones = struct.unpack_from(">I", data, trailer + 4)[0]
    out.textures = _fp_slots(data)
    base = trailer - count * RECORD_FP
    for i in range(count):
        _fp_node(data, i, base + i * RECORD_FP, flags, out)
    return out


# -- skinned characters: the "array block" flavour (TS2 chrinc, Future Perfect / Second Sight) --

GROUP_TS2 = 20
GROUP_FP = 24
ENTRY_B = 20
MAX_GROUPS = 4096


def b_block(data: bytes) -> tuple[int, bool] | None:
    """(offset of the array block, Future Perfect layout?) or None.  TimeSplitters 2 keeps
    the block at ``+4`` with its positions at 8; Future Perfect at ``+8`` with them at 12."""
    if len(data) < 0x40:
        return None
    a, b, c = struct.unpack_from(">3I", data, 0)
    if 0x20 <= b < len(data) - 0x30 and struct.unpack_from(">I", data, b)[0] == 8 and a > b:
        return b, False
    if 0x20 <= c < len(data) - 0x40 and struct.unpack_from(">I", data, c)[0] == 12 and a > c:
        return c, True
    return None


def is_b(head: bytes, size: int) -> bool:
    """What 64 bytes can say: the header pointers sit inside the file and the first
    positions follow the header words directly (``b_block`` finishes the check)."""
    if len(head) < 12:
        return False
    a, b, c = struct.unpack_from(">3I", head, 0)
    ts2 = 0x20 <= b < size and a > b and b > 8
    fp = 0x20 <= c < size and a > c and a < size and 0x20 <= b < size
    return ts2 or fp


def _b_slots(data: bytes, at: int) -> list[int]:
    """Texture slots: an embedded gct's offset, or the negated hash of an external one."""
    out = []
    p = at
    while p + TEXTURE_SLOT <= len(data) and len(out) < MAX_BATCHES:
        ptr, _h, _z, kind = struct.unpack_from(">4I", data, p)
        if ptr == END32:
            break
        out.append(ptr if kind & FP_EMBEDDED else -ptr)
        p += TEXTURE_SLOT
    return out


def _orient(positions: np.ndarray, normals: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Flip each triangle that faces away from its own vertex normals - this flavour's
    strips do not keep one winding."""
    a, b, c = positions[tri[:, 0]], positions[tri[:, 1]], positions[tri[:, 2]]
    face = np.cross(b - a, c - a)
    vert = normals[tri[:, 0]] + normals[tri[:, 1]] + normals[tri[:, 2]]
    flip = (face * vert).sum(1) < 0
    tri = tri.copy()
    tri[flip] = tri[flip][:, ::-1]
    return tri


def parse_b(data: bytes) -> Model | None:
    got = b_block(data)
    if got is None:
        return None
    at, fp = got
    n = len(data)
    if fp:
        pos_at, uv_at, nrm_at, _seven, groups_at, _tree, ngroups, nnodes = struct.unpack_from(
            ">8I", data, at
        )
        slots_at = struct.unpack_from(">I", data, 0)[0]
        pos_stride, uv_stride, nrm_stride, group_size = 6, 4, 8, GROUP_FP
    else:
        pos_at, uv_at, nrm_at, groups_at, _tree, ngroups, nnodes = struct.unpack_from(
            ">7I", data, at
        )
        slots_at = struct.unpack_from(">I", data, 0)[0]
        pos_stride, uv_stride, nrm_stride, group_size = 16, 8, 16, GROUP_TS2
    if not (pos_at < uv_at < nrm_at < n) or not 0 < ngroups <= MAX_GROUPS:
        return None
    nverts = (uv_at - pos_at) // pos_stride
    nuv = (nrm_at - uv_at) // uv_stride
    if nverts < 3 or nrm_at + nverts * nrm_stride > n:
        return None
    out = Model()
    out.records, out.bones = ngroups, nnodes
    out.textures = _b_slots(data, slots_at)
    if fp:
        raw = np.frombuffer(data, ">i2", nverts * 3, pos_at).reshape(nverts, 3)
        positions = raw.astype(np.float32) * POS_SCALE_FP
        uvs_all = np.frombuffer(data, ">i2", nuv * 2, uv_at).reshape(nuv, 2).astype(np.float32)
        uvs_all *= UV_SCALE_FP
        nr = np.frombuffer(data, ">i2", nverts * 4, nrm_at).reshape(nverts, 4)[:, :3]
        normals_all = nr.astype(np.float32) / 16384.0
    else:
        positions = np.frombuffer(data, ">f4", nverts * 4, pos_at).reshape(nverts, 4)[:, :3]
        uvs_all = np.frombuffer(data, ">f4", nuv * 2, uv_at).reshape(nuv, 2)
        normals_all = np.frombuffer(data, ">f4", nverts * 4, nrm_at).reshape(nverts, 4)[:, :3]
    # matrix byte, normal index, colour index (TS2 only), no second colour
    layout = (True, True, not fp, False)
    for g in range(ngroups):
        gr = groups_at + g * group_size
        if gr + group_size > n:
            out.warnings.append(f"group {g} past the file")
            break
        if fp:
            _z, entries_at, nentries, _x, _nm, _first = struct.unpack_from(">6I", data, gr)
        else:
            entries_at, nentries, _x, _nm, _first = struct.unpack_from(">5I", data, gr)
        for k in range(min(nentries, MAX_BATCHES)):
            e = entries_at + k * ENTRY_B
            if e + ENTRY_B > n:
                break
            slot, _first_v, _count, dl_at, dl_size = struct.unpack_from(">5I", data, e)
            if not dl_at or not dl_size or dl_at + dl_size > n:
                continue
            got_dl = _strips(data, dl_at, dl_size, layout)
            if got_dl is None:
                out.warnings.append(f"group {g}: entry {k} display list unreadable")
                continue
            rows, mtx, tri = got_dl
            if int(rows[:, 0].max()) >= nverts or int(rows[:, 1].max()) >= nverts:
                out.warnings.append(f"group {g}: entry {k} indexes past {nverts} vertices")
                continue
            uniq, inverse = np.unique(rows, axis=0, return_inverse=True)
            tri = inverse.reshape(-1)[tri]
            keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2])
            tri = tri[keep & (tri[:, 0] != tri[:, 2])]
            if not len(tri):
                continue
            pi = uniq[:, 0].astype(np.int64)
            ni = uniq[:, 1].astype(np.int64)
            ti = np.minimum(uniq[:, 3].astype(np.int64), max(nuv - 1, 0))
            pos = np.ascontiguousarray(positions[pi], np.float32)
            nrm = np.ascontiguousarray(normals_all[ni], np.float32)
            tri = _orient(pos, nrm, tri)
            first = np.zeros(len(uniq), np.int64)
            first[inverse.reshape(-1)[::-1]] = np.arange(len(inverse) - 1, -1, -1)
            out.batches.append(
                Batch(
                    g,
                    1,
                    0,
                    slot,
                    pos,
                    nrm,
                    np.ascontiguousarray(uvs_all[ti], np.float32),
                    None,
                    tri.ravel().astype(np.uint32),
                    mtx[first].astype(np.uint16) if mtx is not None else None,
                )
            )
    return out
