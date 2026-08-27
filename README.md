# 3D Ripper 9000

Give it a game disc, get back every 3D model - textured, rigged, animated - as glTF you can
open in Blender. Output is organised and named the way the developers laid it out on the disc.

**gc-ripper** (`gcrip` on the command line) is the first module: GameCube. Later modules are
planned for other consoles (N64, PlayStation ...); each will be its own package under this
project, sharing the same idea - one command, disc in, models out - and the same output layout,
report and Blender add-on.

| Module | Status | Language | License | What it does |
|--------|--------|----------|---------|--------------|
| `gcrip` - GameCube | **working** (Wind Waker, Twilight Princess verified) | Python | MIT | disc walker, J3D model/animation parsers, GX texture decode, glTF export, Blender add-on |
| `dcrip` - Dreamcast | **working** (Ninja games; Phantasy Star Online verified) | Python | MIT | GDI/zip reader, ISO 9660, AFS/PRS, Ninja model/motion parsers, PVR/PVM decode, same glTF/report/Blender path |
| Dolphin capture fork (for non-J3D GameCube games) | planned | C++ | GPLv2 | runtime capture of object-space geometry for games with custom formats |
| N64 module | idea | - | - | - |
| PlayStation module | idea | - | - | - |

## Legal position

- This tool is for **personal use with discs you own and dumped yourself**.
- Anything you extract remains under its **original copyright**. Extracted
  assets are not yours to redistribute.
- **No game data belongs in this repository** - not discs, not extracted files,
  not manifests of real games. The tests use synthetic images built at test time.
- The Dolphin fork inherits Dolphin's GPLv2.

## Quick start: disc in, models out

```
pip install -e .
gcrip rip "path/to/game.iso" out/
```

That walks the disc, finds every J3D model (BMD/BDL, including inside Yaz0/Yay0
compressed RARC archives), and writes:

```
out/<GameID>/<disc path>/<model>.gltf        glTF 2.0: mesh + materials + skeleton + animation clips + expression switches
out/<GameID>/<disc path>/<model>.bin         geometry buffer
out/<GameID>/<disc path>/<model>_tex/*.png   the model's textures (all GC formats incl. CMPR decoded)
out/<GameID>/<disc path>/<model>_thumb.png   preview thumbnail
out/<GameID>/<disc path>/<model>.blend       (after `gcrip blend`) Blender asset file
out/<GameID>/<disc path>/<texture>.png       standalone BTI/TPL textures
out/<GameID>/report.html                     browsable index with thumbnails, joint names, filter box
out/<GameID>/disc_manifest.json              every file on the disc with hashes and formats
```

