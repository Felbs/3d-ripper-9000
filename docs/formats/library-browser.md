# Library browser (`gcrip library`)

`gcrip/library.py` + the `library` CLI command build one page over **every** ripped game and
serve the dump root:

- `build_index(root)` reads only `batch_results.jsonl` and each game's `rip_results.json`
  (never a disc image, so it is safe to run mid-rip), picks a hero thumbnail per game (the
  highest-triangle model whose `_thumb.png` exists on disk) and up to 24 top models, and bakes
  the catalog into a self-contained `library.html` at the dump root.
- `serve_library(root)` reuses `gcrip.serve.make_handler` (so `/glb?path=<game>/<rel>.gltf`
  packs any model into a self-contained `.glb` on the fly, and `/open` launches Blender), and
  redirects `/` to `library.html`.
- The page: sticky header with library totals, instant search (title / disc / id), sort
  (triangles / models / title / textures), filter chips (Has models / Textured / Skinned /
  Animated), a responsive card grid with hero thumbnails, click-to-expand inline strips of a
  game's top models, and — when served — a click on any model thumbnail opens a `model-viewer`
  (jsDelivr CDN) 3D preview of its `/glb`. From `file://` it degrades to the report links.

A served page also has a **Refresh** button hitting `/catalog.json` (regenerated on demand, no polling) so the library reflects newly ripped games without restarting.  `build_catalog(root)` returns `{games, stats}` for both the baked page and that endpoint.  A game's expand strip shows the baked top 24, plus a **Show all N models** link (served) that fetches `/models.json?game=<id>` - the full thumbnailed set, biggest first, capped at 600 (`game_models(root, gid)`) - so every model is browsable/previewable, not just the top slice.

`gcrip library "D:/3d dump/GameCube"` serves; `--build-only` just writes the file.

## MCP server over the library

`gcrip/library_query.py` is a small importable/testable query layer on top of `build_catalog` /
`game_models` (catalog cached against `batch_results.jsonl` mtime), and `tools/library_mcp.py`
(FastMCP, registered as **gcrip-library** in `.mcp.json`, dump root via `GCRIP_DUMP_ROOT`) turns
it into assistant tools:

- `library_stats()` - games / with_geo / models / tris / tex totals.
- `search_games(query, textured, skinned, animated, has_models, sort, limit)` - compact game
  summaries; `sort` in tris|models|textures|title; query matches title / disc filename / id.
- `list_models(game, limit, offset)` - a game's models biggest-first with thumbnail (`t`) and
  glTF (`g`) paths, paginated; resolves `game` by id or title.
- `model_glb(gltf_path, dest)` - pack a model's `g` path into a self-contained `.glb` on disk
  (the only writing tool); guards the path to inside the dump root and to a real `.gltf`.

All reads hit only the metadata JSONs, so it is safe to query while a rip is running.
