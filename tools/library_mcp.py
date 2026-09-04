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
def model_glb(gltf_path: str, dest: str | None = None) -> dict:
    """Pack one model (its ``g`` path from list_models) into a self-contained ``.glb`` on disk.

    Textures and geometry are bundled in; returns ``{glb, bytes, source}``.  ``dest`` overrides
    the output path (defaults to the model's own folder)."""
    return lq.pack_glb(ROOT, gltf_path, dest)


if __name__ == "__main__":
    mcp.run()
