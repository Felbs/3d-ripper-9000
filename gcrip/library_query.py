"""Query layer over the ripped-model library - the logic behind ``gcrip library`` and the
library MCP server (``tools/library_mcp.py``), kept here so it is importable and testable.

Everything reads the small metadata JSONs (``batch_results.jsonl`` + each game's
``rip_results.json``) through :mod:`gcrip.library`; the catalog is cached against the batch
file's mtime so repeated queries in one session do not re-scan every game.
"""

from __future__ import annotations

import json
import threading as _threading
import time as _time
from pathlib import Path

from gcrip.library import build_catalog, game_models

_cache: dict[str, object] = {"root": None, "mtime": None, "cat": None}


_cat_lock = _threading.Lock()


def catalog(root: Path) -> dict:
    """The ``{games, stats}`` catalog, cached until ``batch_results.jsonl`` changes.  The
    rebuild is serialized: concurrent callers wait for one rebuild instead of stacking
    full re-scans against a drive a rip may be using."""
    root = Path(root)
    batch = root / "batch_results.jsonl"
    mtime = batch.stat().st_mtime if batch.exists() else None
    if _cache["root"] != str(root) or _cache["mtime"] != mtime or _cache["cat"] is None:
        with _cat_lock:
            if _cache["root"] != str(root) or _cache["mtime"] != mtime or _cache["cat"] is None:
                _cache.update(root=str(root), mtime=mtime, cat=build_catalog(root))
    return _cache["cat"]  # type: ignore[return-value]


def stats(root: Path) -> dict:
    return catalog(root)["stats"]


_SORTS = {
    "tris": "tris",
    "triangles": "tris",
    "models": "models",
    "textures": "textures",
    "tex": "textures",
}


def search_games(
    root: Path,
    query: str = "",
    *,
    textured: bool | None = None,
    skinned: bool | None = None,
    animated: bool | None = None,
    has_models: bool | None = None,
    sort: str = "tris",
    limit: int = 50,
) -> list[dict]:
    """Games matching the query/filters, as compact summaries (no per-model thumbnails)."""
    q = query.strip().lower()
    out = []
    for g in catalog(root)["games"]:
        if has_models and g["tris"] <= 0:
            continue
        if textured is True and g["textures"] <= 0:
            continue
        if skinned is True and not g["skinned"]:
            continue
        if animated is True and g["clips"] <= 0:
            continue
        hay = (g["title"] + " " + g["disc"] + " " + g["id"]).lower()
        if q and q not in hay:
            continue
        out.append(
            {
                "id": g["id"],
                "title": g["title"],
                "disc": g["disc"],
                "models": g["models"],
                "triangles": g["tris"],
                "textures": g["textures"],
                "skinned": g["skinned"],
                "clips": g["clips"],
                "report": g["report"],
            }
        )
    if sort == "title":
        out.sort(key=lambda x: x["title"].lower())
    else:
        key = _SORTS.get(sort, "tris")
        field = {"tris": "triangles", "models": "models", "textures": "textures"}[key]
        out.sort(key=lambda x: -x[field])
    return out[: max(1, limit)]


def find_game(root: Path, game_id_or_title: str) -> dict | None:
    key = game_id_or_title.strip().lower()
    exact = None
    for g in catalog(root)["games"]:
        if g["id"].lower() == key:
            return g
        if exact is None and key in g["title"].lower():
            exact = g
    return exact


def list_models(root: Path, game_id_or_title: str, *, limit: int = 100, offset: int = 0) -> dict:
    """A game's models (biggest first) with their thumbnail and glTF paths; paginated."""
    g = find_game(root, game_id_or_title)
    if g is None:
        return {"error": f"no game matching {game_id_or_title!r}", "models": [], "total": 0}
    full = game_models(root, g["id"])
    window = full["models"][offset : offset + max(1, limit)]
    return {
        "id": g["id"],
        "title": g["title"],
        "total": full["total"],
        "offset": offset,
        "returned": len(window),
        "models": window,
    }


