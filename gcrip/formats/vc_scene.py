"""Visual Concepts ``SCNE`` scene records - the models inside ``game.dat``'s ``.IFF``
members (NBA 2K2/2K3, NFL 2K3, NCAA Basketball/Football 2K3).

A decoded ``.IFF`` member is a run of generic records - ``16 bytes of header, a reversed
4CC, u32 size`` (span ``size + 16``), the same frame the ``RTXT`` texture records use.  The
``ENCS`` (SCNE) records are Maya-exported scenes: skeleton node names (``rhumerus``,
``lcollar``...), source texture paths (``D:/nba2k3/coach/textures/...``) and, this module's
business, **mesh geometry as GameCube GX display lists**.  ``FRONTEND.IFF`` alone carries
the NBA ball, players, referees, the basket and the ESPN overlay models.

One scene record holds, in order: node tables and 4x4 matrices, a **position dequantization
matrix** (diagonal scale + translation, its inverse right after it, then the normal
dequantization ``diag(1/64)``), a string table, and per shape a **vertex array** followed
by its **display lists**.

Vertex array - 16 bytes an entry, big-endian::

    +0   u16    texture U (u8.8 fixed point)
    +2   s16    x, y, z   quantized position - model space, bind pose baked in
    +8   s8[3]  normal, scale 1/64
    +11  u8     pad
    +12  u16    0
    +14  u16    texture V (u8.8)

The display lists are the GX wire format itself: ``0x20/0x28/0x30`` load-indexed-XF
(position matrix to XF row 0..., normal matrix to 0x400..., texture matrix to 0x78 -
GX_TEXMTX0), then ``0x98|vat`` triangle strips (also 0x80 quads / 0x90 triangles / 0xA0
fans): a u16 vertex count and per drawn vertex ``[pn matrix index][texmtx?][pos][nrm][uv]``
where the trailing three index bytes are always equal (Maya's exporter writes one index per
vertex).  Every bind-pose XF matrix in the palette is the identity - the vertices are
already composed (the Acclaim ``SKN`` archetype, not the bone-local one) - so the loads
matter only for animation and the per-vertex matrix bytes are skinning we do not resolve.

A second, **colored** vertex layout has no normal - 14 bytes:
``[u16 misc (1, or a bone id)][u16 u][u16 v][s16 x y z][u16 RGB565 color]`` - used by the
unlit props (backboards, coaches' rigs).  Its draws may be INDEX16, and its array can sit
before *or after* its display list.

**The engine repoints the CP array base between display lists** (that is why index bytes
stay 8-bit under arrays far past 256 entries), and the base lives in the node graph, which
is not mapped.  The reader recovers it empirically: display-list sections group into meshes
wherever the index window restarts, and the base is solved by **normal congruence** - at
the true base the stored vertex normals agree with the triangle normals the positions make
(cosine ~0.95 at the solution, ~0.5 shuffled).  The colored layout, with no normals to
check, is solved by address instead: minimum mean log strip-edge length, guarded by hard
structural filters on the misc and uv fields.  The quantitative checks that pinned the
format: the ``ballhi`` sphere decodes to 170 vertices at radius 16383.3 +- 0.3 with
position/normal cosine >= 0.9992, and the light-pyramid record decodes to exactly 4 faces
of 3 vertices sharing face normals.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"ENCS"  # "SCNE" stored reversed, like every tag in these members
TAG_AT = 16
SIZE_AT = 20
HEADER = 16
ENTRY = 16
NORMAL_SCALE = 64.0
UV_SCALE = 256.0
MAX_RECORDS = 4096
MAX_DRAW = 20000
MIN_RUN = 4
#: |s8 normal| window that marks a vertex entry (unit normals at scale 64)
NORM_LO, NORM_HI = 50.0, 78.0
#: a solved base must reach this normal-congruence, or the mesh is declined
MIN_CONGRUENCE = 0.55


class SceneError(ValueError):
    pass


def is_scne(head: bytes) -> bool:
    return len(head) >= TAG_AT + 4 and head[TAG_AT : TAG_AT + 4] == MAGIC


def records(data: bytes) -> list[tuple[int, bytes, int]]:
    """The generic record run: ``(offset, tag, span)`` triples tiling the member."""
    out: list[tuple[int, bytes, int]] = []
    at = 0
    while at + HEADER + 8 <= len(data) and len(out) < MAX_RECORDS:
        tag = data[at + TAG_AT : at + TAG_AT + 4]
        if not all(0x20 <= c < 0x7F for c in tag):
            break
        size = struct.unpack_from(">I", data, at + SIZE_AT)[0]
        span = size + HEADER
        if size < 8 or at + span > len(data) + 31:  # final record may sit in trim slop
            break
        out.append((at, tag, min(span, len(data) - at)))
        at += span
    return out


@dataclass
class Mesh:
    positions: np.ndarray  # (N,3) f32, dequantized
    normals: np.ndarray | None  # (N,3) f32 - the colored layout has none
    uvs: np.ndarray  # (N,2) f32
    indices: np.ndarray  # (M,) u32 triangles
    base: int  # solved array base (entries for the 16-byte layout, bytes for the 14-byte)
    congruence: float  # normal-congruence (or edge-compactness) score at that base
    colors: np.ndarray | None = None  # (N,4) f32 from RGB565 vertex colors


# -- the pieces ---------------------------------------------------------------------------


def _norm_ok(rec: bytes, at: int) -> bool:
    nx, ny, nz = struct.unpack_from(">3b", rec, at + 8)
    return NORM_LO**2 <= nx * nx + ny * ny + nz * nz <= NORM_HI**2


def _vertex_runs(rec: bytes) -> list[tuple[int, int]]:
    """Maximal stride-16 runs of entries whose s8 normal has magnitude ~64."""
    runs: list[tuple[int, int]] = []
    n = len(rec)
    for at in range(0, n - ENTRY, 2):
        if not _norm_ok(rec, at):
            continue
        if at >= ENTRY and _norm_ok(rec, at - ENTRY):
            continue  # inside a longer run
        k = at
        while k + ENTRY <= n and _norm_ok(rec, k):
            k += ENTRY
        if (k - at) // ENTRY >= MIN_RUN:
            runs.append((at, (k - at) // ENTRY))
    runs.sort(key=lambda r: -r[1])
    kept: list[tuple[int, int]] = []
    for at, c in runs:
        if not any(a <= at < a + n2 * ENTRY for a, n2 in kept):
            kept.append((at, c))
    kept.sort()
    return kept


def _dequant(rec: bytes, before: int) -> np.ndarray:
    """The last position-dequantization matrix before ``before``: a row-major 4x4,
    diagonal scale in (0, 1), translation column, bottom row 0 0 0 1 - identity excluded
    (the bind-pose palette is identities).  Falls back to the identity."""
    best = np.eye(4, dtype=np.float64)
    for at in range(0, min(before, len(rec) - 64), 4):
        m = struct.unpack_from(">16f", rec, at)
        if m[15] != 1.0 or any(m[i] for i in (1, 2, 4, 6, 8, 9, 12, 13, 14)):
            continue
        if not all(0.0 < m[i] < 1.0 for i in (0, 5, 10)):
            continue
        if not all(abs(m[i]) < 1e6 for i in (3, 7, 11)):
            continue
        best = np.array(m, dtype=np.float64).reshape(4, 4)
    return best


def _verts(rec: bytes, at: int, count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    raw = np.frombuffer(rec[at : at + count * ENTRY], dtype=">i2").reshape(count, 8)
    pos = raw[:, 1:4].astype(np.float32)
    sb = np.frombuffer(rec[at : at + count * ENTRY], dtype=np.int8).reshape(count, 16)
    nrm = sb[:, 8:11].astype(np.float32) / NORMAL_SCALE
    u = raw[:, 0].astype(np.float32) / UV_SCALE  # s8.8 fixed point - wraps negative
    v = raw[:, 7].astype(np.float32) / UV_SCALE
    return pos, nrm, np.stack([u, v], axis=1)


def _entry_index(rec: bytes, at: int, stride: int, wide: bool) -> int:
    if wide:
        return struct.unpack_from(">H", rec, at + stride - 6)[0]
    return rec[at + stride - 3]


def _detect_stride(rec: bytes, at: int, count: int, hi: int) -> tuple[int, bool] | None:
    """Entries end in three equal index fields; find the byte stride (u8 or u16 fields)."""
    for stride, wide in ((4, False), (5, False), (6, False), (7, True), (8, True)):
        need = min(count, 12)
        hits = 0
        for k in range(need):
            p = at + k * stride
            if p + stride > hi:
                break
            if wide:
                a, b, c = struct.unpack_from(">3H", rec, p + stride - 6)
            else:
                a, b, c = rec[p + stride - 3 : p + stride]
            hits += a == b == c
        if hits >= need - 1 > 0:
            return stride, wide
    return None


def _parse_dls(rec: bytes, lo: int, hi: int) -> list[tuple[int, int, list[tuple[int, list[int]]]]]:
    """Display-list sections in ``rec[lo:hi]``: ``(start, end, [(op, indices), ...])``."""
    sections = []
    at = lo
    while at < hi - 5:
        op0 = rec[at]
        if op0 not in (0x20, 0x28, 0x30) and (op0 & 0xF8) not in (0x80, 0x90, 0x98, 0xA0):
            at += 1
            continue
        p = at
        draws: list[tuple[int, list[int]]] = []
        while p < hi:
            op = rec[p]
            if op in (0x20, 0x28, 0x30, 0x38):
                if p + 5 > hi:
                    break
                cmd = struct.unpack_from(">H", rec, p + 3)[0]
                if (cmd >> 12) + 1 not in (9, 12):
                    break
                p += 5
            elif (op & 0xF8) in (0x80, 0x90, 0x98, 0xA0):
                if p + 3 > hi:
                    break
                count = struct.unpack_from(">H", rec, p + 1)[0]
                if not 3 <= count <= MAX_DRAW:
                    break
                got = _detect_stride(rec, p + 3, count, hi)
                if got is None:
                    break
                stride, wide = got
                if p + 3 + count * stride > hi:
                    break
                idx = [_entry_index(rec, p + 3 + k * stride, stride, wide) for k in range(count)]
                draws.append((op & 0xF8, idx))
                p += 3 + count * stride
            elif op == 0x00:
                p += 1
            else:
                break
        if draws:
            sections.append((at, p, draws))
            at = p
        else:
            at += 1
    return sections


def _triangles(op: int, idx: list[int]) -> list[tuple[int, int, int]]:
    tris: list[tuple[int, int, int]] = []
    if op == 0x98:  # strip, degenerate-stitched
        for k in range(len(idx) - 2):
            a, b, c = idx[k : k + 3]
            if a in (b, c) or b == c:
                continue
            tris.append((a, b, c) if k % 2 == 0 else (a, c, b))
    elif op == 0x90:  # triangles
        for k in range(0, len(idx) - 2, 3):
            tris.append((idx[k], idx[k + 1], idx[k + 2]))
    elif op == 0xA0:  # fan
        for k in range(1, len(idx) - 1):
            tris.append((idx[0], idx[k], idx[k + 1]))
    elif op == 0x80:  # quads
        for k in range(0, len(idx) - 3, 4):
            a, b, c, d = idx[k : k + 4]
            tris += [(a, b, c), (a, c, d)]
    return tris


def _congruence(pos: np.ndarray, nrm: np.ndarray, tris: np.ndarray, base: int) -> float:
    t = tris + base
    a, b, c = pos[t[:, 0]], pos[t[:, 1]], pos[t[:, 2]]
    g = np.cross(b - a, c - a)
    gl = np.linalg.norm(g, axis=1)
    v = nrm[t[:, 0]] + nrm[t[:, 1]] + nrm[t[:, 2]]
    vl = np.linalg.norm(v, axis=1)
    keep = (gl > 1e-9) & (vl > 1e-9)
    if not keep.any():
        return 0.0
    return float(np.abs((g[keep] * v[keep]).sum(1) / (gl[keep] * vl[keep])).mean())


def _solve_base(
    pos: np.ndarray, nrm: np.ndarray, tris: np.ndarray, nverts: int, first: int
) -> tuple[int, float]:
    """The array base a mesh's 8-bit indices count from.  Preferred candidates first (0 and
    the end of the previous mesh's window), then a subsampled full scan."""
    maxi = int(tris.max())
    limit = nverts - maxi
    if limit <= 0:
        return 0, 0.0
    sample = tris if len(tris) <= 300 else tris[:: len(tris) // 300 + 1]
    preferred = [b for b in {0, first} if 0 <= b < limit]
    best, best_s = 0, -1.0
    for b in preferred:
        s = _congruence(pos, nrm, tris, b)
        if s > best_s:
            best, best_s = b, s
    if best_s < 0.9:
        for b in range(limit):
            s = _congruence(pos, nrm, sample, b)
            if s > best_s:
                best, best_s = b, s
        best_s = _congruence(pos, nrm, tris, best)
    return best, best_s


#: the second vertex layout - no normal, a vertex color instead, 14 bytes:
#: ``[u16 misc (1, or a bone id)] [u16 u] [u16 v] [s16 x y z] [u16 RGB565 color]``
CENTRY = 14
CPOS_AT = 6
#: an accepted colored-layout mesh must have MEDIAN strip edge under this fraction of its
#: bounding-box diagonal - the median, not the RMS, because real meshes carry genuinely
#: long triangles (the basket pole); random addresses score ~0.5, wrong phases ~0.08
MAX_EDGE_FRACTION = 0.045


def _cverts(rec: bytes, at: int, count: int):
    raw = np.frombuffer(rec[at : at + count * CENTRY], dtype=">i2").reshape(count, 7)
    pos = raw[:, 3:6].astype(np.float32)
    u = raw[:, 1].astype(np.float32) / UV_SCALE
    v = raw[:, 2].astype(np.float32) / UV_SCALE
    c = raw[:, 6].astype(np.uint16)
    colors = np.stack(
        [
            (c >> 11) / 31.0,
            ((c >> 5) & 0x3F) / 63.0,
            (c & 0x1F) / 31.0,
            np.ones(count),
        ],
        axis=1,
    ).astype(np.float32)
    return pos, np.stack([u, v], axis=1).astype(np.float32), colors


def _edge_fraction(rec: bytes, tris: np.ndarray, at: int) -> float:
    """Median strip-edge length over the bounding-box diagonal for the 14-byte layout
    array at ``at`` - the score ``_solve_addr`` optimizes, for one known address."""
    need = int(tris.max()) + 1
    if at + need * CENTRY > len(rec):
        return 1.0
    raw = np.frombuffer(rec[at : at + need * CENTRY], dtype=">i2").reshape(need, 7)
    pos = raw[:, 3:6].astype(np.float32)
    used = np.unique(tris)
    diag = float(np.linalg.norm(pos[used].max(0) - pos[used].min(0)))
    if diag < 1.0:
        return 1.0
    d = pos[tris[:, 0]] - pos[tris[:, 1]]
    return float(np.median(np.sqrt((d * d).sum(1)))) / diag


def _solve_addr(rec: bytes, tris: np.ndarray, need: int, gstart: int) -> tuple[int, float]:
    """Where a 14-byte-entry vertex array starts: the byte address (the array may sit
    before *or after* its display list, and stride 14 alternates parity, so every address
    within 16KB of the section is tried) minimizing the mesh's RMS strip-edge length
    relative to its bounding box.  Returns ``(address, edge_fraction)``; -1 if none fits."""
    lo = max(0, gstart - need * CENTRY - 16384)
    hi = min(len(rec) - need * CENTRY, gstart + 16384)
    if hi <= lo:
        return -1, 1.0
    used = np.unique(tris)
    edges = np.unique(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [0, 2]]]), axis=0)
    if len(edges) > 300:
        edges = edges[:: len(edges) // 300 + 1]
    remap = np.full(int(used.max()) + 1, -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    e0, e1 = remap[edges[:, 0]], remap[edges[:, 1]]
    halves = (
        np.frombuffer(rec, dtype=">i2", count=len(rec) // 2),
        np.frombuffer(rec[1:], dtype=">i2", count=(len(rec) - 1) // 2),
    )
    gather = used * (CENTRY // 2)
    best, best_ml, best_f = -1, np.inf, 1.0
    for at in range(lo, hi):
        p = at & 1
        arr = halves[p]
        mbase = (at - p) // 2
        idx = mbase + gather
        if idx[-1] + (CPOS_AT // 2) + 2 >= len(arr):
            continue
        # hard filters: the leading u16 of every used entry is a small id (1, or a bone),
        # and the two uv fields are s8.8 texture coordinates of sane magnitude - a wrong
        # phase puts position bytes in these slots and fails one or the other
        misc = arr[idx]
        if bool(((misc < 0) | (misc >= 0x100)).any()):
            continue
        u, v = arr[idx + 1], arr[idx + 2]
        if bool((np.abs(u) > 0x1000).any()) or bool((np.abs(v) > 0x1000).any()):
            continue
        pi = idx + CPOS_AT // 2
        pos = np.stack([arr[pi], arr[pi + 1], arr[pi + 2]], axis=1).astype(np.float32)
        diag = float(np.linalg.norm(pos.max(0) - pos.min(0)))
        if diag < 1.0:
            continue
        d = pos[e0] - pos[e1]
        lens = np.sqrt((d * d).sum(1))
        med = float(np.median(lens))
        if med < 1e-3 * diag:
            continue  # coincident-vertex degenerates game every mean
        # selection is by mean log edge length, UN-normalized: dividing by the bounding
        # box lets junk in a shifted read inflate the box and win, and the log keeps the
        # genuinely long triangles real meshes carry (the basket pole) from drowning the
        # signal while still charging a shifted read for its wrapped-seam outliers
        ml = float(np.mean(np.log1p(lens)))
        if ml < best_ml:
            best, best_ml, best_f = at, ml, med / diag
    return best, best_f


# -- the reader ---------------------------------------------------------------------------


def meshes(rec: bytes) -> list[Mesh]:
    """Every mesh of one ``ENCS`` record whose solved base passes the congruence gate.

    Display lists are parsed over the whole record (byte runs that merely *look* like
    vertex entries occur inside display-list data, so section search is never windowed by
    the next run); each section is then bound to the nearest preceding vertex run large
    enough for its indices.  Sections inside a solid run are the run's own bytes, skipped.
    """
    if rec[TAG_AT : TAG_AT + 4] != MAGIC:
        return []
    runs = _vertex_runs(rec)
    arrays = [(at, c) for at, c in runs if c >= 8]
    sections = [
        (start, end, draws)
        for start, end, draws in _parse_dls(rec, 0, len(rec))
        if not any(at <= start < at + c * ENTRY for at, c in arrays)
    ]
    # bind sections to arrays, then group their draws into meshes: a new mesh wherever
    # the index window restarts (the engine repoints the array base there).  Sections no
    # stride-16 run can serve go to the colored-layout solver instead (run -1).
    per_run: dict[int, list[tuple[int, list[tuple[int, list[int]]]]]] = {}
    tops: dict[int, int] = {}
    for start, _end, draws in sections:
        maxi = max(max(idx) for _op, idx in draws)
        run = next(
            (
                i
                for i in range(len(arrays) - 1, -1, -1)
                if arrays[i][0] + arrays[i][1] * ENTRY <= start and arrays[i][1] > maxi
            ),
            -1,
        )
        groups = per_run.setdefault(run, [])
        for op, idx in draws:
            if not groups or min(idx) < tops[run] - 8:
                groups.append((start, []))
                tops[run] = 0
            groups[-1][1].append((op, idx))
            tops[run] = max(tops[run], max(idx))

    out: list[Mesh] = []
    for run, groups in sorted(per_run.items()):
        if run >= 0:
            vat, vcount = arrays[run]
            pos_q, nrm, uv = _verts(rec, vat, vcount)
            m = _dequant(rec, vat)
            pos = (pos_q @ m[:3, :3].T + m[:3, 3]).astype(np.float32)
        cursor = 0
        for gstart, draws in groups:
            tris: list[tuple[int, int, int]] = []
            for op, idx in draws:
                tris += _triangles(op, idx)
            if not tris:
                continue
            tarr = np.asarray(tris, dtype=np.int64)
            if run >= 0:
                base, score = _solve_base(pos, nrm, tarr, vcount, cursor)
                cursor = base + int(tarr.max()) + 1
                if score < MIN_CONGRUENCE:
                    continue
                out.append(
                    Mesh(
                        positions=pos,
                        normals=nrm.astype(np.float32),
                        uvs=uv.astype(np.float32),
                        indices=(tarr + base).reshape(-1).astype(np.uint32),
                        base=base,
                        congruence=score,
                    )
                )
            else:
                need = int(tarr.max()) + 1
                at, frac = _solve_addr(rec, tarr, need, gstart)
                if at < 0 or frac > MAX_EDGE_FRACTION or at + need * CENTRY > len(rec):
                    continue
                cpos, cuv, ccol = _cverts(rec, at, need)
                m = _dequant(rec, at)
                cpos = (cpos @ m[:3, :3].T + m[:3, 3]).astype(np.float32)
                out.append(
                    Mesh(
                        positions=cpos,
                        normals=None,
                        uvs=cuv,
                        indices=tarr.reshape(-1).astype(np.uint32),
                        base=at,
                        congruence=1.0 - frac,
                        colors=ccol,
                    )
                )
    return out
