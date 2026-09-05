"""The standard hypothesis battery for unknown member bytes - a REPORTING tool, not a reader.

Eight GameCube formats fell in one night (2026-09-04: Skye SKX/skg, Acclaim SKN, VC SCNE,
Gun .mpk, TR Legend DRM, ...) and every crack opened with the same first hour: run the
standard hypothesis tests, see which fire, and only then start thinking.  This module is
that first hour, productized.  Given a member's bytes it runs every named probe and emits a
structured :class:`Report` of what fired with the evidence, so a session starts a format
crack at step 5 instead of step 0.

It deliberately ships **no reader** - a probe that fires is a lead, not a decode.  The
grading discipline comes from :mod:`gcrip.oracles`: a check must be able to FAIL on wrong
data to be evidence, so every probe here states what it measured, and the exported oracle
utilities implement the anti-gaming guards those notes demand (percentile extents against
outliers, distinct-value counts against constant runs, collapse detection against the
degenerate "solutions" that gamed the Skye and VC metric oracles - the render gate stays
mandatory, so :func:`render_wireframe` is here too).

The probes and the archetypes they map to are drawn from the cracked formats' own notes
(``docs/formats/*.md`` and the format modules' docstrings):

* container tables that tile the buffer to the byte (VC DAT, CD bigfile, LOTR SHOC),
* GX display-list walks at strides 5-16, with and without CP setup (Taz, SKN, Gun,
  TR Legend's naked lists),
* vertex-array scent: f32 xyz runs, s16 at the standard fixed points (/256 /1024 /4096
  /16384), s8 and s16 unit-normal runs, uv runs, unit-quaternion runs (skg keys),
  orthonormal-matrix runs (SKX joint tables),
* skeleton scent: parent-index forests and bone-name tables,
* codec scent: zlib sniffs, the per-page entropy map that mapped Gun's regions,
  repeated-fill detection (the ``AB AB`` placeholder lesson).

usage: ``python -m gcrip.autocrack <file>``
"""

from __future__ import annotations

import re
import struct
import sys
import time
import zlib
from dataclasses import dataclass, field

import numpy as np

# -- caps: a 50 MB member must finish in well under a minute -------------------------------
PAGE = 4096
MAX_TABLE_START = 256  # container tables live near the head
MAX_TABLE_ROWS = 8192
MAX_GX_STARTS = 2500
MAX_GX_PRIMS = 4096
MAX_PARENT_STARTS = 2500
MAX_ZLIB_SITES = 400
MAX_STRINGS = 200_000
GX_BUDGET = 20.0  # seconds for the display-list walk alone

_PRIM_KINDS = frozenset(range(0x80, 0xC0, 8))  # 0x80..0xB8 GX draw opcodes (low 3 bits = VAT)
_FIXED_POINTS = (256.0, 1024.0, 4096.0, 16384.0)
_STRING_RE = re.compile(rb"[\x20-\x7e]{3,63}\x00")
_BONE_RE = re.compile(
    r"root|spine|neck|head|pelvis|hip|clavicle|collar|humerus|femur|arm|leg|hand|foot|"
    r"toe|finger|thumb|jaw|tail|bip01|^[lr]_|_[lr]$",
    re.IGNORECASE,
)


@dataclass
class ProbeResult:
    """One named hypothesis test: did it fire, on what evidence, with what parameters."""

    name: str
    fired: bool
    evidence: str
    params: dict = field(default_factory=dict)


@dataclass
class Report:
    size: int
    probes: list[ProbeResult]
    archetypes: list[tuple[str, str]]  # (archetype name, evidence line)
    elapsed: float = 0.0

    def probe(self, name: str) -> ProbeResult | None:
        return next((p for p in self.probes if p.name == name), None)

    def fired(self) -> list[str]:
        return [p.name for p in self.probes if p.fired]

    def summary(self) -> str:
        lines = [
            f"autocrack: {self.size:,} bytes - {len(self.fired())}/{len(self.probes)} "
            f"probes fired in {self.elapsed:.1f}s"
        ]
        for p in self.probes:
            mark = "x" if p.fired else " "
            lines.append(f"  [{mark}] {p.name:<22} {p.evidence}")
        if self.archetypes:
            lines.append("archetype suggestions:")
            for name, why in self.archetypes:
                lines.append(f"  * {name}: {why}")
        else:
            lines.append("archetype suggestions: none - see the probe evidence above")
        return "\n".join(lines)


# ==========================================================================================
# small shared helpers
# ==========================================================================================


def _longest_run(mask: np.ndarray) -> tuple[int, int]:
    """(start, length) of the longest run of True."""
    if mask.size == 0 or not mask.any():
        return 0, 0
    m = np.concatenate(([False], mask, [False]))
    d = np.diff(m.astype(np.int8))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    k = int(np.argmax(ends - starts))
    return int(starts[k]), int(ends[k] - starts[k])