_model_cache: dict[str, tuple[float | None, dict]] = {}


def game_models_cached(root: Path, gid: str) -> dict:
    """One game's ``{id, models, total}``, cached against its ``rip_results.json`` mtime -
    what the served ``/models.json`` returns, without re-reading an unchanged game."""
    rr = Path(root) / gid / "rip_results.json"
    try:
        mtime = rr.stat().st_mtime
    except OSError:
        mtime = None
    hit = _model_cache.get(gid)
    if hit is None or hit[0] != mtime:
        hit = (mtime, game_models(root, gid))
        _model_cache[gid] = hit
    return hit[1]


def _models_cached(root: Path, gid: str) -> list[dict]:
    return game_models_cached(root, gid)["models"]


def search_models(
    root: Path,
    query: str = "",
    *,
    kind: str | None = None,
    rigged: bool | None = None,
    animated: bool | None = None,
    game: str | None = None,
    min_triangles: int = 0,
    limit: int = 200,
) -> dict:
    """Model-level search across the whole library - "every sword", "rigged characters".

    Matches the query against model names and game titles, filters by classified ``kind``
    (:data:`gcrip.model_tags.KINDS`), rig/animation flags and triangle count, and returns flat
    model cards each tagged with its game (``gid`` / ``title``).  Reads each game's cached
    model list through :func:`gcrip.library.game_models`, so it touches only metadata JSONs.
    """
    from gcrip.model_tags import KINDS

    q = query.strip().lower()
    if kind is not None and kind not in KINDS:
        return {"error": f"kind must be one of {', '.join(KINDS)}", "models": []}
    out = []
    games = catalog(root)["games"]
    if game:
        g = find_game(root, game)
        games = [g] if g else []
    for g in games:
        if not g.get("nmodels"):
            continue
        title = g["title"]
        title_hit = q and q in title.lower()
        for m in _models_cached(root, g["id"]):
            if kind is not None and m.get("k") != kind:
                continue
            if rigged is not None and bool(m.get("r")) != rigged:
                continue
            if animated is not None and bool(m.get("a")) != animated:
                continue
            if m.get("tris", 0) < min_triangles:
                continue
            if q and not title_hit and q not in m["n"].lower():
                continue
            out.append({**m, "gid": g["id"], "title": title})
            if len(out) >= max(1, limit) * 4:
                break
    out.sort(key=lambda m: -m["tris"])
    return {"models": out[: max(1, limit)], "total": len(out)}


FLAGS_FILE = "review_flags.json"


def read_flags(root: Path) -> dict:
    """The review flags the user set in the library UI - ``{key: {n, gid, note?, time}}``
    where ``key`` is the model's glTF path (or thumb path when it has no glTF)."""
    p = Path(root) / FLAGS_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_flag(
    root: Path, key: str, on: bool, *, name: str = "", gid: str = "", note: str = ""
) -> dict:
    """Set or clear one review flag; returns the updated flag map.  Keys are validated to
    stay relative (no drive letters or parent escapes)."""
    key = key.strip().replace("\\", "/")
    if not key or key.startswith("/") or ".." in key or ":" in key:
        return read_flags(root)
    flags = read_flags(root)
    if on:
        entry = {
            "n": name or key.rsplit("/", 1)[-1],
            "gid": gid or key.split("/", 1)[0],
            "time": _time.strftime("%Y-%m-%d %H:%M"),
        }
        if note:
            entry["note"] = note[:500]
        flags[key] = entry
    else:
        flags.pop(key, None)
    tmp = Path(root) / (FLAGS_FILE + ".tmp")
    tmp.write_text(json.dumps(flags, indent=1), encoding="utf-8")
    tmp.replace(Path(root) / FLAGS_FILE)
    return flags


