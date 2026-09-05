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
  "count": 72621, "humanoid": 3176, "inferred": 5015, "animated": 2105, "games": 130,
  "rigs": [
    {
      "gid": "GZLE01", "title": "THE LEGEND OF ZELDA The Wind Waker",
      "n": "acarm.bdl",
      "g": "GZLE01/res/Object/Ac.arc/archive/bdl/acarm.gltf",
      "blend": "GZLE01/res/Object/Ac.arc/archive/bdl/acarm.blend",
      "t": "GZLE01/res/Object/Ac.arc/archive/bdl/acarm_thumb.png",
      "tris": 466, "tex": 2,
      "joints": 15, "std": 6, "humanoid": false,
      "std_bones": {"handL": "LeftHand", "armL2": "LeftForeArm", "armL1": "LeftArm", ...},
      "joint_names": ["world_root", "armL_loc", "armL1", ...],
      "clips": ["acarm_wait01", "acarm_talk01", ...]
    },
    {
      "gid": "G6FE69", "title": "2006 FIFA World Cup", "n": "m200__.ord",
      "joints": 51, "std": 22, "humanoid": true, "inferred": true, "weights": true,
      "std_bones": {"Hips": "Hips", "LCollarBone": "LeftShoulder", "LArm": "LeftArm", ...}
    }
  ]
}
```

- All paths are relative to `root`.  `g` is the glTF 2.0 file: it carries the skin
  (inverse bind matrices), the joint hierarchy as nodes, and the sampled clips as
  animations - import it in Blender with the stock glTF importer or gcrip's
  `bpy.ops.gcrip.import_gltf`.  `blend` exists when the rip also wrote a `.blend` asset.
- `std_bones` maps the game's joint name to the Mixamo-standard bone name
  (`Hips`, `Spine`, `LeftArm`, `LeftForeArm`, `LeftHand`, ...).  `std` is its size.
  Unmapped joints keep their game names.
- `humanoid` is the mocap flag: the map covers the Mixamo **core** (Hips, both
  Arm/ForeArm/Hand, both UpLeg/Leg/Foot) *and* the mesh carries skin weights.  That is
  what the `humanoid` filter keeps and what the Blender add-on's retarget needs; spine
  chain, neck, head, shoulders and toes are welcome but optional.
- `inferred: true` means the ripper wrote no map (every non-J3D format) and the
  structural mapper (`gcrip/humanoid.py`) derived it from the joint names + hierarchy.
  `weights` says whether the glTF carries `JOINTS_0`/`WEIGHTS_0`; a rig without them
  (the Radical p3d games: Simpsons Hit & Run / Road Rage, Hulk, Dark Summit, Scream Arena)
  gets a map but stays `humanoid: false` - the skeleton would move, the body would not.
  Inference results are cached in `rigs_infer_cache.json` next to the manifest.
- `joints` is the skeleton size; `joint_names` is the full ordered list (glTF node order).
- `clips` are the animation names present in the glTF.
- Records are sorted best-first: humanoid, then most standard bones, joints, triangles.

## How the map is guessed (gcrip/humanoid.py)

Joint names are split into tokens (`LCollarBone` -> l, collar, bone; `J_Leg_L2_Knee` ->
j, leg, l, 2, knee), each token gets a role (hand/foot/toe/head/neck/clavicle/arm/leg/
hips/spine, English + roman-ised Japanese) and a side (left/right/l/r).  Then the mapper
walks the hierarchy: hands and feet are the sided end joints (the real ankle wins over an
IK handle called `Left_Foot` because it sits at the end of a same-side chain), the
forearm is the `elbow` joint or the first forearm-role ancestor, the upper arm the next
plain joint, twist/roll/IK/handle joints are skipped, the hips are where the two thighs
and the neck meet, and the joints between hips and neck become Spine/Spine1/Spine2.
The same code, embedded verbatim, runs inside the Blender add-on on any armature without
`gcrip_std_bone` props (`tools/sync_addon_humanoid.py` keeps the copy current).

## For the mocap / Blender add-on: the MCP route

The `gcrip-library` MCP server (`.mcp.json`, `tools/library_mcp.py`) is the intended way
for another Claude session to drive this library.  The tools that matter for putting a
motion-captured character into a game setting:

| tool | gives you |
|---|---|
| `library_root()` | the absolute dump root, manifest/report paths, served URL - resolve every relative path with it |
| `mocap_rigs(min_std_bones=0, game=None, query="", limit=500)` | **the retargetable characters**: `humanoid` rigs (core map + skin weights, ripper-mapped or inferred); each record has `abs_gltf` / `abs_thumb` / `abs_blend`, `joints`, `std_bones` (game joint -> `Hips`/`Spine`/`LeftArm`/...), `clips`; `min_std_bones=22` = the full set incl. spine chain, neck, head, shoulders, toes |
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

## Driving Blender itself: the `gcrip-blender` MCP server

`tools/blender_mcp.py` (registered in `.mcp.json` as `gcrip-blender`) talks to the
add-on's control channel (127.0.0.1:8788, "GCRip Server" panel; or launch Blender with
`blender/gcrip_server_boot.py`, `-b` for a headless worker).  The whole
pick-a-character-and-animate-it loop is then tool calls:

| tool | does |
|---|---|
| `blender_status()` / `blender_launch(background, blend)` | find or start a Blender with the server up |
| `blender_games(query)` / `blender_library(gid, category, query, humanoid)` | the add-on's own library index (same rows as the Library panel; `humanoid=True` = mocap-ready) |
| `blender_spawn(gltf | gid+name, at)` | import; characters come back Mixamo-named with `mocap_ready` / `missing_core` / `skinned_meshes` |
| `blender_retarget(bvh, object, start, max_frames)` | BVH -> NLA strip on track MOCAP |
| `blender_camera(target, azimuth, distance, height)` | aim a tracking camera from in front of the character (adds a sun if unlit) |
| `blender_render(path, frame | animation, start, end)` | PNG still or H.264 MP4 |
| `blender_characters()` / `blender_scene()` / `blender_frame()` / `blender_save()` / `blender_open()` / `blender_delete()` | inspect and manage the scene |
| `blender_python(code)` | anything else, inside Blender |

`python tools/blender_mcp_smoke.py <out_dir> [query] [game_id] [bvh]` exercises the whole
chain headless (spawn, retarget, camera, two stills, save) on port 8790.

## Filters

`rigged_models(root, min_joints=2, humanoid=False, game=None, query="")` - `game` takes an
id or a title fragment; `query` matches model names and titles.  The UI's Rigs view exposes
the same three knobs (humanoid toggle, min joints, search).
