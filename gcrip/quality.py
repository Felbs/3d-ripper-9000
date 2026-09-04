"""Automated quality audit for the ripped-model library.

Scores every exported glTF against the geometric oracles that told good decodes from
garbage during format cracking (see gcrip/oracles.py for the registry of what actually
carries signal):

* **spaghetti** - median triangle-edge length as a share of the bounding-box diagonal.
  Real meshes sit at 0.5-8%; a decoder reading vertices at the wrong stride produces
  edges that span the whole model.
* **collapse** - near-zero extent, a single position repeated across most of the mesh,
  or a large share of zero-length edges.
* **fragments** - connected components over the index buffer; a partial export ("just
  a head") shows up as a model far smaller than its siblings, a shattered decode as
  hundreds of crumbs with no dominant component.
* **NaN/inf positions** - never legitimate.
* **untextured** - the model carries no textures while the rest of the game does, or
  the glTF references image files that are missing on disk.

Verdict per model: ``ok`` | ``untextured`` | ``suspect`` (a soft signal) | ``garbage``
(a hard signal), with the reasons attached.

Reads are kept HDD-friendly: one sequential pass per game folder, no re-reads, games
processed serially, and models over ``MAX_TRIANGLES`` scored from metadata only.
"""

from __future__ import annotations

import fnmatch
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path("D:/3d dump/GameCube")

# -- thresholds ------------------------------------------------------------------------
MAX_TRIANGLES = 500_000  # bigger models are scored from metadata only (HDD is shared)
SPAGHETTI_MIN_TRIS = 128  # low-poly props legitimately have long edges vs their extent
SPAGHETTI_SUSPECT = 0.15  # median edge / bbox diagonal
SPAGHETTI_GARBAGE = 0.25
# co-gate: even the SHORT end of the edge distribution must be long.  Random-index
# spaghetti has essentially no short edges (p10 ~ random-pair distance, 15%+ of the
# diagonal); legit coarse meshes (Tiger Woods terrain slabs, med 0.27) keep a local
# fringe (p10 ~ 2%).  Calibrated on G6WE69 ter_* vs GDQE7L STONEL11 (p10 0.19).
SPAGHETTI_P10_GARBAGE = 0.04
SPAGHETTI_P10_SUSPECT = 0.03
DUP_TOP_SHARE = 0.50  # most common single position covers this share -> collapsed
DEGENERATE_EDGE_SHARE = 0.20  # zero-length edges: soft signal here, hard at 2x
SHATTER_MIN_VERTS = 100
SHATTER_COMPONENTS = 16
SHATTER_LARGEST_SHARE = 0.15
SHATTER_TRIS_PER_COMP = 4.0  # legit multi-part stages average far more triangles/part
TINY_SHARE = 0.01  # vs the game's median model vertex count
TINY_MIN_MEDIAN = 300  # only meaningful when the game's models are non-trivial
GAME_TEXTURED_MIN = 0.5  # game share of textured models before "untextured" is a verdict

# Known-benign exceptions, matched with fnmatch against "<GID>/<out_rel>".  Tiger Woods
# `ter` slabs decode byte-identical to raw known-plaintext copies (see gcrip/knownplain.py),
# so the exports are faithful to the source even though their edge statistics look tangled
# (coarse LOD-stitch sheets: median edge ~0.27 of the diagonal, isotropic normals).  Only
# the spaghetti-family signals are suppressed for matches; NaN/collapse still apply.
SPAGHETTI_EXEMPT = (
    "G6WE69*/*.hog/*.gltf",  # Tiger Woods 06
    "G5TE69*/*.hog/*.gltf",  # Tiger Woods 2005
    "GW4E69*/*.hog/*.gltf",  # Tiger Woods 2004 (both discs)
    "GTIE69*/*.hog/*.gltf",  # Tiger Woods 2003
)

_HARD = "garbage"
_SOFT = "suspect"

_IDX_DTYPES = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}


# -- minimal glTF reader ---------------------------------------------------------------