def flagged_models(root: Path) -> list[dict]:
    """The flagged models joined with their live catalog data (title, tris, kind) - what a
    session reads to see which models the user marked as glitchy and which games/formats
    they cluster in."""
    flags = read_flags(root)
    out = []
    for g in catalog(root)["games"]:
        if not g.get("nmodels"):
            continue
        for m in _models_cached(root, g["id"]):
            key = m.get("g") or m.get("t")
            if key in flags:
                out.append(
                    {
                        **m,
                        "gid": g["id"],
                        "title": g["title"],
                        **{k: v for k, v in flags[key].items() if k in ("note", "time")},
                    }
                )
    known = {m.get("g") or m.get("t") for m in out}
    for key, e in flags.items():  # flags whose model vanished from the catalog still show
        if key not in known:
            out.append(
                {
                    "n": e.get("n", key),
                    "g": key,
                    "gid": e.get("gid", ""),
                    "title": "(no longer in catalog)",
                    "tris": 0,
                    **e,
                }
            )
    return out


def pack_glb(root: Path, rel_gltf: str, dest: str | None = None) -> dict:
    """Pack ``<root>/<rel_gltf>`` (a model's ``g`` path) into a self-contained ``.glb`` and
    return where it was written."""
    from gcrip.export import glb as glbmod

    root = Path(root)
    src = (root / rel_gltf).resolve()
    if root not in src.parents or src.suffix != ".gltf" or not src.exists():
        return {"error": f"no such .gltf under the dump root: {rel_gltf}"}
    out = Path(dest) if dest else src.with_suffix(".glb")
    data = glbmod.pack(src)
    out.write_bytes(data)
    return {"glb": str(out), "bytes": len(data), "source": rel_gltf}


RIGS_FILE = "rigs_manifest.json"
INFER_FILE = "rigs_infer_cache.json"


def gltf_skeleton(path: Path) -> tuple[list[str], list[int | None], bool]:
    """(node names, parent index per node, has skin weights) from a glTF: the joint tree,
    plus whether any primitive carries JOINTS_0/WEIGHTS_0 (some format exporters write the
    skeleton but drop the weights - such a rig cannot be animated)."""
    g = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = g.get("nodes", [])
    parents: list[int | None] = [None] * len(nodes)
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            if 0 <= c < len(nodes):
                parents[c] = i
    weights = any(
        "JOINTS_0" in p.get("attributes", {}) and "WEIGHTS_0" in p.get("attributes", {})
        for m in g.get("meshes", [])
        for p in m.get("primitives", [])
    )
    return [n.get("name", f"node_{i}") for i, n in enumerate(nodes)], parents, weights


def gltf_hierarchy(path: Path) -> tuple[list[str], list[int | None]]:
    """(node names, parent index per node) from a glTF's ``nodes`` - the joint tree."""
    names, parents, _w = gltf_skeleton(path)
    return names, parents


def infer_std_bones(root: Path, rigs: list[dict]) -> int:
    """Fill ``std_bones`` for rigs the ripper left unmapped (every non-J3D format) by
    running the structural humanoid mapper on the glTF's joint tree.  Only rigs whose joint
    names *look* humanoid are opened; results are cached in ``rigs_infer_cache.json`` next
    to the manifest, keyed by glTF path + mtime.  Returns how many rigs gained a map."""
    from gcrip import humanoid as _hm

    cache_path = Path(root) / INFER_FILE
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    dirty = gained = 0
    for r in rigs:
        if r["std"] or r["joints"] < 8 or not r["g"]:
            continue
        if not _hm.humanoid_hint(r["joint_names"]):
            continue
        p = Path(root) / r["g"]
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        hit = cache.get(r["g"])
        if hit and hit.get("mtime") == mtime and "weights" in hit:
            std, weights = hit["std_bones"], hit["weights"]
        else:
            try:
                names, parents, weights = gltf_skeleton(p)
                std = {names[i]: v for i, v in _hm.guess_bones(names, parents).items()}
            except (OSError, ValueError, KeyError):
                std, weights = {}, False
            cache[r["g"]] = {"mtime": mtime, "std_bones": std, "weights": weights}
            dirty += 1
        r["weights"] = weights
        if std:
            r["std_bones"], r["std"], r["inferred"] = std, len(std), True
            gained += 1
    if dirty:
        try:
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache), encoding="utf-8")
            tmp.replace(cache_path)
        except OSError:
            pass
    return gained


