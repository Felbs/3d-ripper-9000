"""Query layer over the ripped-model library - the logic behind ``gcrip library`` and the
library MCP server (``tools/library_mcp.py``), kept here so it is importable and testable.

Everything reads the small metadata JSONs (``batch_results.jsonl`` + each game's
``rip_results.json``) through :mod:`gcrip.library`; the catalog is cached against the batch
file's mtime so repeated queries in one session do not re-scan every game.
"""

from __future__ import annotations

from pathlib import Path

from gcrip.library import build_catalog, game_models

_cache: dict[str, object] = {"root": None, "mtime": None, "cat": None}


def catalog(root: Path) -> dict:
    """The ``{games, stats}`` catalog, cached until ``batch_results.jsonl`` changes."""
    root = Path(root)
    batch = root / "batch_results.jsonl"
    mtime = batch.stat().st_mtime if batch.exists() else None
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
