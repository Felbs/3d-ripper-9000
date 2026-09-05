"""MCP server over the ripped GameCube 3D-model library.

Point it at a batch dump root and an assistant can browse the whole lake:

    GCRIP_DUMP_ROOT="D:/3d dump/GameCube" python tools/library_mcp.py

Every tool reads only the small metadata JSONs (never a disc image) and the catalog is cached
until the batch file changes, so it stays cheap to call while a rip is running.  ``model_glb``
is the one tool that writes: it packs a model into a self-contained ``.glb`` on disk and hands
back the path.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from gcrip import library_query as lq

ROOT = Path(os.environ.get("GCRIP_DUMP_ROOT", "D:/3d dump/GameCube"))

mcp = FastMCP("gcrip-library")


@mcp.tool()
def library_stats() -> dict:
    """Totals for the whole library: games, how many have geometry, models, triangles, textures."""
    return lq.stats(ROOT)


@mcp.tool()
def search_games(
    query: str = "",
    textured: bool | None = None,
    skinned: bool | None = None,
    animated: bool | None = None,
    has_models: bool | None = None,
    sort: str = "tris",
    limit: int = 50,
) -> list[dict]:
    """Find games by title / disc filename / game-id and optional filters.

    ``sort`` is one of tris | models | textures | title.  Returns compact summaries
    (id, title, disc, model/triangle/texture counts, skinned/clips, report path)."""
    return lq.search_games(
        ROOT,
        query,
        textured=textured,
        skinned=skinned,
        animated=animated,
        has_models=has_models,
        sort=sort,
        limit=limit,
    )


@mcp.tool()
def list_models(game: str, limit: int = 100, offset: int = 0) -> dict:
    """Models of one game (by id or title), biggest first, paginated.

    Each model carries its name, triangle/texture counts, thumbnail path (``t``) and glTF path
    (``g``) - pass ``g`` to ``model_glb`` to get a usable file."""
    return lq.list_models(ROOT, game, limit=limit, offset=offset)


@mcp.tool()
def search_models(
    query: str = "",
    kind: str | None = None,
    rigged: bool | None = None,
    animated: bool | None = None,
    game: str | None = None,
    min_triangles: int = 0,
    limit: int = 100,
) -> dict:
    """Search MODELS across every game - "every sword", "rigged characters", "level pieces".

    ``kind`` is one of character | weapon | vehicle | level | prop | ui | effect | unknown
    (heuristic, classified from the model's name plus its rig).  ``rigged``/``animated`` filter
    on the skeleton and clips.  ``query`` matches model names and game titles; ``game`` limits
    to one game (id or title).  Results are flat model cards tagged with their game."""
    return lq.search_models(
        ROOT,
        query,
        kind=kind,
        rigged=rigged,
        animated=animated,
        game=game,
        min_triangles=min_triangles,
        limit=limit,
    )


@mcp.tool()
def rigged_models(
    min_joints: int = 2, humanoid: bool = False, game: str | None = None, query: str = ""
) -> list[dict]:
    """Every rigged (skinned) model in the library - for rig/mocap consumers.

    Each entry: game, name, glTF path (skin + joints + clips inside), .blend path, joint
    count + joint names, `std_bones` (game joint -> Mixamo-standard bone map: the retarget
    key), clip names.  ``humanoid=True`` keeps rigs with >= 15 mapped standard bones.
    ``write_rigs_manifest`` writes the same list to rigs_manifest.json at the dump root."""
    return lq.rigged_models(ROOT, min_joints=min_joints, humanoid=humanoid, game=game, query=query)


def _absolutize(rec: dict) -> dict:
    """Add absolute paths a Blender add-on can open directly (relative ones stay too)."""
    out = dict(rec)
    for key, abs_key in (("g", "abs_gltf"), ("t", "abs_thumb"), ("blend", "abs_blend")):
        if rec.get(key):
            out[abs_key] = str(ROOT / rec[key])
    return out


@mcp.tool()
def library_root() -> dict:
    """Where the library lives - absolute dump root, the manifest/report files, and the
    served URL - so another tool can resolve every relative path this server returns."""
    return {
        "root": str(ROOT),
        "rigs_manifest": str(ROOT / "rigs_manifest.json"),
        "quality_report": str(ROOT / "quality_report.json"),
        "review_flags": str(ROOT / "review_flags.json"),
        "served_url": "http://127.0.0.1:8765/library.html",
        "thumbnail_note": "each model has a <name>_thumb.png beside its glTF (the 't' path)",
    }


@mcp.tool()
def mocap_rigs(
    min_std_bones: int = 15, game: str | None = None, query: str = "", limit: int = 500
) -> list[dict]:
    """Rigs suitable for motion-capture retargeting: skinned characters whose skeleton maps
    onto >= ``min_std_bones`` Mixamo-standard bones (Hips/Spine/Arms/Legs...).  Each entry
    carries the game, name, absolute + relative glTF/thumb/.blend paths, joint count,
    ``std_bones`` (game joint -> standard bone) and clip names.  Best-first order."""
    rigs = lq.rigged_models(ROOT, humanoid=False, game=game, query=query)
    keep = [r for r in rigs if r["std"] >= min_std_bones][: max(1, limit)]
    return [_absolutize(r) for r in keep]


@mcp.tool()
def level_models(
    query: str = "", game: str | None = None, min_triangles: int = 2000, limit: int = 200
) -> list[dict]:
    """Level / environment geometry to put characters into: models classified as level
    pieces (terrain, rooms, arenas, buildings, worlds), biggest first, with absolute and
    relative glTF + thumbnail paths.  ``query`` matches model names and game titles."""
    res = lq.search_models(
        ROOT, query, kind="level", game=game, min_triangles=min_triangles, limit=limit
    )
    return [_absolutize(m) for m in res.get("models", [])]


@mcp.tool()
def write_rigs_manifest(humanoid: bool = False, min_joints: int = 2) -> dict:
    """Write rigs_manifest.json at the dump root (the full rigged-model list, no server
    needed) and return its summary counts."""
    return lq.write_rigs_manifest(ROOT, humanoid=humanoid, min_joints=min_joints)


@mcp.tool()
def flagged_models() -> list[dict]:
    """The models the user flagged as glitchy in the library UI (their review/audit list).

    Each entry carries the model's name, game, triangle count, glTF path, the flag time and
    any note the user typed.  This is the work list for rip fixes - group by game/format."""
    return lq.flagged_models(ROOT)


@mcp.tool()
def model_glb(gltf_path: str, dest: str | None = None) -> dict:
    """Pack one model (its ``g`` path from list_models) into a self-contained ``.glb`` on disk.

    Textures and geometry are bundled in; returns ``{glb, bytes, source}``.  ``dest`` overrides
    the output path (defaults to the model's own folder)."""
    return lq.pack_glb(ROOT, gltf_path, dest)


if __name__ == "__main__":
    mcp.run()