In Blender the default *Solid* viewport shading hides textures - press **Z > Material Preview**
(or set Solid shading's Color to Texture) to see them.

### Browse and open models

- `gcrip serve out/rip/GZLE01` opens the report in your browser with an **Open in Blender**
  and **Show file** button on every card (Blender is auto-detected; `--blender PATH` otherwise).
- `gcrip blend out/rip/GZLE01` writes one `.blend` next to every model, marked as a Blender
  **asset** (thumbnail, catalog = disc folder, tags). Register `out/rip` as an Asset Library
  (Preferences > File Paths, or the GCRip panel's *Add rip folder as asset library* button)
  and every model shows up in Blender's Asset Browser: search, drag into any scene, or open
  the `.blend` to edit that model on its own. Roughly 1-3 s per model; rerun to resume
  (existing files are skipped, `--force` rewrites).

**Recommended:** install `blender/gcrip_blender.py` (Edit > Preferences > Add-ons > Install
from Disk) and use **File > Import > GCRip glTF**. It runs the normal glTF importer and then
hides the expression/alternate meshes (Blender's importer ignores `KHR_node_visibility`, so
otherwise every eye texture is visible at once), sets the scene to 30 fps, and can rename
the bones to Mixamo names. Its **GCRip** sidebar tab (press N) has one row of buttons per
face part (eyes / mouth / brows) to switch expressions, and Mixamo <-> original bone renaming.

Wind Waker (USA): 2,759 models -> 1,856 unique glTFs, 4,175 animation clips, 1,867 textures in ~4.5 minutes.
Twilight Princess (USA): 3,626 models -> 2,489 unique glTFs, 13,822 clips in ~10 minutes.
Blender imports Link with all 594 clips in about 10 seconds.

### Dump a whole library

```
gcrip survey "D:/roms/gamecube" -o "D:/3d dump/GameCube/_survey"   # ~1 s/disc: which engine each game uses
gcrip dump   "D:/roms/gamecube" --out "D:/3d dump/GameCube"        # every disc, everything gcrip can pull
```

`gcrip dump` runs the rip on each disc (or on one `.iso`) and then every extra the disc has
data for - recompiled levels, message text, streamed audio, sequenced music, cutscenes
(`--no-extras` for models only, `--blend` for a `.blend` per model). One folder per game ID,
a `README.md` + `batch_matrix.md` at the top with per-game counts, and the Blender add-on
copied alongside so the dump folder is self-contained. Resumable: finished discs are skipped.
Non-J3D discs still get their manifest and any standalone TPL/BTI textures, and land in the
matrix as "0 models" - that is the verified-games list in
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

### Dreamcast (`dcrip`)

```
dcrip info   "game.zip"                          # IP.BIN header + track table (Redump .gdi zips or a .gdi on disk)
dcrip survey "D:/roms/dreamcast" -o "D:/3d dump/Dreamcast/_survey"   # which games use Ninja models
dcrip rip    "game.zip" "D:/3d dump/Dreamcast"    # models + textures + report for one disc
dcrip dump   "D:/roms/dreamcast" --out "D:/3d dump/Dreamcast"        # the whole library, README + matrix
```

The Dreamcast module walks the GD-ROM's ISO 9660 tree (raw 2352-byte sectors, absolute
LBAs), expands AFS archives and PRS-compressed files, and turns every Ninja model
(NJTL + NJCM chunk models with weighted vertex-cache skinning and cached polygon lists,
NJBM basic models) into a skinned glTF, with NMDM motions as clips and PVR/PVM textures
(twiddled, VQ, small VQ, mipmapped; ARGB1555/RGB565/ARGB4444/YUV422) as PNGs. Output,
`report.html`, `gcrip serve`/`gcrip blend` and the Blender add-on are shared with gcrip.
Phantasy Star Online: 334 models, 0 failures, 1,560 texture files in 42 s.

### Level recompilation (Wind Waker)

```
gcrip stage out/rip/GZLE01 --list           # what's on the disc (156 stages)
gcrip stage out/rip/GZLE01 M_NewD2          # one stage -> stages/M_NewD2/M_NewD2.gltf
gcrip stage out/rip/GZLE01 sea --rooms 44   # just Outset Island
gcrip stage out/rip/GZLE01 --all            # every stage + stages/stage_matrix.md
```

`gcrip stage` reads the game's own placement files (`stage.dzs` / `room.dzr`) from the disc,
places the room geometry with the MULT room table, resolves every placed actor
(ACTR/SCOB/DOOR/TRES... chunks) to a model the rip already exported, and merges everything
into **one level glTF**: instances share meshes, node transforms are baked flat (no
armatures - the whole Great Sea imports into Blender in ~30 s; pass `--rigs` to keep
skeletons instead), treasure chests pick the right box variant from their parameters, and
doors come from the stage's own archive. Import it straight into Blender (or drop the
packed `.glb` into Godot/Unity/Unreal). Actor names map to archives via
a table mined from [noclip.website](https://noclip.website)'s Wind Waker code (which credits
Winditor's ActorDatabase); vegetation drawn from display lists inside the game executable and
invisible logic actors (switches, tags, triggers) are skipped and counted in the per-stage
report. Whole-disc numbers: **156/156 stages build, 8,428 actors placed, ~3% unresolved**.
The entire Great Sea - all 49 islands with their props - comes out as a single 28 MB scene.

### Walk the levels in Godot

```
gcrip godot out/rip/GZLE01 M_NewD2 sea_r44   # -> out/rip/GZLE01/godot/
```

Generates a ready-to-open **Godot 4** project from the recompiled stages. Each stage scene
has: the level as a self-contained `.glb`; **the game's own collision** (`room.dzb` parsed
per surface class - you walk on floors, not on lava, because lava/water/poison groups are
excluded from the solid mesh); **a playable, animated Link** (his real model with his real
`wait`/`walk`/`dash`/jump clips driving a third-person controller, trimmed from 594 clips to
a 0.5 MB player glb); and **working doors** - walk into a house door on Outset and the
interior stage loads with Link on its arrival spawn. Door destinations are not guessed: every
interior's own exit table names the spawn it returns to, and that spawn stands in front of
its door, so the graph is inverted from the game's own data (`SCLS` chunks). Open the folder
with Godot (godotengine.org, free/open source), press **F5** - WASD + mouse, Space to jump,
Shift to sprint. This is the engine-recompiler direction growing up: assets, placement,
collision and connectivity come from your disc; game behaviour (enemies, items, puzzles) is
original code layered on top.

## Status

