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
        entry = {"n": name or key.rsplit("/", 1)[-1], "gid": gid or key.split("/", 1)[0],
                 "time": _time.strftime("%Y-%m-%d %H:%M")}
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
                out.append({**m, "gid": g["id"], "title": g["title"],
                            **{k: v for k, v in flags[key].items() if k in ("note", "time")}})
    known = {m.get("g") or m.get("t") for m in out}
    for key, e in flags.items():  # flags whose model vanished from the catalog still show
        if key not in known:
            out.append({"n": e.get("n", key), "g": key, "gid": e.get("gid", ""),
                        "title": "(no longer in catalog)", "tris": 0, **e})
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