def rigged_models(
    root: Path,
    *,
    min_joints: int = 2,
    humanoid: bool = False,
    game: str | None = None,
    query: str = "",
    infer: bool = True,
) -> list[dict]:
    """Every skinned (rigged) model in the library with what a rig consumer needs: the glTF
    (skin + joints + clips), the .blend when one exists, joint count and names, the
    ``std_bones`` map (game joint name -> Mixamo-standard bone, the retargeting key) and
    the clip names.  ``humanoid`` keeps rigs whose map covers the Mixamo core (hips, both
    arms + hands, both legs + feet) - the set the mocap retarget needs.  ``infer`` runs the
    structural mapper on rigs the ripper left unmapped (``inferred: True`` on those).
    Reads rip_results.json (+ the glTF joint tree for inferred rigs; mid-rip safe)."""
    from gcrip.humanoid import is_humanoid

    q = query.strip().lower()
    out = []
    games = catalog(root)["games"]
    if game:
        g = find_game(root, game)
        games = [g] if g else []
    for g in games:
        if not g.get("rigged"):
            continue
        try:
            rr = json.loads((Path(root) / g["id"] / "rip_results.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for m in rr.get("models", []) if isinstance(rr, dict) else rr:
            if not m.get("skinned") or m.get("duplicate_of") or m.get("error"):
                continue
            joints = int(m.get("joints") or 0)
            if joints < min_joints:
                continue
            std = m.get("std_bones") or {}
            name = (m.get("path") or m.get("out_rel") or "model").split("/")[-1]
            if q and q not in name.lower() and q not in g["title"].lower():
                continue
            out_rel = m.get("out_rel") or ""
            out.append(
                {
                    "gid": g["id"],
                    "title": g["title"],
                    "n": name,
                    "g": f"{g['id']}/{out_rel}" if out_rel.endswith(".gltf") else None,
                    "blend": f"{g['id']}/{m['blend_rel']}" if m.get("blend_rel") else None,
                    "t": f"{g['id']}/{m['thumb']}" if m.get("thumb") else None,
                    "tris": int(m.get("triangles") or 0),
                    "tex": int(m.get("textures") or 0),
                    "joints": joints,
                    "std": len(std),
                    "std_bones": std,
                    "joint_names": m.get("joint_names") or [],
                    "clips": list(m.get("animations") or []),
                    "k": "character",
                    "r": True,
                    "a": bool(m.get("animations")),
                }
            )
    if infer:
        infer_std_bones(root, out)
    for r in out:
        # a full core map, and skin weights to move (unknown for ripper-mapped rigs = yes)
        r["humanoid"] = is_humanoid(r["std_bones"]) and r.get("weights", True)
    if humanoid:
        out = [r for r in out if r["humanoid"]]
    out.sort(key=lambda x: (-x["humanoid"], -x["std"], -x["joints"], -x["tris"]))
    return out


def write_rigs_manifest(root: Path, **filters) -> dict:
    """Write ``rigs_manifest.json`` at the dump root - the full rigged-model list for other
    tools (the mocap/Blender add-on) to consume without the server.  Returns a summary."""
    rigs = rigged_models(root, **filters)
    doc = {
        "generated": _time.strftime("%Y-%m-%d %H:%M"),
        "root": str(Path(root)),
        "paths": "relative to root; 'g' is the glTF with skin+joints+clips, 'blend' the .blend",
        "count": len(rigs),
        "humanoid": sum(1 for r in rigs if r["humanoid"]),
        "inferred": sum(1 for r in rigs if r.get("inferred")),
        "animated": sum(1 for r in rigs if r["clips"]),
        "games": len({r["gid"] for r in rigs}),
        "rigs": rigs,
    }
    tmp = Path(root) / (RIGS_FILE + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    tmp.replace(Path(root) / RIGS_FILE)
    return {k: v for k, v in doc.items() if k != "rigs"}