def _f32_runs(data: bytes, min_words: int = 36) -> list[tuple[int, int]]:
    """(byte offset, byte length) of maximal runs of plausible big-endian f32 words
    (exponent within ~1e-8..2e6, or exactly zero)."""
    n = len(data)
    if n < 16:
        return []
    arr = np.frombuffer(data, ">u4", n // 4)
    exp = (arr >> 23) & 0xFF
    ok = ((exp >= 0x66) & (exp <= 0x94)) | (arr == 0)
    bad = np.flatnonzero(~ok)
    edges = np.concatenate(([-1], bad, [len(ok)]))
    return [
        (int(a + 1) * 4, int(b - a - 1) * 4)
        for a, b in zip(edges[:-1], edges[1:], strict=True)
        if b - a - 1 >= min_words
    ]


def _rolling_sum(v: np.ndarray, k: int) -> np.ndarray:
    c = np.concatenate(([0.0], np.cumsum(v, dtype=np.float64)))
    return c[k:] - c[:-k]


def _strings(data: bytes) -> list[tuple[int, int]]:
    """(offset, char length) of NUL-terminated printable ASCII strings of 3+ chars."""
    out = []
    for m in _STRING_RE.finditer(data):
        out.append((m.start(), m.end() - m.start() - 1))
        if len(out) >= MAX_STRINGS:
            break
    return out


def _pct(x: float) -> str:
    return f"{100.0 * x:.0f}%"


# ==========================================================================================
# 1. container probes
# ==========================================================================================


def probe_chunk_stream(data: bytes) -> ProbeResult:
    """Tag+size chunk runs that tile the buffer - the SHOC / VC-record archetype.

    Three header shapes are walked from offset 0: ``tag u32-size`` with the size including
    the 8-byte header (SHOC), the same with the size excluding it, and the VC record frame
    (16 opaque bytes, then tag at +16 and size at +20, span ``size + 16``).
    """
    n = len(data)
    shapes = (
        ("tag+size incl. header", 0, 4, 0),
        ("tag+size excl. header", 0, 4, 8),
        ("16-byte frame + tag + size", 16, 20, 16),
    )
    best = None
    for label, tag_at, size_at, extra in shapes:
        for endian in (">", "<"):
            at, chunks, tags = 0, 0, []
            while at + max(tag_at, size_at) + 4 <= n and chunks < 1 << 16:
                tag = data[at + tag_at : at + tag_at + 4]
                if not all(0x20 <= c < 0x7F for c in tag):
                    break
                size = struct.unpack_from(endian + "I", data, at + size_at)[0]
                span = size + extra
                if span < 8 or at + span > n:
                    break
                if len(tags) < 6 and tag not in tags:
                    tags.append(tag)
                chunks += 1
                at += span
            coverage = at / n if n else 0.0
            if chunks >= 4 and coverage >= 0.9:
                cand = (chunks, coverage, label, endian, tags, at)
                if best is None or cand[:2] > best[:2]:
                    best = cand
    if best is None:
        return ProbeResult("chunk-stream", False, "no tag+size chunk run tiles the buffer")
    chunks, coverage, label, endian, tags, end = best
    names = ", ".join(t.decode("ascii", "replace") for t in tags)
    return ProbeResult(
        "chunk-stream",
        True,
        f"{chunks} chunks ({label}, {'BE' if endian == '>' else 'LE'}) tile {_pct(coverage)} "
        f"of the buffer; tags: {names}",
        {"chunks": chunks, "coverage": coverage, "shape": label, "endian": endian, "end": end},
    )


def _table_columns(data: bytes, start: int, stride: int, endian: str) -> np.ndarray | None:
    rows = min((len(data) - start) // stride, MAX_TABLE_ROWS)
    if rows < 8:
        return None
    cols = stride // 4
    return np.frombuffer(data, endian + "u4", rows * cols, start).reshape(rows, cols)


def probe_tiling_table(data: bytes) -> ProbeResult:
    """Offset/size table candidates whose spans tile the buffer to the byte.

    u32 pairs/triples at strides 8-32, both endians, table start within the first 256
    bytes.  This is the identity that shipped the VC DAT container ("the member spans
    account for every byte") - a wrong column pairing cannot tile.  Small constant
    alignment padding between spans (up to 32 bytes) is tolerated and reported.
    """
    n = len(data)
    best = None
    for endian in (">", "<"):
        for stride in (8, 12, 16, 20, 24, 28, 32):
            for start in range(0, min(MAX_TABLE_START + 1, n), 4):
                t = _table_columns(data, start, stride, endian)
                if t is None:
                    continue
                cols = t.shape[1]
                v = t.astype(np.int64)
                # a column can be the offset column only if it is in-bounds and ascending
                plaus = [
                    c
                    for c in range(cols)
                    if v[0, c] < n
                    and v[:, c].max() <= n
                    and float(np.mean(np.diff(v[:16, c]) >= 0)) >= 0.85
                ]
                for oc in plaus:
                    off = v[:, oc]
                    for sc in range(cols):
                        if sc == oc:
                            continue
                        size = v[:, sc]
                        gap = off[1:] - (off[:-1] + size[:-1])
                        good = (gap >= 0) & (gap < 32) & (off[1:] > off[:-1])
                        lead = len(good) if good.all() else int(np.argmin(good))
                        run = 1 + lead
                        if run < 8:
                            continue
                        end = int(off[run - 1] + size[run - 1])
                        covered = (end - int(off[0])) / n
                        exact = bool(np.all(gap[: run - 1] == 0))
                        near_end = n - end < 2048
                        if not (near_end or (exact and covered >= 0.5)):
                            continue
                        cand = (run, covered, start, stride, endian, oc, sc, exact, end)
                        if best is None or (run, covered) > (best[0], best[1]):
                            best = cand
    if best is None:
        return ProbeResult(
            "container-tiling", False, "no u32 offset/size table tiles the buffer"
        )
    run, covered, start, stride, endian, oc, sc, exact, end = best
    return ProbeResult(
        "container-tiling",
        True,
        f"{run} entries at +0x{start:x}, stride {stride} ({'BE' if endian == '>' else 'LE'}), "
        f"offset col {oc} / size col {sc}: spans tile {_pct(covered)} "
        f"({'byte-exact' if exact else 'with alignment padding'}, last end 0x{end:x})",
        {
            "start": start,
            "stride": stride,
            "endian": endian,
            "offset_col": oc,
            "size_col": sc,
            "entries": run,
            "exact": exact,
        },
    )


def probe_ascending_table(data: bytes) -> ProbeResult:
    """Ascending u32 columns - offset tables without sizes, and sorted hash arrays
    (the CD bigfile identity: 4,314 strictly ascending hashes is what a sorted lookup
    table looks like and what nothing else in a header does)."""
    n = len(data)
    best = None
    for stride in (4, 8, 12, 16, 20, 24, 28, 32):
        for start in range(0, min(MAX_TABLE_START + 1, n), 4):
            rows = min((n - start) // stride, 1 << 14)
            if rows < 16:
                continue
            cols = stride // 4
            t = np.frombuffer(data, ">u4", rows * cols, start).reshape(rows, cols)
            for c in range(cols):
                v = t[:, c].astype(np.int64)
                asc = np.diff(v) > 0
                run0 = int(np.argmin(asc)) + 1 if not asc.all() else len(v)
                if run0 < 16:
                    continue
                in_bounds = v[run0 - 1] <= n
                kind = "offset-like (in bounds)" if in_bounds else "hash-like (full u32)"
                cand = (run0, start, stride, c, kind, int(v[run0 - 1]))
                if best is None or run0 > best[0]:
                    best = cand
    if best is None:
        return ProbeResult("ascending-offsets", False, "no ascending u32 column found")
    run0, start, stride, c, kind, last = best
    return ProbeResult(
        "ascending-offsets",
        True,
        f"{run0} strictly ascending u32 at +0x{start:x} stride {stride} col {c}, "
        f"{kind}, last 0x{last:x}",
        {"start": start, "stride": stride, "col": c, "entries": run0, "kind": kind},
    )


def probe_name_tables(data: bytes) -> ProbeResult:
    """Runs of NUL-terminated printable strings at the fixed strides real name tables use
    (16/32/36/64 - SKN bones are char[32], SKX's header name is char[36]) plus dense
    back-to-back name lists (the Skye ``.pak`` shape)."""
    strs = _strings(data)
    hits: list[tuple[str, int, int, list[str]]] = []
    if len(strs) >= 4:
        starts = np.array([s for s, _ in strs], dtype=np.int64)
        lens = np.array([ln for _, ln in strs], dtype=np.int64)
        d = np.diff(starts)
        for stride in (16, 32, 36, 64):
            ok = (d == stride) & (lens[:-1] < stride)
            at, run = _longest_run(ok)
            if run >= 3:  # run of diffs -> run+1 strings
                names = [
                    data[starts[i] : starts[i] + lens[i]].decode("ascii", "replace")
                    for i in range(at, min(at + 4, len(strs)))
                ]
                hits.append((f"stride {stride}", int(starts[at]), run + 1, names))
        dense = (d == lens[:-1] + 1) | (d == lens[:-1] + 2)
        at, run = _longest_run(dense)
        if run >= 7:
            names = [
                data[starts[i] : starts[i] + lens[i]].decode("ascii", "replace")
                for i in range(at, min(at + 4, len(strs)))
            ]
            hits.append(("back-to-back", int(starts[at]), run + 1, names))
    if not hits:
        return ProbeResult("name-table", False, "no fixed-stride or dense name runs")
    hits.sort(key=lambda h: -h[2])
    kind, at, count, names = hits[0]
    return ProbeResult(
        "name-table",
        True,
        f"{count} strings ({kind}) at 0x{at:x}: {', '.join(repr(x) for x in names)} ...",
        {"tables": [{"kind": k, "at": a, "count": c, "first": nm} for k, a, c, nm in hits]},
    )


# ==========================================================================================
# 2. GX display-list probes
# ==========================================================================================


@dataclass
class _Walk:
    start: int
    end: int
    stride: int
    prims: int
    verts: int
    ops: set
    vertex_bytes: np.ndarray | None  # (V, stride) u8, capped


def _gx_walk(data: bytes, start: int, stride: int) -> _Walk | None:
    """Tolerant walk accepting NOPs, CP loads (0x08, 6 bytes), XF loads (0x10, variable),
    indexed-XF loads (0x20/0x28/0x30/0x38, 5 bytes), BP loads (0x61, 5 bytes) and
    draw ops 0x80-0xbf (u16 count, count*stride bytes).  Stops quietly at anything else."""
    n = len(data)
    i = start
    prims = verts = 0
    ops: set[int] = set()
    rows: list[np.ndarray] = []
    pad = 0
    while i < n and prims < MAX_GX_PRIMS:
        op = data[i]
        if op == 0x00:
            pad += 1
            if pad > 64:
                break
            i += 1
            continue
        pad = 0
        if op == 0x08:
            if i + 6 > n:
                break
            ops.add(0x08)
            i += 6
            continue
        if op == 0x10:
            if i + 5 > n:
                break
            cnt = struct.unpack_from(">H", data, i + 1)[0]
            if cnt > 255:
                break
            ops.add(0x10)
            i += 5 + 4 * (cnt + 1)
            continue
        if op in (0x20, 0x28, 0x30, 0x38, 0x61):
            if i + 5 > n:
                break
            ops.add(op)
            i += 5
            continue
        kind = op & 0xF8
        if kind in _PRIM_KINDS:
            if i + 3 > n:
                break
            nv = struct.unpack_from(">H", data, i + 1)[0]
            if nv == 0 or nv > 8192 or i + 3 + nv * stride > n:
                break
            ops.add(kind)
            if verts < 20000:
                rows.append(np.frombuffer(data, np.uint8, nv * stride, i + 3))
            prims += 1
            verts += nv
            i += 3 + nv * stride
            continue
        break
    if prims == 0:
        return None
    vb = np.concatenate(rows).reshape(-1, stride) if rows else None
    return _Walk(start, i, stride, prims, verts, ops, vb)


def probe_gx_display_lists(data: bytes, deadline: float | None = None) -> ProbeResult:
    """Opcode walks at vertex strides 5-16 from every draw-op candidate (greedy skip over
    claimed spans, like gxscan).  Reports clean-walk spans, primitive and vertex totals,
    the dominant stride, per-attribute max indices of the best span (via gxscan's field
    inference), and whether the lists are *naked* - no CP (0x08) setup, the TR Legend /
    Gun shape that hid from gxscan."""
    from gcrip.gxscan import field_values, infer_fields

    n = len(data)
    if n < 16:
        return ProbeResult("gx-display-list", False, "buffer too small")
    b = np.frombuffer(data, np.uint8)
    opk = b[:-2] & 0xF8
    is_op = np.zeros(len(opk), bool)
    for k in _PRIM_KINDS:
        is_op |= opk == k
    count = (b[1:-1].astype(np.uint32) << 8) | b[2:]
    starts = np.flatnonzero(is_op & (count >= 3) & (count <= 8192))
    walks: list[_Walk] = []
    skip_to = 0
    processed = 0
    for p in starts:
        p = int(p)
        if p < skip_to:
            continue
        if processed >= MAX_GX_STARTS or (deadline and time.monotonic() > deadline):
            break
        processed += 1
        best: _Walk | None = None
        for stride in range(5, 17):
            w = _gx_walk(data, p, stride)
            if w is None:
                continue
            # an accidental chain is one or two giant primitives; real lists are many
            # modest ones (the gxscan salvage lesson: one spurious chain buries the rest)
            if w.prims < 3 and (w.verts < 24 or w.verts / w.prims > 1024):
                continue
            if best is None or (w.prims, w.end - w.start) > (best.prims, best.end - best.start):
                best = w
        if best is not None:
            walks.append(best)
            skip_to = best.end
        else:
            skip_to = p + 1
    if not walks:
        return ProbeResult("gx-display-list", False, "no opcode walk chains at any stride 5-16")
    total_prims = sum(w.prims for w in walks)
    total_verts = sum(w.verts for w in walks)
    if total_verts < 100 and not any(w.prims >= 4 for w in walks):
        return ProbeResult(
            "gx-display-list",
            False,
            f"only {len(walks)} weak chains ({total_prims} prims, {total_verts} verts) - "
            "below evidence threshold",
            {"spans": len(walks), "prims": total_prims, "verts": total_verts},
        )
    stride_hist: dict[int, int] = {}
    for w in walks:
        stride_hist[w.stride] = stride_hist.get(w.stride, 0) + w.prims
    dom_stride = max(stride_hist, key=lambda s: stride_hist[s])
    best = max(walks, key=lambda w: (w.prims, w.verts))
    fields = []
    if best.vertex_bytes is not None:
        for off, size in infer_fields(best.vertex_bytes):
            mx = int(field_values(best.vertex_bytes, off, size).max())
            fields.append({"at": off, "size": size, "max": mx})
    has_cp = any(0x08 in w.ops for w in walks)
    has_ixf = any(w.ops & {0x20, 0x28, 0x30, 0x38} for w in walks)
    naked = not has_cp and not any(0x10 in w.ops for w in walks)
    # setup only counts as evidence inside a span that also chains several primitives -
    # a lone 0x08 byte in noise is nothing (the strong test below uses it that way)
    setup_ops = {0x08, 0x10, 0x20, 0x28, 0x30, 0x38}
    setup = (
        "naked lists (no CP/XF setup - engine binds arrays, the TR Legend/Gun-prop shape)"
        if naked
        else "with " + "/".join(
            s
            for s, y in (("CP", has_cp), ("XF", any(0x10 in w.ops for w in walks)),
                         ("indexed-XF", has_ixf))
            if y
        ) + " loads"
    )
    fmax = ", ".join(
        f"+{f['at']}:{'u16' if f['size'] == 2 else 'u8'} max {f['max']}" for f in fields
    )
    # what 8 MB of pure noise produces: hundreds of 1-4-prim chains averaging >1,000
    # verts/prim.  Real lists have a dense span (many prims at one stride) or a span
    # where setup ops chain with several modest-count prims - that is what "fired" needs.
    strong = best.prims >= 6 or any(
        w.prims >= 4 and (w.ops & setup_ops) and w.verts / w.prims <= 512 for w in walks
    )
    grade = "" if strong else "WEAK (sparse accidental-looking chains): "
    return ProbeResult(
        "gx-display-list",
        strong,
        f"{grade}{len(walks)} clean spans, {total_prims} prims / {total_verts:,} verts, dominant "
        f"stride {dom_stride}, {setup}; best span 0x{best.start:x}..0x{best.end:x} "
        f"(stride {best.stride}, {best.prims} prims) fields: {fmax}",
        {
            "spans": len(walks),
            "prims": total_prims,
            "verts": total_verts,
            "stride_hist": stride_hist,
            "naked": naked,
            "strong": strong,
            "has_cp": has_cp,
            "has_indexed_xf": has_ixf,
            "best": {
                "start": best.start,
                "end": best.end,
                "stride": best.stride,
                "prims": best.prims,
                "verts": best.verts,
                "fields": fields,
            },
        },
    )


# ==========================================================================================
# 3. vertex-array probes
# ==========================================================================================


def probe_f32_positions(data: bytes) -> ProbeResult:
    """f32 xyz runs: finite, plausible extents, and - the discredited-oracle guard - the
    three components of a triple must actually differ (index buffers read as xyz have them
    nearly equal; see gcrip.oracles 'triangle locality')."""
    runs = sorted(_f32_runs(data), key=lambda r: -r[1])[:8]
    best = None
    for off, length in runs:
        f = np.frombuffer(data, ">f4", length // 4, off).astype(np.float64)
        for phase in (0, 1, 2):
            m = (len(f) - phase) // 3
            if m < 48:
                continue
            v = f[phase : phase + m * 3].reshape(m, 3)
            differ = float(np.mean(~((v[:, 0] == v[:, 1]) & (v[:, 1] == v[:, 2]))))
            nz = float(np.mean(np.any(v != 0, axis=1)))
            lo = np.percentile(v, 10, axis=0)
            hi = np.percentile(v, 90, axis=0)
            extent = float(np.linalg.norm(hi - lo))
            if differ < 0.85 or nz < 0.5 or not np.isfinite(extent):
                continue
            if not 1e-4 < extent < 1e7:
                continue
            cand = (m, off + phase * 4, extent, differ)
            if best is None or m > best[0]:
                best = cand
    if best is None:
        return ProbeResult("f32-positions", False, "no plausible f32 xyz run")
    m, at, extent, differ = best
    return ProbeResult(
        "f32-positions",
        True,
        f"{m:,} f32 triples at 0x{at:x}, 10-90pct extent {extent:.4g}, "
        f"components differ on {_pct(differ)}",
        {"at": at, "triples": m, "extent": extent, "differ": differ},
    )


def probe_s16_fixed(data: bytes) -> ProbeResult:
    """s16 vertex-array scent at the standard fixed points seen in the cracked formats
    (/256 SKN, /1024 Skye+LOTR, /4096 uv, /16384 normals).  Pages of 1 KB are scored on
    value plausibility and neighboring-value variety; a contiguous plausible region is
    reported with its per-divisor dequantized extent.  WEAK by nature - any bytes read as
    s16 - so this ranks regions, it does not accept them."""
    n = len(data)
    if n < 2048:
        return ProbeResult("s16-fixed-point", False, "buffer too small")
    words = np.frombuffer(data, ">i2", n // 2).astype(np.int32)
    page = 512  # words -> 1 KB pages
    npages = len(words) // page
    if npages < 2:
        return ProbeResult("s16-fixed-point", False, "buffer too small")
    w = words[: npages * page].reshape(npages, page)
    mag_ok = np.mean((np.abs(w) > 4) & (np.abs(w) < 0x6000), axis=1)
    vary = np.mean(np.abs(np.diff(w, axis=1)) > 0, axis=1)
    # 0.82 sits above what uniform noise reaches (max 0.81 over 8k pages) and below what
    # real s16 vertex regions score (0.84-1.0 on SKN / SKX)
    score = (mag_ok > 0.82) & (vary > 0.6)
    at, run = _longest_run(score)
    if run < 2:
        return ProbeResult(
            "s16-fixed-point", False, "no contiguous region reads as varied mid-range s16"
        )
    lo_b, span_b = at * page * 2, run * page * 2
    seg = words[at * page : (at + run) * page]
    extents = {
        int(fp): round(float(np.percentile(np.abs(seg), 98)) / fp, 4) for fp in _FIXED_POINTS
    }
    return ProbeResult(
        "s16-fixed-point",
        True,
        f"{span_b // 1024} KB plausible s16 region at 0x{lo_b:x}; 98pct |value| dequantized: "
        + ", ".join(f"/{k}={v:g}" for k, v in extents.items()),
        {"at": lo_b, "bytes": span_b, "extents": extents},
    )


def _unit_triple_runs(v: np.ndarray, scale: float, tol: float) -> tuple[int, int, int, int]:
    """(best index, packed run length in triples, record stride, strided count) over an
    int array: positions where three consecutive values form a unit vector at `scale`.
    The strided variant catches normals interleaved in vertex records (SKN 12/16-byte
    rows, VC 16-byte entries): the element stride at which unit triples repeat most."""
    if len(v) < 6:
        return 0, 0, 0, 0
    sq = v.astype(np.float64) ** 2
    s3 = sq[:-2] + sq[1:-1] + sq[2:]
    nrm = np.sqrt(s3) / scale
    unit = (np.abs(nrm - 1.0) < tol) & (s3 > 0)
    best_at, best_run = 0, 0
    for phase in (0, 1, 2):
        u = unit[phase::3]
        at, run = _longest_run(u)
        if run > best_run:
            best_at, best_run = phase + at * 3, run
    hits = int(np.count_nonzero(unit))
    stride, spairs = 0, 0
    if hits >= 24:
        for s in range(4, 33):
            if len(unit) <= 2 * s:
                break
            # a triple chain (unit at i, i+s, i+2s) is what noise cannot sustain
            chains = int(np.count_nonzero(unit[: -2 * s] & unit[s:-s] & unit[2 * s :]))
            if chains > spairs and chains >= max(24, hits // 4):
                stride, spairs = s, chains
    return best_at, best_run, stride, spairs


def probe_normal_runs(data: bytes) -> ProbeResult:
    """Unit-vector runs: s16 at /16384 (the run test that located Gun's global normal
    array) and s8 at /64 (LOTR, VC) or /127 (TR Legend), packed or at a fixed record
    stride (the VC 16-byte vertex has its s8 normal at +8 of every entry)."""
    n = len(data)
    found = []
    for parity in (0, 1):
        if n - parity < 12:
            continue
        h = np.frombuffer(data, ">i2", (n - parity) // 2, parity)
        at, run, stride, pairs = _unit_triple_runs(h, 16384.0, 0.02)
        if run >= 48 or stride:
            found.append(("s16 /16384", parity + at * 2, run, stride * 2, pairs))
    s8 = np.frombuffer(data, np.int8, n)
    for scale, label in ((64.0, "s8 /64"), (127.0, "s8 /127")):
        at, run, stride, pairs = _unit_triple_runs(s8, scale, 0.06)
        if run >= 48 or stride:
            found.append((label, at, run, stride, pairs))
    if not found:
        return ProbeResult("normal-runs", False, "no unit s16/s8 triple runs")
    found.sort(key=lambda f: -(f[2] + f[4]))
    label, at, run, stride, pairs = found[0]
    bits = []
    if run >= 8:
        bits.append(f"{run:,} packed triples at 0x{at:x}")
    if stride:
        bits.append(f"{pairs:,} strided hits repeating every {stride} bytes (record-interleaved)")
    return ProbeResult(
        "normal-runs",
        True,
        f"unit {label}: " + "; ".join(bits),
        {
            "runs": [
                {"kind": la, "at": a, "triples": r, "stride": s, "strided_pairs": p}
                for la, a, r, s, p in found
            ]
        },
    )


def probe_uv_runs(data: bytes) -> ProbeResult:
    """uv scent: f32 pairs inside [0,1] (the Skye lesson - floats in [0,1] on a textured
    model are uvs, not normalized geometry) and u16 pairs plausible at /4096."""
    hits = []
    for off, length in sorted(_f32_runs(data), key=lambda r: -r[1])[:8]:
        f = np.frombuffer(data, ">f4", length // 4, off)
        inrange = (f >= -0.01) & (f <= 1.02)
        at, run = _longest_run(inrange)
        if run >= 96 and len(np.unique(f[at : at + run])) >= 16:
            hits.append(("f32 [0,1]", off + at * 4, run // 2))
    n = len(data)
    if n >= 512:
        u = np.frombuffer(data, ">u2", n // 2)
        ok = u <= 4200
        at, run = _longest_run(ok)
        if run >= 256 and len(np.unique(u[at : at + min(run, 4096)])) >= 64:
            hits.append(("u16 /4096", at * 2, run // 2))
    if not hits:
        return ProbeResult("uv-runs", False, "no [0,1] f32 or /4096 u16 pair runs")
    hits.sort(key=lambda h: -h[2])
    kind, at, pairs = hits[0]
    return ProbeResult(
        "uv-runs",
        True,
        f"{pairs:,} plausible {kind} uv pairs at 0x{at:x}",
        {"runs": [{"kind": k, "at": a, "pairs": p} for k, a, p in hits]},
    )


_QUAT_FRAMES = ((4, "q4"), (5, "frame+q4 (skg key)"), (7, "t3+q4"), (8, "t3+q4+pad"))


def probe_quaternion_runs(data: bytes) -> ProbeResult:
    """Unit-quaternion runs under the framings the Skye .skg proved out: bare f32[4], the
    20-byte animation key (f32 frame + quat) and t3+q4 record shapes.  Distinct-value
    counting guards against a repeated constant looking like a result (the oracle note:
    358 distinct of 400 is what made the skg keys evidence)."""
    n = len(data)
    if n < 64:
        return ProbeResult("quaternion-runs", False, "buffer too small")
    with np.errstate(invalid="ignore", over="ignore"):
        f = np.frombuffer(data, ">f4", n // 4).astype(np.float64)
    f = np.nan_to_num(f, nan=9.0, posinf=9.0, neginf=-9.0)
    bad = ~np.isfinite(f) | (np.abs(f) > 1.001)
    sq = np.where(bad, 4.0, f) ** 2
    s4 = _rolling_sum(sq, 4)
    unit = np.abs(np.sqrt(s4) - 1.0) < 0.01
    best = None
    for stride, label in _QUAT_FRAMES:
        q_at = stride - 4  # the quat is the record's last 4 floats
        for phase in range(stride):
            u = unit[phase + q_at :: stride] if phase + q_at < len(unit) else np.zeros(0, bool)
            at, run = _longest_run(u)
            if run < 16:
                continue
            first = phase + q_at + at * stride
            run = min(run, (len(f) - first) // stride)
            if run < 16:
                continue
            qs = f[first : first + run * stride].reshape(-1, stride)[:, :4]
            distinct = len(np.unique(np.round(qs, 5), axis=0))
            if distinct < max(8, run // 4):
                continue
            cand = (run, distinct, label, (phase + at * stride) * 4, stride)
            if best is None or run > best[0]:
                best = cand
    if best is None:
        return ProbeResult("quaternion-runs", False, "no unit-quaternion run in any framing")
    run, distinct, label, at, stride = best
    return ProbeResult(
        "quaternion-runs",
        True,
        f"{run} unit quaternions ({distinct} distinct) as {label} records at 0x{at:x}",
        {"records": run, "distinct": distinct, "framing": label, "at": at, "stride_f32": stride},
    )


def probe_matrix_runs(data: bytes) -> ProbeResult:
    """Orthonormal 3x3 / 3x4 / 4x4 matrix runs (row norms ~1 AND row0.row1 ~ 0 - the
    orthogonality requirement is what stops a packed unit-normal array firing this).
    Reports the count and the dominant record stride (SKX joint rows are 128 bytes)."""
    n = len(data)
    if n < 64:
        return ProbeResult("matrix-runs", False, "buffer too small")
    with np.errstate(invalid="ignore", over="ignore"):
        f = np.frombuffer(data, ">f4", n // 4).astype(np.float64)
    f = np.nan_to_num(f, nan=9.0, posinf=9.0, neginf=-9.0)
    bad = ~np.isfinite(f) | (np.abs(f) > 2.0)
    g = np.where(bad, 3.0, f)
    sq = g * g
    r3 = np.sqrt(_rolling_sum(sq, 3))
    rowunit = np.abs(r3 - 1.0) < 0.02
    results = []
    for row_stride, kind in ((3, "3x3"), (4, "3x4/4x4")):
        need = 2 * row_stride
        if need >= len(rowunit):
            continue
        m = rowunit[:-need] & rowunit[row_stride:-row_stride] & rowunit[need:]
        # all three row pairs must be orthogonal - one small dot happens by chance on
        # unit-normal arrays; three at once is a rotation
        prod1 = g[:-row_stride] * g[row_stride:]
        prod2 = g[:-need] * g[need:]
        d01 = np.abs(_rolling_sum(prod1, 3))
        d12 = d01[row_stride:]
        d02 = np.abs(_rolling_sum(prod2, 3))
        k = min(len(m), len(d01), len(d12), len(d02))
        cand = np.flatnonzero(
            m[:k] & (d01[:k] < 0.05) & (d12[:k] < 0.05) & (d02[:k] < 0.05)
        )
        if len(cand) == 0:
            continue
        # suppress overlapping hits inside one matrix
        keep = [int(cand[0])]
        for c in cand[1:]:
            if c - keep[-1] >= need + row_stride:
                keep.append(int(c))
        if len(keep) < 4:
            continue
        d = np.diff(np.array(keep))
        stride_b = 0
        if len(d):
            vals, cnts = np.unique(d, return_counts=True)
            k = int(np.argmax(cnts))
            if cnts[k] >= max(3, len(d) // 2):
                stride_b = int(vals[k]) * 4
        results.append((len(keep), kind, keep[0] * 4, stride_b))
    if not results:
        return ProbeResult("matrix-runs", False, "no orthonormal matrix runs")
    results.sort(key=lambda r: -r[0])
    count, kind, at, stride_b = results[0]
    extra = f" at byte stride {stride_b}" if stride_b else ""
    return ProbeResult(
        "matrix-runs",
        True,
        f"{count} orthonormal {kind} matrices from 0x{at:x}{extra}",
        {"hits": [{"count": c, "kind": k, "at": a, "stride": s} for c, k, a, s in results]},
    )


# ==========================================================================================
# 4. skeleton probes
# ==========================================================================================


def _forest_walk(seq: np.ndarray, root: int) -> int:
    """Longest prefix of `seq` that is a valid parent table: seq[k] == root or < k."""
    k = 0
    while k < len(seq):
        p = int(seq[k])
        if p != root and not 0 <= p < k:
            break
        k += 1
    return k


def probe_parent_table(data: bytes) -> ProbeResult:
    """Parent-index table candidates: i32/i16 sequences forming a valid forest (every
    parent index precedes its child; roots are -1).  Candidates start at a root sentinel;
    strides cover packed arrays and per-record fields (the Skye .skg keeps its i32 parent
    at +0 of a 64-byte record)."""
    n = len(data)
    best = None
    for dt, root, elem in ((">i4", -1, 4), (">i2", -1, 2)):
        arr = np.frombuffer(data, dt, (n // elem)).astype(np.int64)
        sites = np.flatnonzero(arr == root)[: MAX_PARENT_STARTS]
        for stride_e in (1, 2, 4, 8, 16, 32):  # in elements
            byte_stride = stride_e * elem
            if byte_stride > 128:
                continue
            for s in sites:
                seq = arr[s :: stride_e][:512]
                run = _forest_walk(seq, root)
                if run < 10:
                    continue
                got = seq[:run]
                distinct = len(np.unique(got))
                roots = int(np.sum(got == root))
                if distinct < max(5, run // 3) or roots > max(2, run // 8):
                    continue
                # rank by nonzero information (zeros are always-valid parents, so an
                # aliased finer stride pads its run with them), then by the wider stride
                nonzero = int(np.sum(got != 0))
                key = (nonzero * elem, byte_stride, run)
                cand = (key, run, int(s) * elem, byte_stride, dt, roots, distinct)
                if best is None or cand[0] > best[0]:
                    best = cand
    if best is None:
        return ProbeResult("parent-table", False, "no i32/i16 sequence forms a plausible forest")
    _, run, at, stride, dt, roots, distinct = best
    return ProbeResult(
        "parent-table",
        True,
        f"{run} {dt} parent indices at 0x{at:x} stride {stride}: valid forest, "
        f"{roots} root(s), {distinct} distinct values",
        {"at": at, "entries": run, "stride": stride, "dtype": dt, "roots": roots},
    )


def probe_bone_names(data: bytes, names: ProbeResult | None = None) -> ProbeResult:
    """Bone-name scent over the file's strings: ROOT / L_UP_LEG / rhumerus / Bip01-style
    vocabulary.  Confirmation-grade only (gcrip.oracles: 'a mis-read table does not
    produce English') - it points at where a skeleton is named, not how it is stored."""
    matches = []
    for m in _STRING_RE.finditer(data):
        s = m.group()[:-1].decode("ascii", "replace")
        if _BONE_RE.search(s):
            matches.append((m.start(), s))
            if len(matches) >= 512:
                break
    if len(matches) < 4:
        return ProbeResult("bone-names", False, f"only {len(matches)} bone-like strings")
    sample = ", ".join(repr(s) for _, s in matches[:6])
    return ProbeResult(
        "bone-names",
        True,
        f"{len(matches)} bone-like strings from 0x{matches[0][0]:x}: {sample}",
        {"count": len(matches), "first": matches[:16]},
    )


# ==========================================================================================
# 5. codec probes
# ==========================================================================================


def probe_zlib(data: bytes) -> ProbeResult:
    """zlib/deflate sniffs at every plausible 0x78-header site (checksum-validated CMF/FLG
    pair), each given a bounded inflate."""
    sites = []
    at = 0
    tried = 0
    while tried < MAX_ZLIB_SITES:
        at = data.find(b"\x78", at)
        if at < 0 or at + 2 > len(data):
            break
        flg = data[at + 1]
        if ((0x78 << 8) | flg) % 31 == 0:
            tried += 1
            try:
                d = zlib.decompressobj()
                out = d.decompress(data[at : at + (1 << 18)], 1 << 22)
                if len(out) >= 256:
                    sites.append((at, len(out), d.eof))
            except zlib.error:
                pass
        at += 1
    if not sites:
        return ProbeResult("zlib-streams", False, "no zlib stream inflates")
    total = sum(s[1] for s in sites)
    complete = sum(1 for s in sites if s[2])
    return ProbeResult(
        "zlib-streams",
        True,
        f"{len(sites)} zlib streams inflate ({complete} to a clean end), first at "
        f"0x{sites[0][0]:x}, {total:,}+ bytes out",
        {"streams": [{"at": a, "out": o, "complete": c} for a, o, c in sites[:32]]},
    )


def probe_entropy(data: bytes) -> ProbeResult:
    """Per-4KB-page entropy profile - the map that found Gun's regions - plus repeated-fill
    detection (32 bytes of ``AB AB`` is the MSVC heap fill, and 918 'members' were that)."""
    n = len(data)
    npages = max(1, n // PAGE)
    ent = np.zeros(npages)
    fill = np.zeros(npages)
    fillv = np.zeros(npages, np.int64)
    for i in range(npages):
        page = np.frombuffer(data, np.uint8, min(PAGE, n - i * PAGE), i * PAGE)
        if len(page) == 0:
            continue
        counts = np.bincount(page, minlength=256).astype(np.float64)
        p = counts[counts > 0] / len(page)
        ent[i] = float(-np.sum(p * np.log2(p)))
        k = int(np.argmax(counts))
        fill[i] = counts[k] / len(page)
        fillv[i] = k
    high = ent > 7.3
    low = ent < 2.0
    at, run = _longest_run(high)
    fills = {}
    for i in np.flatnonzero(fill > 0.9):
        fills[int(fillv[i])] = fills.get(int(fillv[i]), 0) + 1
    fired = run * PAGE >= 16384
    fill_note = (
        "; fill pages: " + ", ".join(f"0x{v:02x} x{c}" for v, c in sorted(fills.items()))
        if fills
        else ""
    )
    return ProbeResult(
        "entropy-map",
        fired,
        f"mean {float(np.mean(ent)):.2f} bits/byte over {npages} pages; "
        f"{_pct(float(np.mean(high)))} high (>7.3), {_pct(float(np.mean(low)))} low (<2); "
        f"longest high region {run * PAGE // 1024} KB at 0x{at * PAGE:x}{fill_note}",
        {
            "pages": npages,
            "mean": float(np.mean(ent)),
            "high_frac": float(np.mean(high)),
            "low_frac": float(np.mean(low)),
            "longest_high": {"at": at * PAGE, "bytes": run * PAGE},
            "fills": fills,
            "profile": [round(float(e), 2) for e in ent[:512]],
        },
    )


# ==========================================================================================
# 6. oracle utilities (exported for reuse - the render gate is mandatory)
# ==========================================================================================


def edge_coherence(positions: np.ndarray, tris: np.ndarray) -> dict:
    """Median edge length over robust extent, with the anti-gaming guards the Skye and VC
    notes demand.  The bare ratio was gamed repeatedly: by collapse (everything to a
    point shrinks edges AND extent), by degenerate faces, and by junk outliers inflating
    the extent.  Guards: degenerate triangles are dropped and counted; the extent is the
    10-90 percentile box (outliers cannot inflate it); a collapse (most edges near zero,
    or almost no distinct vertices) sets ``gamed`` and the score to inf.  Even ungamed,
    a good score is a *ranking* signal - only a render is acceptance."""
    tris = np.asarray(tris).reshape(-1, 3)
    positions = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    if len(tris) == 0 or len(positions) == 0:
        return {"score": float("inf"), "gamed": True, "note": "empty"}
    degen = (tris[:, 0] == tris[:, 1]) | (tris[:, 1] == tris[:, 2]) | (tris[:, 0] == tris[:, 2])
    t = tris[~degen]
    if len(t) == 0:
        return {"score": float("inf"), "gamed": True, "note": "all triangles degenerate"}
    used = positions[np.unique(t)]
    distinct = len(np.unique(np.round(used, 9), axis=0))
    lo, hi = np.percentile(used, 10, axis=0), np.percentile(used, 90, axis=0)
    extent = float(np.linalg.norm(hi - lo))
    a, b, c = positions[t[:, 0]], positions[t[:, 1]], positions[t[:, 2]]
    edges = np.linalg.norm(np.concatenate([a - b, b - c, c - a]), axis=1)
    zero_frac = float(np.mean(edges < 1e-9))
    med = float(np.median(edges))
    gamed = extent <= 0 or distinct < max(4, len(used) // 20) or zero_frac > 0.5
    score = float("inf") if gamed else med / extent
    return {
        "score": score,
        "median_edge": med,
        "extent": extent,
        "degenerate_frac": float(np.mean(degen)),
        "zero_edge_frac": zero_frac,
        "distinct_verts": distinct,
        "gamed": gamed,
        "note": "collapse/degenerate - not evidence" if gamed else "rank with it, render to accept",
    }


def connected_components(tris: np.ndarray) -> list[int]:
    """Component sizes (in vertices, largest first) of the triangle graph - one big
    component is what a body looks like; ten thousand two-triangle islands is what a
    mis-read index buffer looks like."""
    t = np.asarray(tris).reshape(-1, 3)
    if len(t) == 0:
        return []
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for row in t:
        a = find(int(row[0]))
        for v in row[1:]:
            b = find(int(v))
            if a != b:
                parent[b] = a
    sizes: dict[int, int] = {}
    for v in parent:
        r = find(v)
        sizes[r] = sizes.get(r, 0) + 1
    return sorted(sizes.values(), reverse=True)


def bbox_containment(positions: np.ndarray, lo, hi, slack: float = 0.0) -> float:
    """Fraction of positions inside [lo, hi] (+- slack).  Meaningful only when the box
    comes from somewhere ELSE (a header the layout did not use to build the positions) -
    dequantizing against the same box makes it vacuous (gcrip.oracles, DISCREDITED)."""
    v = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    lo = np.asarray(lo, dtype=np.float64) - slack
    hi = np.asarray(hi, dtype=np.float64) + slack
    if len(v) == 0:
        return 0.0
    return float(np.mean(np.all((v >= lo) & (v <= hi), axis=1)))


def triangle_identity(declared: int, produced: int) -> tuple[bool, str]:
    """The declared-count identity (GDF: 1,274 of 1,274; LOTR: 2,990 exactly).  Exact or
    nothing - 'close' is what a wrong stride produces."""
    ok = declared == produced
    return ok, (
        f"declared {declared} == produced {produced}"
        if ok
        else f"declared {declared} != produced {produced} (off by {produced - declared})"
    )


def render_wireframe(positions: np.ndarray, tris: np.ndarray, path) -> None:
    """Three orthographic wireframe views (XY / XZ / YZ) to ``path`` - the render gate.
    The metric oracles were gamed on both Skye and VC; the wireframe was the only honest
    judge, so every accepted geometry hypothesis ends here."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    v = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    t = np.asarray(tris).reshape(-1, 3)
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    if len(e) > 80_000:
        e = e[np.random.default_rng(0).choice(len(e), 80_000, replace=False)]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, (i, j, label) in zip(axes, ((0, 1, "XY"), (0, 2, "XZ"), (1, 2, "YZ")), strict=True):
        segs = np.stack([v[e[:, 0]][:, (i, j)], v[e[:, 1]][:, (i, j)]], axis=1)
        ax.add_collection(LineCollection(segs, linewidths=0.3, colors="black"))
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_title(label)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ==========================================================================================
# 7. archetype matcher
# ==========================================================================================

ARCHETYPES = (
    "indexed-GX-arrays",
    "naked-GX",
    "bone-local-skinned",
    "dual-copy-baked",
    "fixed-point-flat",
    "LZ-packed",
)


def _match_archetypes(res: dict[str, ProbeResult]) -> list[tuple[str, str]]:
    def on(name: str) -> bool:
        p = res.get(name)
        return bool(p and p.fired)

    def ev(name: str) -> str:
        p = res.get(name)
        return p.evidence if p else ""

    out: list[tuple[str, str]] = []
    gx = res.get("gx-display-list")
    gx_on = bool(gx and gx.fired and gx.params.get("strong"))
    naked = bool(gx_on and gx.params.get("naked"))
    if on("container-tiling") or on("chunk-stream"):
        which = "container-tiling" if on("container-tiling") else "chunk-stream"
        out.append(
            (
                "container (expand first)",
                f"this member is itself an archive - {ev(which)}; crack the members, "
                "not the wrapper",
            )
        )
    if on("zlib-streams"):
        out.append(("LZ-packed", ev("zlib-streams")))
    elif res.get("entropy-map") and res["entropy-map"].params.get("high_frac", 0) > 0.8:
        others = gx_on or on("f32-positions") or on("name-table") or on("container-tiling")
        if not others:
            out.append(
                (
                    "LZ-packed",
                    "near-uniform high entropy with no structural probe firing - likely a "
                    "non-zlib codec (VC 10:14, EA rcmp, Yaz0 family); "
                    + ev("entropy-map"),
                )
            )
    if gx_on and naked:
        out.append(
            (
                "naked-GX",
                "display lists with no CP/XF setup - arrays are bound by the engine "
                "(TR Legend DRM, Gun props); find the header that names the arrays. "
                + ev("gx-display-list"),
            )
        )
    if gx_on and not naked and (on("f32-positions") or on("s16-fixed-point")):
        arrays = ev("f32-positions") if on("f32-positions") else ev("s16-fixed-point")
        out.append(
            (
                "indexed-GX-arrays",
                "GX lists with setup over separate attribute arrays (Blitz/Taz, Gun levels, "
                f"SKN): {ev('gx-display-list')} | arrays: {arrays}",
            )
        )
    skel = on("parent-table") or on("bone-names")
    if skel and on("matrix-runs"):
        skel_ev = ev("parent-table") if on("parent-table") else ev("bone-names")
        out.append(
            (
                "bone-local-skinned",
                "skeleton with stored transforms - vertices are probably joint-local and "
                f"need G = parent@local composition (Darkened Skye SKX): "
                f"{ev('matrix-runs')} | {skel_ev}",
            )
        )
    if on("bone-names") and not on("matrix-runs") and gx_on:
        out.append(
            (
                "dual-copy-baked",
                "bone NAMES but no stored transforms + GX lists - the Acclaim SKN shape: "
                "model-space baked bind pose, transforms live with the animation data. "
                + ev("bone-names"),
            )
        )
    if on("s16-fixed-point") and on("normal-runs") and not on("f32-positions"):
        out.append(
            (
                "fixed-point-flat",
                "s16 fixed-point arrays with unit-normal runs and no f32 positions "
                "(SKN /256, Skye /1024): try the standard divisors against a size identity. "
                f"{ev('normal-runs')}",
            )
        )
    return out


# ==========================================================================================
# the battery
# ==========================================================================================


def probe(data: bytes, budget: float = 55.0) -> Report:
    """Run every probe over the member bytes and return the structured :class:`Report`."""
    t0 = time.monotonic()
    deadline = t0 + budget
    results: list[ProbeResult] = []

    def run(fn, *args) -> ProbeResult:
        try:
            r = fn(*args)
        except Exception as exc:  # a probe must never kill the battery  # noqa: BLE001
            r = ProbeResult(fn.__name__.replace("probe_", "").replace("_", "-"), False,
                            f"probe error: {exc!r}")
        results.append(r)
        return r

    run(probe_chunk_stream, data)
    run(probe_tiling_table, data)
    run(probe_ascending_table, data)
    names = run(probe_name_tables, data)
    run(probe_gx_display_lists, data, min(deadline, t0 + GX_BUDGET))
    run(probe_f32_positions, data)
    run(probe_s16_fixed, data)
    run(probe_normal_runs, data)
    run(probe_uv_runs, data)
    run(probe_quaternion_runs, data)
    run(probe_matrix_runs, data)
    run(probe_parent_table, data)
    run(probe_bone_names, data, names)
    run(probe_zlib, data)
    run(probe_entropy, data)
    res = {r.name: r for r in results}
    return Report(
        size=len(data),
        probes=results,
        archetypes=_match_archetypes(res),
        elapsed=time.monotonic() - t0,
    )


def main(argv=None) -> int:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(
        prog="python -m gcrip.autocrack",
        description="run the standard format-cracking hypothesis battery over a file",
    )
    ap.add_argument("file", help="the unknown member bytes")
    ap.add_argument("--budget", type=float, default=55.0, help="seconds (default 55)")
    a = ap.parse_args(argv)
    data = Path(a.file).read_bytes()
    report = probe(data, budget=a.budget)
    print(f"{a.file}")
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