- **Phase 0 - disc filesystem walker: done.** `.iso`/`.gcm` parsing, FST tree,
  Yaz0/Yay0, recursive RARC (`.arc`/`.szs`/`.szp`), embedded `.tgc` mini-discs (Zelda
  Collector's Edition's Wind Waker demo), format sniffing, manifest, tree, extract.
- **Static rip (J3D games): done.** BMD/BDL parser (INF1/VTX1/EVP1/DRW1/JNT1/SHP1/MAT3/TEX1),
  GX texture decoding (I4/I8/IA4/IA8/RGB565/RGB5A3/RGBA8/C4/C8/C14X2/CMPR), glTF 2.0 export
  with skins and named joints, dedupe by hash, report.html. This is "Strategy B" of the
  original plan pulled forward: for first-party GameCube titles it already delivers the
  whole point of the tool without needing Dolphin.
- Phase 1 - Dolphin fork geometry capture (for games with non-J3D/custom formats): not started
- Phase 2 - runtime naming correlation: not started (not needed for J3D games - names come from the disc)
- **Skeletal animation: done.** BCK clips (hermite keyframes, sampled at 30 fps) become glTF
  animations on the model's skeleton; texture-pattern (BTP) facial expressions become
  hidden switch meshes + `KHR_materials_variants` presets; recognised humanoid rigs carry
  Mixamo bone names. See below.
- Phase 3 extras - OBJ fallback: not started
- Phase 4 - audio via vgmstream: not started

### Animations

Every `.bck` clip whose joint count matches a model in the same archive is attached to that
model as a named glTF animation (`walk`, `wait`, `dasha`...). Archives that hold only
animations - Wind Waker's `LkAnm.arc`, Twilight Princess's `AlAnm.arc` and the many
`Demo*.arc` cutscene packs - are matched to the model they drive by joint count within the
same directory, ranked by shared expression materials, archive-name affinity
(`Kolin.arc` <- `Kolin1.arc`) and detail; the report lists which archives each model's clips
came from. Override a guess with `--anim-map LkAnm=Link`; cap the clip count with
`--max-anims 200`; skip animation entirely with `--no-anims`.

Clips are sampled per frame (30 fps by default, `--fps` to change) with LINEAR
interpolation, so they play in every glTF viewer. Each animation carries extras
`gcrip_loop`, `gcrip_frames`, `gcrip_fps`. In Blender each clip becomes an action / NLA
track on the armature (Wind Waker Link: 594 clips, Twilight Princess Link: 695 clips on each
tunic model - al/bl/ml/zl share one skeleton, so they share the clips).

### Faces, expressions, alternate meshes

Each J3D shape becomes its own object named after its material (`face`, `mouth`, `eyeL`...),
all sharing one armature. Two kinds of alternates are exported hidden
(`KHR_node_visibility`, honoured by three.js / most viewers; the Blender add-on hides them):

