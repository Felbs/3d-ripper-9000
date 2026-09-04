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

## Faceted model search (2026-09-04, evening)

`gcrip/model_tags.py` classifies every model into a **kind** - character / weapon / vehicle /
level / prop / ui / effect / unknown - from its name+path tokens (whole-word keyword tables,
plus substring matches for long unambiguous tokens so `steelsword` hits) and the rig: a skinned
or animated mesh with no name signal is a character, and a rig outweighs a weak level/prop name
hit.  Precision over recall: ~36% of models classify on the real library (29% character, and
weapons/vehicles/levels/ui in the hundreds), the numeric-named rest stay `unknown` rather than
guessed.

Model cards gain `k` (kind), `r` (rigged), `a` (animated); game entries gain per-game `kinds`
counts + `rigged`/`animated` totals; stats gains library-wide `kinds`.  The page gains a
**Games | Models mode toggle**, category chips with live counts (chips AND together; rigged is
its own facet), kind badges on model cards, and Models mode searches the whole library through
the served `/search_models.json` (query + kind + rigged + animated + game + min_tris; from
`file://` it degrades to searching the baked top-24 strips).  `library_query.search_models`
is the same engine for the MCP server (`search_models` tool) - per-game model lists cached on
each `rip_results.json` mtime (first scan ~30 s over 638 games, then ~30 ms).

## Game pages (2026-09-04 night)

Clicking a game card now opens **that game's own page** (`#g=<id>` hash route, linkable,
back/forward safe): a header with the title, disc, badges and the full-report link, then a
grid of **every** model in the game (served: fetched once through `/models.json`; `file://`:
the baked top 24 with a note).  The search box scopes to that game's model names and the
category chips filter within it; every thumbnail 3D-previews.  In Models mode the game-title
line on each card jumps to that game's page.  The old inline expand strip is gone - the page
replaced it.

## Review flags - the user's audit loop (2026-09-04 night)

The user reviews models in the UI and flags glitchy ones; the flags are the work list for
rip fixes.  Every model card and the 3D viewer carry a 🚩 toggle (with an optional note
prompt - "arm bent", "spikes"); flags persist in **`review_flags.json` at the dump root**
(atomic tmp+replace writes, keys are the model's glTF/thumb rel path, validated relative).
Served endpoints: `/flag?key&on&n&gid&note` and `/flags.json`; a "🚩 Flagged" chip (with
count) filters models AND games to the flagged set.  `library_query.read_flags/set_flag/
flagged_models` is the API - `flagged_models` joins flags with live catalog data and keeps
orphaned flags visible as "(no longer in catalog)".  The MCP server exposes `flagged_models`
so a session starts by reading the audit list and grouping it by game/format.