def _read_accessor(gltf: dict, buffers: dict[int, bytes], index: int) -> np.ndarray | None:
    """Return the raw data of accessor *index* as a numpy array, or None if unreadable."""
    try:
        acc = gltf["accessors"][index]
        bv = gltf["bufferViews"][acc["bufferView"]]
    except (KeyError, IndexError, TypeError):
        return None
    buf = buffers.get(bv.get("buffer", 0))
    if buf is None:
        return None
    comp = acc.get("componentType")
    count = acc.get("count", 0)
    if comp == 5126:
        dtype, width = np.dtype("<f4"), 4
    elif comp in _IDX_DTYPES:
        dtype, width = np.dtype(_IDX_DTYPES[comp]).newbyteorder("<"), np.dtype(
            _IDX_DTYPES[comp]
        ).itemsize
    else:
        return None
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}.get(acc.get("type"), 0)
    if not ncomp or count <= 0:
        return None
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or ncomp * width
    need = start + (count - 1) * stride + ncomp * width
    if need > len(buf):
        return None
    if stride == ncomp * width:
        out = np.frombuffer(buf, dtype=dtype, count=count * ncomp, offset=start)
    else:  # interleaved
        rows = np.frombuffer(buf, dtype=np.uint8, count=count * stride, offset=start)
        rows = rows.reshape(count, stride)[:, : ncomp * width].copy()
        out = rows.view(dtype).reshape(-1)
    return out.reshape(count, ncomp) if ncomp > 1 else out


