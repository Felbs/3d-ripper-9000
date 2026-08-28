"""Engine-agnostic geometry finder: locate GX display lists in any blob and rebuild meshes.

Every GameCube game hands the GPU the same three things - vertex attribute arrays, GX
display lists (primitive opcode, u16 vertex count, one index tuple per vertex) and
tiled textures - and stores them on disc in that layout so they can be DMA'd straight
in.  So a file in an unknown container can still be read at the hardware level:

1. `find_display_lists` walks the bytes for primitive opcodes whose u16 counts chain
   consistently at one vertex stride (opcode, count, count*stride bytes, next opcode ...).
   Real display lists chain for many primitives at exactly one stride; noise does not.
2. `infer_fields` splits the stride into u8/u16 index fields by looking at byte columns.
3. `find_positions` looks for a big-endian float32 array (or s16 with a fixed-point
   shift) large enough for the biggest index, and `best_mesh` picks the index field +
   array whose triangles are compact (mean edge / bbox diagonal is small for real meshes
   and ~0.5 for spaghetti).

The result is raw geometry - no hierarchy, skinning, names or UV-texture links.  It is a
fallback for the ~470 discs whose model containers no plugin understands.

usage: python -m gcrip.gxscan <disc.iso> [--only substr] [--out dir] [--limit n]
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import numpy as np

PRIM_OPS = {0x80: "quads", 0x90: "tris", 0x98: "strip", 0xA0: "fan"}
MAX_COUNT = 0x1000
MIN_STRIDE, MAX_STRIDE = 2, 64


@dataclass
class DisplayList:
    offset: int
    end: int
    stride: int
    prims: list[tuple[int, int, int]]  # (opcode, count, data offset)

    @property
    def vertices(self) -> int:
        return sum(c for _, c, _ in self.prims)


@dataclass
class Mesh:
    dl: DisplayList
    field_offset: int
    field_size: int
    pos_offset: int
    pos_kind: str  # "f32" | "s16"
    positions: np.ndarray  # (N,3) f32
    indices: np.ndarray  # (M,) u32 triangles
    compactness: float
    uv_field: tuple[int, int] | None = None
    uvs: np.ndarray | None = None
    extras: dict = field(default_factory=dict)

    @property
    def triangles(self) -> int:
        return len(self.indices) // 3


# ---------------------------------------------------------------------------
# 1. display lists
# ---------------------------------------------------------------------------


class _Blob:
    """Per-blob caches: primitive-header mask and plausible-number runs."""

    def __init__(self, data: bytes):
        self.data = data
        n = len(data)
        b = np.frombuffer(data, np.uint8)
        op_ok = np.zeros(n, bool)
        if n >= 3:
            ops = (b[:-2] & 0xF8)
            is_op = (ops == 0x80) | (ops == 0x90) | (ops == 0x98) | (ops == 0xA0)
            count = (b[1:-1].astype(np.uint32) << 8) | b[2:]
            op_ok[:-2] = is_op & (count >= 3) & (count <= MAX_COUNT)
        self.hdr = op_ok
        self._runs: dict[str, list[tuple[int, int]]] = {}

    def op_at(self, p: int) -> tuple[int, int] | None:
        if p < 0 or p >= len(self.hdr) or not self.hdr[p]:
            return None
        d = self.data
        return d[p] & 0xF8, (d[p + 1] << 8) | d[p + 2]

    def runs(self, kind: str) -> list[tuple[int, int]]:
        """(byte offset, byte length) of maximal runs of plausible f32 / s16 words."""
        if kind in self._runs:
            return self._runs[kind]
        data, n = self.data, len(self.data)
        if kind == "f32":
            arr = np.frombuffer(data[: n - n % 4], ">u4")
            exp = (arr >> 23) & 0xFF
            ok = ((exp >= 0x66) & (exp <= 0x94)) | (arr == 0)
            step = 4
        else:
            arr = np.frombuffer(data[: n - n % 2], ">i2")
            ok = np.abs(arr.astype(np.int32)) < 0x7FF0
            step = 2
        bad = np.flatnonzero(~ok)
        edges = np.concatenate(([-1], bad, [len(ok)]))
        runs = [
            (int(a + 1) * step, int(b - a - 1) * step)
            for a, b in zip(edges[:-1], edges[1:], strict=True)
            if b - a - 1 >= 12
        ]
        self._runs[kind] = runs
        return runs


def _skip_pad(data: bytes, p: int, limit: int = 32) -> int:
    """GX lists are padded with 0x00 (NOP) to 32 bytes between/after primitives."""
    n = len(data)
    q = p
    while q < n and q - p < limit and data[q] == 0:
        q += 1
    return q


def _chain(blob: _Blob, start: int, stride: int) -> DisplayList | None:
    data, n = blob.data, len(blob.data)
    p = start
    prims = []
    while True:
        h = blob.op_at(p)
        if h is None:
            break
        op, count = h
        nxt = p + 3 + count * stride
        if nxt > n:
            break
        prims.append((op, count, p + 3))
        p = _skip_pad(data, nxt)
        if len(prims) > 4096:
            break
    if not prims:
        return None
    ends_clean = p >= n or blob.op_at(p) is not None or p > prims[-1][2] + prims[-1][1] * stride
    if not ends_clean and len(prims) < 2 and prims[0][1] < 12:
        return None
    return DisplayList(start, p, stride, prims)


def _stride_candidates(blob: _Blob, p: int, count: int) -> list[int]:
    """Strides for which this primitive is followed (after optional 0x00 padding) by
    another header or the end of data."""
    data, n = blob.data, len(blob.data)
    base = p + 3
    out = []
    for s in range(MIN_STRIDE, MAX_STRIDE + 1):
        e = base + count * s
        if e > n:
            break
        q = _skip_pad(data, e)
        if q >= n or blob.hdr[q]:
            out.append(s)
    return out


def find_display_lists(data: bytes, min_prims: int = 2, min_verts: int = 12,
                       blob: _Blob | None = None) -> list[DisplayList]:
    """Best chain per start (most primitives), non-overlapping."""
    return [c[0] for c in candidate_lists(data, min_prims, min_verts, blob)]


def candidate_lists(data: bytes, min_prims: int = 2, min_verts: int = 12,
                    blob: _Blob | None = None) -> list[list[DisplayList]]:
    """For every start offset that chains at some stride, the chains for each viable
    stride (longest first).  Which stride is right is decided by the geometry score in
    `scan_blob`, not here - a wrong stride can chain by accident but yields spaghetti."""
    blob = blob or _Blob(data)
    out: list[list[DisplayList]] = []
    starts = np.flatnonzero(blob.hdr)
    skip_to = 0
    for p in starts:
        p = int(p)
        if p < skip_to:
            continue
        h = blob.op_at(p)
        if h is None:
            continue
        cands = []
        for s in _stride_candidates(blob, p, h[1]):
            dl = _chain(blob, p, s)
            if dl is not None and (len(dl.prims) >= min_prims or dl.vertices >= min_verts):
                cands.append(dl)
        if not cands:
            continue
        cands.sort(key=lambda d: (len(d.prims), d.end), reverse=True)
        out.append(cands[:6])
        skip_to = max(d.end for d in cands)
    return out


# ---------------------------------------------------------------------------
# 2. index fields
# ---------------------------------------------------------------------------


def _vertex_bytes(data: bytes, dl: DisplayList) -> np.ndarray:
    """(V, stride) u8 - every vertex tuple in the list."""
    rows = []
    for _, count, off in dl.prims:
        rows.append(np.frombuffer(data, np.uint8, count * dl.stride, off).reshape(count, dl.stride))
    return np.concatenate(rows)


def infer_fields(vb: np.ndarray) -> list[tuple[int, int]]:
    """(byte offset, size) for each index field.  A byte column that never exceeds 0x3F
    while the next column varies is the high byte of a u16."""
    s = vb.shape[1]
    fields = []
    c = 0
    while c < s:
        if c + 1 < s and vb[:, c].max() <= 0x3F and vb[:, c + 1].max() > 0 and (
            vb[:, c].max() > 0 or len(np.unique(vb[:, c + 1])) > 2
        ):
            fields.append((c, 2))
            c += 2
        else:
            fields.append((c, 1))
            c += 1
    return fields


def field_values(vb: np.ndarray, off: int, size: int) -> np.ndarray:
    if size == 2:
        return (vb[:, off].astype(np.uint32) << 8) | vb[:, off + 1]
    return vb[:, off].astype(np.uint32)


# ---------------------------------------------------------------------------
# 3. position arrays
# ---------------------------------------------------------------------------


def find_positions(blob: _Blob, needed: int, near: int, kind: str = "f32") -> list[int]:
    """Offsets of arrays with >= `needed` plausible vertex triples, nearest to `near`
    first (aligned to the word size)."""
    span = needed * (12 if kind == "f32" else 6)
    offs = []
    for start, length in blob.runs(kind):
        if length < span:
            continue
        end = start + length - span
        for o in {start, min(max(start, near - span), end), min(max(start, near), end)}:
            offs.append(o)
    offs = sorted(set(offs), key=lambda o: abs(o - near))
    return offs[:24]


# ---------------------------------------------------------------------------
# 4. mesh assembly and scoring
# ---------------------------------------------------------------------------


def _triangulate(dl: DisplayList, idx: np.ndarray) -> np.ndarray:
    tris = []
    k = 0
    for op, count, _ in dl.prims:
        v = idx[k : k + count]
        k += count
        if op == 0x90:
            m = count - count % 3
            tris.append(v[:m].reshape(-1, 3))
        elif op == 0x98:
            for i in range(count - 2):
                a, b, c = v[i], v[i + 1], v[i + 2]
                tris.append(np.array([[a, b, c] if i % 2 == 0 else [b, a, c]], np.uint32))
        elif op == 0xA0:
            for i in range(1, count - 1):
                tris.append(np.array([[v[0], v[i], v[i + 1]]], np.uint32))
        elif op == 0x80:
            m = count - count % 4
            q = v[:m].reshape(-1, 4)
            tris.append(np.stack([q[:, 0], q[:, 1], q[:, 2]], 1))
            tris.append(np.stack([q[:, 0], q[:, 2], q[:, 3]], 1))
    if not tris:
        return np.zeros(0, np.uint32)
    t = np.concatenate(tris).astype(np.uint32)
    return t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])].reshape(-1)


def _compactness(pos: np.ndarray, tri: np.ndarray) -> float:
    """Mean edge length / bbox diagonal, scaled by sqrt(triangles): a surface mesh
    with N triangles has edges ~ diag/sqrt(N), so real meshes score ~1-2 at any size,
    while wrong strides / index fields / arrays give spaghetti (edges ~ diag/2) and
    score ~ 0.5*sqrt(N).  The diagonal is taken over the 10th-90th percentile box so a
    few outlier vertices (an array read from the wrong offset) cannot inflate it."""
    if len(tri) < 3:
        return 99.0
    t = tri.reshape(-1, 3)
    used = pos[np.unique(t)]
    lo, hi = np.percentile(used, 10, axis=0), np.percentile(used, 90, axis=0)
    diag = float(np.linalg.norm(hi - lo))
    if diag <= 0:
        return 99.0
    a, b, c = pos[t[:, 0]], pos[t[:, 1]], pos[t[:, 2]]
    e = np.linalg.norm(np.concatenate([a - b, b - c, c - a]), axis=1) / diag
    if float(np.mean(e)) > 0.35 or float(np.mean(e > 0.5)) > 0.05:
        return 99.0  # spaghetti: long edges everywhere
    return float(np.mean(e)) * float(np.sqrt(len(t)))


def _inline_mesh(blob: _Blob, dl: DisplayList, vb: np.ndarray, max_score: float) -> Mesh | None:
    """Direct display lists (no index arrays): the vertex tuple holds the position itself
    as 3 x f32 (or 3 x s16) at some offset.  The triangle list is simply 0..V-1."""
    best: Mesh | None = None
    v = vb.shape[0]
    idx = np.arange(v, dtype=np.uint32)
    tri = _triangulate(dl, idx)
    if len(tri) < 3:
        return None
    for kind, size, dt in (("f32", 12, ">f4"), ("s16", 6, ">i2")):
        for k in range(0, dl.stride - size + 1, 2 if kind == "s16" else 4):
            raw = np.ascontiguousarray(vb[:, k : k + size]).tobytes()
            pos = np.frombuffer(raw, dt).reshape(v, 3).astype(np.float32)
            if kind == "f32":
                if not np.all(np.isfinite(pos)) or np.abs(pos).max() > 1e6:
                    continue
                nz = np.abs(pos[pos != 0])
                if nz.size and nz.min() < 1e-6:
                    continue
            sc = _compactness(pos, tri) * (1.0 if kind == "f32" else 1.25)
            if sc < max_score and (best is None or sc < best.compactness):
                best = Mesh(dl, k, size, -1, "inline-" + kind, pos, tri, sc)
    return best


def best_mesh(blob: _Blob, dl: DisplayList, max_score: float = 2.5) -> Mesh | None:
    data = blob.data
    vb = _vertex_bytes(data, dl)
    fields = infer_fields(vb)
    best: Mesh | None = _inline_mesh(blob, dl, vb, max_score) if dl.stride >= 6 else None
    for off, size in fields:
        idx = field_values(vb, off, size)
        needed = int(idx.max()) + 1
        if needed < 3 or (size == 1 and needed > 256):
            continue
        tri = _triangulate(dl, idx)
        if len(tri) < 3:
            continue
        for kind in ("f32", "s16"):
            for po in find_positions(blob, needed, dl.offset, kind):
                dt = ">f4" if kind == "f32" else ">i2"
                pos = np.frombuffer(data, dt, needed * 3, po).reshape(-1, 3).astype(np.float32)
                if not np.all(np.isfinite(pos)):
                    continue
                sc = _compactness(pos, tri) * (1.0 if kind == "f32" else 1.25)
                if sc < max_score and (best is None or sc < best.compactness):
                    best = Mesh(dl, off, size, po, kind, pos, tri, sc)
    return best


def _accept(m: Mesh) -> bool:
    """Tiny meshes and s16 arrays are where noise can pass the score: any bytes read
    as plausible s16, so those kinds need a stricter score."""
    if m.triangles < 20:
        return False
    limit = 1.6 if "s16" in m.pos_kind else 2.2
    return m.compactness < limit


def scan_blob(data: bytes, max_lists: int = 2000, budget: float | None = None) -> list[Mesh]:
    """Every mesh the blob yields; `budget` (seconds) stops the search early on huge
    files so one archive cannot stall a disc rip."""
    deadline = time.monotonic() + budget if budget else None
    blob = _Blob(data)
    meshes = []
    for cands in candidate_lists(data, blob=blob)[:max_lists]:
        if deadline and time.monotonic() > deadline:
            break
        best: Mesh | None = None
        for dl in cands:
            m = best_mesh(blob, dl)
            if m is None or not _accept(m):
                continue
            if best is None or (m.compactness, -m.triangles) < (best.compactness, -best.triangles):
                best = m
        if best is not None:
            meshes.append(best)
    if not deadline or time.monotonic() < deadline:
        meshes += find_neutral_meshes(blob)
    return meshes


def to_scene(name: str, meshes: list[Mesh]):
    """One Scene: every mesh its own primitive + material, so a viewer can tell them
    apart and the report can show what was found.  Topology is what the scanner inferred,
    so the extras say so."""
    from ripcore.scene import MaterialDef, Primitive, Scene

    scene = Scene(name=name)
    for i, m in enumerate(sorted(meshes, key=lambda x: -x.triangles)):
        scene.materials.append(
            MaterialDef(name=f"gx{i:03d}_{m.pos_kind}", texture=None, double_sided=True)
        )
        scene.primitives.append(Primitive(material=i, positions=m.positions, indices=m.indices))
    scene.extras = {
        "gxscan": True,
        "meshes": len(meshes),
        "kinds": sorted({m.pos_kind for m in meshes}),
        "note": "geometry found by structure (no rig, names, UVs or textures)",
    }
    return scene


# ---------------------------------------------------------------------------
# 5. platform-neutral meshes: vertex array + index array, no GX display list
# ---------------------------------------------------------------------------


def _u16_runs(blob: _Blob, max_value: int = 0xFFF0, min_words: int = 60) -> list[tuple[int, int]]:
    """(byte offset, word count) of maximal runs of big-endian u16 below max_value."""
    if "u16" in blob._runs:
        return blob._runs["u16"]
    data, n = blob.data, len(blob.data)
    arr = np.frombuffer(data[: n - n % 2], ">u2")
    ok = arr < max_value
    bad = np.flatnonzero(~ok)
    edges = np.concatenate(([-1], bad, [len(ok)]))
    runs = [(int(a + 1) * 2, int(b - a - 1)) for a, b in zip(edges[:-1], edges[1:], strict=True)
            if b - a - 1 >= min_words]
    blob._runs["u16"] = runs
    return runs


def _index_candidates(blob: _Blob, run_off: int, words: int, nverts: int) -> list[np.ndarray]:
    """Index streams inside a u16 run that address exactly `nverts` vertices: the run is
    cut where values exceed nverts-1; a stream must use most of the range and be sized
    like an index buffer for that many vertices (~2 triangles per vertex for a list,
    ~1 index per vertex for a strip) so audio and tables do not qualify."""
    arr = np.frombuffer(blob.data, ">u2", words, run_off).astype(np.int64)
    over = np.flatnonzero(arr >= nverts)
    edges = np.concatenate(([-1], over, [len(arr)]))
    out = []
    lo, hi = int(nverts * 0.8), int(nverts * 12)
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        seg = arr[a + 1 : b]
        if not lo <= len(seg) <= hi or len(seg) < 60:
            continue
        if seg.max() < nverts * 0.9:
            continue
        uniq = len(np.unique(seg))
        if uniq < nverts * 0.6:
            continue
        out.append(seg)
    return out


def _neutral_triangulate(seg: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """A u16 stream as a triangle list and as one strip (both are common)."""
    out = []
    m = len(seg) - len(seg) % 3
    if m >= 3:
        out.append(("list", seg[:m].astype(np.uint32)))
    if len(seg) >= 3:
        i = np.arange(len(seg) - 2)
        a, b, c = seg[i], seg[i + 1], seg[i + 2]
        odd = i % 2 == 1
        tri = np.stack([np.where(odd, b, a), np.where(odd, a, b), c], 1).astype(np.uint32)
        out.append(("strip", tri.reshape(-1)))
    return out


def find_neutral_meshes(blob: _Blob, max_score: float = 1.4) -> list[Mesh]:
    """Meshes stored as a float32 vertex array plus a u16 index array, with no display
    list at all - what multi-platform engines write, then convert to GX at load time.
    Every float run is tried as positions at strides 3..12 floats; u16 runs sized like
    an index buffer for that vertex count are tried as its indices, nearest first; the
    geometry score decides (stricter than for display lists: no opcode evidence here)."""
    data = blob.data
    meshes: list[Mesh] = []
    u16 = _u16_runs(blob)
    if not u16:
        return meshes
    for off, length in blob.runs("f32"):
        if length < 48 * 12:
            continue
        floats = np.frombuffer(data, ">f4", length // 4, off)
        found: Mesh | None = None
        for fstride in (3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
            nverts = len(floats) // fstride
            if nverts < 48:
                continue
            pos = np.ascontiguousarray(floats[: nverts * fstride].reshape(nverts, fstride)[:, :3])
            if not np.all(np.isfinite(pos)):
                continue
            near = sorted((r for r in u16 if r[1] >= nverts * 0.8), key=lambda r: abs(r[0] - off))[:12]
            for uoff, words in near:
                for seg in _index_candidates(blob, uoff, words, nverts):
                    for layout, tri in _neutral_triangulate(seg):
                        if len(tri) < 60:
                            continue
                        sc = _compactness(pos, tri)
                        if sc < max_score and (found is None or sc < found.compactness):
                            dl = DisplayList(uoff, uoff + words * 2, 2, [(0x90, len(seg), uoff)])
                            found = Mesh(dl, 0, 2, off, f"neutral-f32x{fstride}-{layout}",
                                         pos, tri, sc)
        if found is not None and _accept(found):
            meshes.append(found)
    return meshes


# ---------------------------------------------------------------------------
# disc driver (prototype)
# ---------------------------------------------------------------------------


def scan_disc(iso, only: str | None = None, limit: int | None = None, out=None, quiet=False,
              max_mb: float = 48.0):
    from pathlib import Path

    from gcrip.disc.image import DiscImage
    from gcrip.manifest import build_manifest
    from gcrip.rip import _Source

    iso = Path(iso)
    report = []
    with DiscImage(iso) as image:
        manifest = build_manifest(image, recurse=True, hash_files=False)
        src = _Source(image, manifest)
        files = [
            f
            for f in manifest.files
            if f.kind in ("unknown", "archive") and 1024 <= f.size <= int(max_mb * (1 << 20))
            and not f.path.startswith("sys/") and (not only or only in f.path)
        ]
        if limit:
            files = files[:limit]
        for i, f in enumerate(files):
            if not quiet:
                sys.stderr.write(f"\r  scan {i + 1}/{len(files)}: {f.path[-60:]:<60}")
            try:
                data = src.get(f.path)
            except Exception:  # noqa: BLE001
                continue
            meshes = scan_blob(data)
            if meshes:
                report.append((f.path, f.size, meshes))
                if out is not None:
                    _export(out, f.path, meshes)
        if not quiet:
            sys.stderr.write("\n")
    return manifest.game, report


def _export(out, path: str, meshes: list[Mesh]) -> None:
    from pathlib import Path

    from ripcore import gltf as core_gltf
    from ripcore.scene import MaterialDef, Primitive, Scene

    scene = Scene(name=Path(path).name)
    scene.materials.append(MaterialDef(name="gxscan", texture=None, double_sided=True))
    for m in meshes:
        scene.primitives.append(Primitive(material=0, positions=m.positions, indices=m.indices))
    base = Path(out) / (path.replace("/", "__").replace("\\", "__"))
    base.parent.mkdir(parents=True, exist_ok=True)
    st = core_gltf.export(scene, base)
    core_gltf.thumbnail(st, base)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("iso")
    ap.add_argument("--only")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out")
    ap.add_argument("--max-mb", type=float, default=48.0)
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    game, report = scan_disc(a.iso, a.only, a.limit, a.out, a.quiet, a.max_mb)
    tri = sum(m.triangles for _, _, ms in report for m in ms)
    print(f"{game['id']} {game['title']}: {len(report)} files with geometry, "
          f"{sum(len(ms) for _, _, ms in report)} meshes, {tri:,} triangles")
    for path, _size, ms in sorted(report, key=lambda r: -sum(m.triangles for m in r[2]))[:25]:
        t = sum(m.triangles for m in ms)
        kinds = {m.pos_kind for m in ms}
        sc = min(m.compactness for m in ms)
        print(f"  {t:8,} tris {len(ms):4} meshes {'/'.join(sorted(kinds)):10} "
              f"best {sc:.3f}  {path[-70:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
