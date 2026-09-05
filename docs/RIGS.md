# Character rigs - the library's rigged-model manifest

For tools that consume rigs (the mocap-to-Blender add-on): every skinned model in the
GameCube library, with what you need to load and retarget it, in one file.

## Where

`D:/3d dump/GameCube/rigs_manifest.json` - regenerate any time with

    python -c "from gcrip.library_query import write_rigs_manifest; print(write_rigs_manifest('D:/3d dump/GameCube'))"

or through the library MCP server (`write_rigs_manifest` / `rigged_models` tools), or the
served endpoint `http://127.0.0.1:8765/rigs.json` (live; same records) while
`gcrip library` runs.  The library UI's **🦴 Rigs** view is the same list, browsable.

## Schema

```json
{
  "generated": "2026-09-05 08:40",
  "root": "D:\\3d dump\\GameCube",
  "count": 12345, "humanoid": 2345, "animated": 4567, "games": 210,
  "rigs": [
    {
      "gid": "GZLE01", "title": "THE LEGEND OF ZELDA The Wind Waker",
      "n": "acarm.bdl",
      "g": "GZLE01/res/Object/Ac.arc/archive/bdl/acarm.gltf",
      "blend": "GZLE01/res/Object/Ac.arc/archive/bdl/acarm.blend",
      "t": "GZLE01/res/Object/Ac.arc/archive/bdl/acarm_thumb.png",
      "tris": 466, "tex": 2,
      "joints": 15, "std": 6,
      "std_bones": {"handL": "LeftHand", "armL2": "LeftForeArm", "armL1": "LeftArm", ...},
      "joint_names": ["world_root", "armL_loc", "armL1", ...],
      "clips": ["acarm_wait01", "acarm_talk01", ...]
    }
  ]
}
```

- All paths are relative to `root`.  `g` is the glTF 2.0 file: it carries the skin
  (inverse bind matrices), the joint hierarchy as nodes, and the sampled clips as
  animations - import it in Blender with the stock glTF importer or gcrip's
  `bpy.ops.gcrip.import_gltf`.  `blend` exists when the rip also wrote a `.blend` asset.
- `std_bones` maps the game's joint name to the Mixamo-standard bone name
  (`Hips`, `Spine`, `LeftArm`, `LeftForeArm`, `LeftHand`, ...).  `std` is its size; the
  batch treats `std >= 15` as a full humanoid ("mixamo rig") - that is the `humanoid`
  filter and the right set for mocap retargeting.  Unmapped joints keep their game names.
- `joints` is the skeleton size; `joint_names` is the full ordered list (glTF node order).
- `clips` are the animation names present in the glTF.
- Records are sorted best-first: most standard bones, then most joints, then triangles.

## For the mocap / Blender add-on: the MCP route

The `gcrip-library` MCP server (`.mcp.json`, `tools/library_mcp.py`) is the intended way
for another Claude session to drive this library.  The tools that matter for putting a
motion-captured character into a game setting:

| tool | gives you |
|---|---|
| `library_root()` | the absolute dump root, manifest/report paths, served URL - resolve every relative path with it |
| `mocap_rigs(min_std_bones=15, game=None, query="", limit=500)` | **the retargetable characters**: skinned models whose skeleton maps onto >= N Mixamo-standard bones; each record has `abs_gltf` / `abs_thumb` / `abs_blend`, `joints`, `std_bones` (game joint -> `Hips`/`Spine`/`LeftArm`/...), `clips` |
| `rigged_models(min_joints, humanoid, game, query)` | every rig, humanoid or not (props with 2 joints included) |
| `level_models(query="", game=None, min_triangles=2000, limit=200)` | **the settings**: terrain / rooms / arenas / buildings, biggest first, with absolute glTF + thumbnail paths |
| `search_models(query, kind=...)` | anything else by category (weapon, vehicle, prop...) |
| `model_glb(gltf_path, dest=None)` | packs one model into a self-contained `.glb` (textures embedded) - the easiest file to import into Blender |
| `write_rigs_manifest()` | refreshes `rigs_manifest.json` for offline use |

A Blender-side preview panel needs only two things per record: `abs_thumb` (a PNG to draw
as the icon) and `abs_gltf` (or a `model_glb` output) to import with
`bpy.ops.import_scene.gltf(filepath=...)`.  The glTF already carries the armature (joint
nodes + skin + inverse bind matrices) and the clips as animations; `std_bones` tells you
which armature bone plays which Mixamo role for retargeting.  Rigs with a `.blend` also
open as Blender assets directly.

Typical flow: `library_root()` once -> `mocap_rigs(limit=50)` to list characters (draw
`abs_thumb`, import `abs_gltf`) -> `level_models(query="arena")` for a setting -> retarget
the capture onto the character's `std_bones` skeleton.

## Filters

`rigged_models(root, min_joints=2, humanoid=False, game=None, query="")` - `game` takes an
id or a title fragment; `query` matches model names and titles.  The UI's Rigs view exposes
the same three knobs (humanoid toggle, min joints, search).