def load_geometry(gltf_path: Path) -> tuple[dict, np.ndarray, np.ndarray]:
    """Parse a glTF file: return (gltf json, positions (N,3) f32, triangles (M,3) i64).

    All primitives of all meshes are concatenated (indices rebased).  Raises on a
    missing/corrupt file so the caller can score it "unreadable".
    """
    gltf_path = Path(gltf_path)
    with open(gltf_path, encoding="utf-8") as fh:
        gltf = json.load(fh)
    buffers: dict[int, bytes] = {}
    for i, b in enumerate(gltf.get("buffers", [])):
        uri = b.get("uri")
        if uri and not uri.startswith("data:"):
            p = gltf_path.parent / uri
            if p.is_file():
                buffers[i] = p.read_bytes()
    pos_parts: list[np.ndarray] = []
    tri_parts: list[np.ndarray] = []
    base = 0
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if prim.get("mode", 4) != 4:
                continue
            pa = prim.get("attributes", {}).get("POSITION")
            if pa is None:
                continue
            pos = _read_accessor(gltf, buffers, pa)
            if pos is None or pos.ndim != 2 or pos.shape[1] != 3:
                continue
            n = len(pos)
            if "indices" in prim:
                idx = _read_accessor(gltf, buffers, prim["indices"])
                if idx is None:
                    continue
                idx = idx.reshape(-1).astype(np.int64)
                idx = idx[: (len(idx) // 3) * 3]
                idx = idx[np.all(idx.reshape(-1, 3) < n, axis=1).repeat(3)]
            else:
                idx = np.arange((n // 3) * 3, dtype=np.int64)
            pos_parts.append(pos.astype(np.float32, copy=False))
            tri_parts.append(idx.reshape(-1, 3) + base)
            base += n
    positions = np.concatenate(pos_parts) if pos_parts else np.empty((0, 3), np.float32)
    triangles = np.concatenate(tri_parts) if tri_parts else np.empty((0, 3), np.int64)
    return gltf, positions, triangles


# -- metrics ---------------------------------------------------------------------------


def _components(n_verts: int, edges: np.ndarray) -> tuple[int, float]:
    """Union-find over vertex-index edges -> (n_components, largest share of used verts)."""
    used = np.unique(edges)
    if used.size == 0:
        return 0, 0.0
    remap = np.full(n_verts, -1, dtype=np.int64)
    remap[used] = np.arange(used.size)
    parent = list(range(used.size))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path halving
            x = parent[x]
        return x

    for a, b in remap[edges]:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[rb] = ra
    roots = np.fromiter((find(i) for i in range(used.size)), dtype=np.int64, count=used.size)
    counts = np.bincount(roots)
    counts = counts[counts > 0]
    return int(counts.size), float(counts.max() / used.size)


def geometry_metrics(positions: np.ndarray, triangles: np.ndarray) -> dict[str, Any]:
    """Compute the per-model geometry metrics from positions + triangle indices."""
    m: dict[str, Any] = {
        "vertices": int(len(positions)),
        "triangles": int(len(triangles)),
    }
    if len(positions) == 0 or len(triangles) == 0:
        m["no_geometry"] = True
        return m

    finite_rows = np.all(np.isfinite(positions), axis=1)
    m["nonfinite_pct"] = round(float(1.0 - finite_rows.mean()) * 100, 3)
    pos = positions[finite_rows].astype(np.float64)  # f64: extreme coords overflow f32 math
    if len(pos) == 0:
        m["extent"] = 0.0
        return m

    extent = pos.max(axis=0) - pos.min(axis=0)
    diag = float(np.linalg.norm(extent))
    m["extent"] = round(diag, 6)

    # collapse: one position repeated over most of the mesh.  The inverse mapping also
    # welds duplicate positions, so connectivity below is not fooled by per-face vertex
    # splitting (every exporter duplicates positions to carry per-face normals/UVs).
    weld = np.full(len(positions), -1, dtype=np.int64)
    uniq, inv, counts = np.unique(pos, axis=0, return_inverse=True, return_counts=True)
    weld[finite_rows] = inv
    m["dup_top_share"] = round(float(counts.max() / len(pos)), 4)
    m["unique_positions"] = int(counts.size)

    # triangle edges (only tris whose vertices are all finite)
    tri_ok = triangles[np.all(finite_rows[triangles], axis=1)]
    if len(tri_ok):
        edges = np.concatenate([tri_ok[:, [0, 1]], tri_ok[:, [1, 2]], tri_ok[:, [2, 0]]])
        p64 = positions.astype(np.float64)
        lengths = np.linalg.norm(p64[edges[:, 0]] - p64[edges[:, 1]], axis=1)
        tol = diag * 1e-9
        m["degenerate_edge_pct"] = round(float((lengths <= tol).mean()) * 100, 2)
        live = lengths[lengths > tol]
        if diag > 0 and live.size:
            m["median_edge_ratio"] = round(float(np.median(live)) / diag, 5)
            m["p10_edge_ratio"] = round(float(np.percentile(live, 10)) / diag, 5)
        # connectivity on unique undirected edges, welded by position
        wedges = weld[edges]
        wedges = wedges[np.all(wedges >= 0, axis=1)]
        und = np.unique(np.sort(wedges, axis=1), axis=0)
        und = und[und[:, 0] != und[:, 1]]
        n_comp, largest = _components(len(uniq), und)
        m["n_components"] = n_comp
        m["largest_component_share"] = round(largest, 4)
    return m


def audit_model(gltf_path: str | os.PathLike) -> dict[str, Any]:
    """Read one glTF and return its quality metrics (geometry + texture presence)."""
    gltf_path = Path(gltf_path)
    gltf, positions, triangles = load_geometry(gltf_path)
    m = geometry_metrics(positions, triangles)
    if m.get("no_geometry"):
        declared = sum(
            1
            for mesh in gltf.get("meshes", [])
            for prim in mesh.get("primitives", [])
            if "POSITION" in prim.get("attributes", {})
        )
        if declared:  # meshes are declared but no accessor could be read (truncated .bin)
            m["geometry_unreadable"] = True

    # texture presence / broken image references
    has_tex = False
    missing: list[str] = []
    for mat in gltf.get("materials", []):
        pbr = mat.get("pbrMetallicRoughness", {})
        if "baseColorTexture" in pbr or "emissiveTexture" in mat:
            has_tex = True
    for img in gltf.get("images", []):
        uri = img.get("uri")
        if uri and not uri.startswith("data:") and not (gltf_path.parent / uri).is_file():
            missing.append(uri)
    m["has_material_texture"] = has_tex
    if missing:
        m["missing_texture_files"] = missing[:8]
        m["missing_texture_count"] = len(missing)
    return m


# -- scoring ---------------------------------------------------------------------------


def score_model(
    metrics: dict[str, Any],
    meta: dict[str, Any] | None = None,
    game_ctx: dict[str, Any] | None = None,
    suppress: tuple[str, ...] = (),
) -> tuple[str, list[str]]:
    """Turn metrics (+ rip metadata, + game context) into (score, reasons).

    *suppress* names reasons to drop before the verdict (known-benign exceptions).
    """
    meta = meta or {}
    game_ctx = game_ctx or {}
    hard: list[str] = []
    soft: list[str] = []

    if metrics.get("nonfinite_pct", 0) > 0:
        hard.append("nan_positions")
    n_tris = metrics.get("triangles", 0)
    ratio = metrics.get("median_edge_ratio")
    p10 = metrics.get("p10_edge_ratio", 0.0)
    if ratio is not None and n_tris >= SPAGHETTI_MIN_TRIS:
        if ratio > SPAGHETTI_GARBAGE and p10 > SPAGHETTI_P10_GARBAGE:
            hard.append("spaghetti")
        elif ratio > SPAGHETTI_SUSPECT and p10 > SPAGHETTI_P10_SUSPECT:
            soft.append("spaghetti_mild")
    if not metrics.get("no_geometry"):
        verts = metrics.get("vertices", 0)
        if metrics.get("extent") == 0.0 and verts >= 3:
            hard.append("collapsed_extent")
        elif metrics.get("dup_top_share", 0) > DUP_TOP_SHARE and verts >= 12:
            hard.append("collapsed_positions")
        deg = metrics.get("degenerate_edge_pct", 0)
        if deg > DEGENERATE_EDGE_SHARE * 200:
            hard.append("degenerate_edges")
        elif deg > DEGENERATE_EDGE_SHARE * 100:
            soft.append("degenerate_edges_mild")
        n_comp = metrics.get("n_components", 0)
        if (
            verts >= SHATTER_MIN_VERTS
            and n_comp >= SHATTER_COMPONENTS
            and metrics.get("largest_component_share", 1.0) < SHATTER_LARGEST_SHARE
            and n_tris < n_comp * SHATTER_TRIS_PER_COMP
        ):
            soft.append("shattered")
        median_v = game_ctx.get("median_vertices", 0)
        if (
            median_v >= TINY_MIN_MEDIAN
            and 0 < verts < median_v * TINY_SHARE
            and n_tris > 0
        ):
            soft.append("tiny_vs_siblings")
    if metrics.get("missing_texture_count"):
        soft.append("missing_texture_files")
    if metrics.get("geometry_unreadable"):
        soft.append("unreadable_geometry")
    if metrics.get("unreadable"):
        soft.append("unreadable")

    if suppress:
        hard = [r for r in hard if r not in suppress]
        soft = [r for r in soft if r not in suppress]
    if hard:
        return _HARD, hard + soft
    if soft:
        return _SOFT, soft

    untex = (meta.get("textures") or 0) == 0 and not metrics.get("has_material_texture")
    if untex and game_ctx.get("textured_share", 0.0) >= GAME_TEXTURED_MIN and n_tris > 0:
        return "untextured", ["untextured"]
    return "ok", []


_SEVERITY = {"garbage": 0, "suspect": 1, "untextured": 2, "ok": 3}


# -- per-game / library drivers --------------------------------------------------------


def _game_context(models: list[dict]) -> dict[str, Any]:
    verts = [m.get("vertices") or 0 for m in models if (m.get("triangles") or 0) > 0]
    textured = [1 if (m.get("textures") or 0) > 0 else 0 for m in models]
    return {
        "median_vertices": float(np.median(verts)) if verts else 0.0,
        "textured_share": float(np.mean(textured)) if textured else 0.0,
    }


def audit_game(root: str | os.PathLike, gid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Audit one game folder.  Returns (game report, {"GID/out_rel": flag} dict)."""
    root = Path(root)
    rr_path = root / gid / "rip_results.json"
    with open(rr_path, encoding="utf-8") as fh:
        rr = json.load(fh)
    models = [
        m
        for m in rr.get("models", [])
        if m.get("out_rel") and not m.get("error") and not m.get("duplicate_of")
    ]
    ctx = _game_context(models)
    counts = {"garbage": 0, "suspect": 0, "untextured": 0, "ok": 0}
    rows: list[dict[str, Any]] = []
    flags: dict[str, Any] = {}
    for i, meta in enumerate(models):
        out_rel = meta["out_rel"]
        n_tris = meta.get("triangles") or 0
        if n_tris > MAX_TRIANGLES:
            metrics: dict[str, Any] = {
                "triangles": n_tris,
                "vertices": meta.get("vertices") or 0,
                "skipped_large": True,
            }
        else:
            gpath = root / gid / out_rel
            try:
                metrics = audit_model(gpath)
            except FileNotFoundError:
                if gpath.with_suffix(".bin").is_file():
                    # per-part entry folded into a merged glTF (e.g. Melee jobj parts):
                    # the .bin remains, the per-part .gltf does not.  Not a defect.
                    metrics = {"merged_bin_only": True, "triangles": n_tris}
                else:
                    metrics = {"unreadable": True, "triangles": n_tris}
            except (OSError, ValueError, json.JSONDecodeError):
                metrics = {"unreadable": True, "triangles": n_tris}
        key = f"{gid}/{out_rel}"
        suppress: tuple[str, ...] = ()
        if any(fnmatch.fnmatch(key, pat) for pat in SPAGHETTI_EXEMPT):
            suppress = ("spaghetti", "spaghetti_mild")
        score, reasons = score_model(metrics, meta, ctx, suppress=suppress)
        counts[score] += 1
        if score != "ok":
            flags[f"{gid}/{out_rel}"] = {"score": score, "reasons": reasons}
            rows.append(
                {
                    "n": i,
                    "out_rel": out_rel,
                    "score": score,
                    "reasons": reasons,
                    "metrics": metrics,
                }
            )
    rows.sort(key=lambda r: (_SEVERITY[r["score"]], -r["metrics"].get("triangles", 0)))
    report = {
        "title": rr.get("title"),
        "models_scored": len(models),
        "garbage": counts["garbage"],
        "suspect": counts["suspect"],
        "untextured": counts["untextured"],
        "worst": rows[:10],
    }
    return report, flags


def _write_outputs(root: Path, games: dict, flags: dict, n_scored: int) -> None:
    totals = {k: sum(g[k] for g in games.values()) for k in ("garbage", "suspect", "untextured")}
    top = sorted(games.items(), key=lambda kv: kv[1]["garbage"], reverse=True)
    summary = {
        "scored": n_scored,
        **totals,
        "top_garbage_games": [
            {"game_id": gid, "title": g["title"], "garbage": g["garbage"]}
            for gid, g in top[:25]
            if g["garbage"]
        ],
    }
    report = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "games": games,
        "summary": summary,
    }
    tmp = root / "quality_report.json.tmp"
    tmp.write_text(json.dumps(report), encoding="utf-8")
    tmp.replace(root / "quality_report.json")
    tmp = root / "quality_flags.json.tmp"
    tmp.write_text(json.dumps(flags), encoding="utf-8")
    tmp.replace(root / "quality_flags.json")


def audit_library(
    root: str | os.PathLike = ROOT,
    limit_games: int | None = None,
    only: list[str] | None = None,
) -> dict[str, Any]:
    """Audit every game folder under *root* (serial, one sequential pass per game).

    Progress prints every 25 games; partial reports land on disk every 50 so a crash
    keeps its results.  Returns the full report dict.
    """
    root = Path(root)
    gids = only or sorted(
        e.name
        for e in os.scandir(root)
        if e.is_dir() and (root / e.name / "rip_results.json").is_file()
    )
    if limit_games:
        gids = gids[:limit_games]
    games: dict[str, Any] = {}
    flags: dict[str, Any] = {}
    n_scored = 0
    t0 = time.time()
    for i, gid in enumerate(gids, 1):
        try:
            report, gflags = audit_game(root, gid)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[{i}/{len(gids)}] {gid}: SKIP ({exc})", flush=True)
            continue
        games[gid] = report
        flags.update(gflags)
        n_scored += report["models_scored"]
        if i % 25 == 0 or i == len(gids):
            dt = time.time() - t0
            print(
                f"[{i}/{len(gids)}] {gid}  models={n_scored}  "
                f"garbage={sum(g['garbage'] for g in games.values())}  "
                f"suspect={sum(g['suspect'] for g in games.values())}  "
                f"({dt / 60:.1f} min)",
                flush=True,
            )
        if i % 50 == 0:
            _write_outputs(root, games, flags, n_scored)
    _write_outputs(root, games, flags, n_scored)
    return {"games": games, "flags": flags, "scored": n_scored}


if __name__ == "__main__":
    audit_library()