- **Alternate meshes** stacked on the same spot (Wind Waker's `eyeLdamA`, `mayuRdamB`...):
  parented under `<model>_variants`, extras `gcrip_variant_of`.
- **Texture switches** derived from the game's BTP texture-pattern animations: for every
  texture a BTP ever assigns to a face material, a hidden clone mesh `eyeL@eyeh.3`,
  `mouth@mouthS3TC.4` with that texture applied (extras `gcrip_variant_of`, `gcrip_texture`).
  Switching an expression is toggling visibility - the Blender add-on's panel does this
  with one click. The multi-material states the BTPs actually reach (`link_freez`,
  `talk#4`...) are also written as `KHR_materials_variants` presets (up to 256; Blender
  needs "Material Variants" enabled in the glTF add-on preferences to show them).

Because J3D expressions are texture swaps and mesh swaps, there are no morph targets /
shape keys in the source data to export.

### Retargeting-friendly skeletons (Mixamo names)

`gcrip/rig.py` recognises the humanoid core of a J3D skeleton - hips, spine chain, neck,
head, shoulders, arms, hands, legs, feet, toes - from Nintendo's naming conventions
(`LarmA_jnt`, `armL1`, `udeL2`, `arm_L1`, `momoL`...) plus hierarchy, and maps it to the
Mixamo convention (`mixamorig:Hips`, `mixamorig:LeftForeArm`...). Wind Waker Link maps 22/22
core bones, Twilight Princess Link 21 (no Spine2), Zelda/Midna/NPCs 17-21.

- default: original joint names, Mixamo name stored in node extras `gcrip_std_bone`
  (imported as a bone custom property; the add-on renames from it)
- `gcrip rip ... --bone-names mixamo`: nodes are named `mixamorig:*` directly, original
  name in extras `gcrip_joint`

Both games' characters are stored in a T-pose, so Mixamo / other T-pose animation
libraries retarget cleanly by bone name (Rokoko, Auto-Rig Pro, Mixamo-to-Rigify... any
name-based retargeter). Fingers, hair, clothing and weapon bones keep their original names.

### Known limitations of the static rip

- Materials are simplified to one base-color texture per material (chosen as the first TEV
  stage that samples through a real UV set). One common two-layer case is baked: a second
  texture sampled through the same UV set (Wind Waker's eye-white shape x pupil texture,
  through its SRT texture matrix) is multiplied into a `<base>_x_<detail>.png` composite so
  eyes come out right. Other TEV multi-texturing, env maps and toon ramps are not reproduced.
- Old `bmd2` files with a `MAT2` section export geometry and textures with placeholder materials.
- Only mip level 0 is exported. Vertex colors are exported as COLOR_0.
- Animation-only archives are matched to models heuristically (see Animations); check the
  report's "from ..." note and use `--anim-map` if a guess is wrong. BTK (UV scroll), BRK
  (color) and BVA (visibility) clips are not exported.

**Run on all 638 discs of a full GameCube library: 12 games rip (8,493 models, 34,836 clips, 0 failures),
256 more yield their standalone textures, 0 discs error - see [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)**
for the per-game matrix and the engine guesses for the rest.

See [docs/PIPELINE.md](docs/PIPELINE.md) for diagrams of the whole pipeline (disc walk → J3D → glTF →
animation matching → Blender) and the list of heuristics with where to look when one is wrong.
`tools/reel/make_reel.py` rebuilds the demo reel from a rip with Blender headless.

## Install

```
pip install -e ".[dev]"
```

Python 3.10+, numpy is the only runtime dependency.

## Usage

```
gcrip info  game.iso                     # header: game ID, title, region, FST/DOL offsets
gcrip tree  game.iso                     # full directory tree, archives expanded, formats tagged
gcrip tree  game.iso --kinds model,texture --depth 4
gcrip manifest game.iso -o disc_manifest.json
gcrip tree  disc_manifest.json           # re-render without re-walking the disc
gcrip extract game.iso out/              # dump every file, archives expanded and decompressed
```

RVZ/GCZ/WIA images are detected but not read; convert with
`DolphinTool convert -i game.rvz -o game.iso -f iso` first.

```
gcrip rip game.iso out/                        # everything: models, textures, animations, report
gcrip rip game.iso out/ --filter res/Object/L  # only paths containing this substring
gcrip rip game.iso out/ --bone-names mixamo    # name humanoid bones mixamorig:* directly
gcrip rip game.iso out/ --anim-map LkAnm=Link  # force an animation archive onto a model archive
gcrip rip game.iso out/ --max-anims 100        # lighter files: at most 100 clips per model
gcrip rip game.iso out/ --no-anims             # static models only
gcrip survey D:/roms/gamecube -o out/survey    # whole library: which engine each disc uses (~2 s/disc)
gcrip dump  D:/roms/gamecube --out "D:/3d dump/GameCube"   # every disc: rip + every extra, README + matrix
gcrip dump  game.iso --out "D:/3d dump/GameCube" --blend    # one disc, plus a .blend per model
gcrip dump  D:/roms/gamecube --survey out/survey/survey.jsonl --engine J3D --out out/rip   # J3D discs only
gcrip serve out/GZLE01                         # report with Open-in-Blender buttons
gcrip blend out/GZLE01                         # .blend asset library (needs Blender)
gcrip stage out/GZLE01 M_NewD2                 # recompile a Wind Waker level into one glTF
gcrip stage out/GZLE01 --all                   # every stage + stage_matrix.md
gcrip godot out/GZLE01 [stages...]             # playable Godot 4 project from the stages
```

### Manifest layout

Paths mirror Dolphin's extraction convention: `sys/` (boot.bin, bi2.bin,
apploader.img, main.dol, fst.bin) and `files/<FST path>`. Files inside archives
get the archive path as a prefix, e.g. `files/map/stage1.szs/kuri/model.bmd`.

Each file entry has `path`, `size`, `sha1`, `kind`/`fmt`, and:

- `disc_offset` - absolute offset in the image, only when the bytes literally
  live there (top-level files, and files inside *uncompressed* archives).
- `container` / `offset` - for nested files, the parent archive and offset
  within its decompressed contents.
- `compression`, `decompressed_size`, `sha1_decompressed` - when the file is
  stored Yaz0/Yay0-compressed; `kind`/`fmt` then describe the *payload*.

## Development

```
pytest
ruff check . && ruff format .
```
