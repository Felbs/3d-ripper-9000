# Silicon Dreams / Gusto "Proteus" SDASSETF asset files (cracked 2026-09-05 on Freestyle Street Soccer, GUVE51)

`gcrip/formats/sdasset.py` + `gcrip/plugins/sdasset.py` (`NAME = "sdasset"`), tests in
`tests/test_sdasset.py`.  Only one library disc ships the format (manifest scan over all
636 discs: GUVE51 alone has `*_models.ast` / `*_textures.ast`, 349 of its 579 `.ast`).
Gusto Games was the Silicon Dreams team; the exporter tag inside every model is
`ProteusMaxExporter v1.11`, the effect paths are `\\Proteus\TEXTURED` etc.

## Why it was garbage in the audit

`.ast` is Nintendo's audio-stream extension, so `gcrip/classify.py` called every one of
these files `audio/AST` by extension, nothing claimed them, and the `gx` fallback scanned
the little-endian float buffers into "meshes": `thestreet-kai_models.gltf` scored 88 verts /
**2 unique positions** / 99.7% degenerate edges, `bmxcrew_models` the same.  (The other
GUVE51 garbage - `.fab` animation tables, `.bvd`, `.spd`, `sys/fst.bin` - is scanner noise
of a different kind and is handled on the scanner side, not here.)  The classifier now
recognises both magics as `model/SDASSET`; the plugin detects on the magic, never on the
extension, so Nintendo `STRM` audio still classifies and routes as before.

## File layout

Magic is two u32 words: `SDASSETF` in the big-endian texture files, `SADSFTES` in the
little-endian model files - and every chunk tag is byte-swapped the same way (`LRTM` on
disk is `MTRL`, `HSEM` is `MESH`, `\0LDM` is `MDL`).  Header: magic(8), u32 version (1),
u32 top-level chunk count.  A team file is several complete files concatenated:
`thestreet-kai_models.ast` (1,640,216 B) = `Ryu_Models.ast` (386,212) + Shuko (409,784) +
Takashi (418,320) + Tetsuo (425,900) byte for byte, so the reader loops on the magic.

Chunk header: `tag, u32 version, u32 arg, u32 size` (16 bytes).

- **Containers** (`MTRL`, `SKEL`, `MDL`, `BMAP`, `LGHT`; in LE files also anything whose
  version word has a non-zero top byte - 0x09 / 0x06 / 0x0F): NUL-terminated name padded
  to 4, then `arg` bytes of body, then `size` bytes of children.  Body size counts from
  after the name: `MTRL` is always 0x28, `MDL` 0x14 or 0x34 (with a shadow path), `SKEL`
  0xA28 for 32 bones, `BMAP` 0x1C.
- **Leaves**: `arg` is the chunk's index (DATA 1..n, MESH 1..n, WDGE 1..n, LOD 1..4),
  `size` the payload.

Identity: the walk tiles every cached file exactly to EOF - Ryu (95 chunks), the team file
(4 segments), the crowd files, `intro_models.AST` (version-3 MESH), the stadium
`BasketBallCourt_Models.ast` (1,004 chunks, 66 `MDL`, 185 `MESH`, 4 `LGHT`) and all
four texture files (7 / 25 / 79 / 1 `BMAP`).  The last chunk of a model is `INFO`
(exporter date, user, "Stripifier: Stripe / Force Single Strip: False / Preserve Winding
Order: True / Max bones per mesh 32, per prim 16, per vert 4").

### Materials
`MTRL name > EFCT*`.  `EFCT` payload: effect path (`\\Proteus\TEXTURED`, `\\Proteus\SHADOW`
for the `1LightingMap` lightmap, `\\Proteus\SPECULARMASKDUP`), u32, texture name.  A
material's picture is its TEXTURED effect's texture.  Players carry each material twice
(flags 0x09 and 0x06 - the second with a 0.6 in the body); the first with a texture wins.

### Skeleton
`SKEL "Player"`: u32 bones (32 players, 14 crowd), u32 names blob size, NUL-separated
names (Pelvis, PSpine, SSpine1.., LThigh, LCalf, LFoot, LBShirt...), i32 parent per bone
(-1 root), f32[16] per bone = **row-vector world bind matrix** (translation in row 3;
`Pelvis` at z 13.7, spine at 27.8 / 42.7 - the model is Z-up), then one f32 per bone.
The reader transposes to column form and derives parent-relative T / quaternion / S for
`Scene.joints`; the glTF exporter rebuilds the inverse binds from that rest pose.

### Geometry (`MDL name > BND, DATA*, WGHT*, WDGE*, MESH*, LOD*, INFO`)
- `DATA`: u32, u32 id, u32 stride, u32 count, u8 attribute codes terminated by 0x80
  (1 = position f32x3, 2 = normal f32x3, 3 = colour u8x4, 4 = uv f32x2; players are
  `01 02 04 04` stride 40, stadiums `01 02 03 04` stride 36, props `01 02 04` stride 32),
  8 pad, `count` interleaved vertices.  Then u32 block count and, per **skinning block**:
  u32 n, u32 bone palette[n], u32 nv, nv vertices continuing the buffer's numbering,
  followed by `nv x (n-1)` bone-space copies of the same stride (the palette-skinning
  scratch data, all zero for unused influences).  The true vertex count is the matching
  `WGHT` count (645 = 645 + 0 blocks; 548 = 397 + 88 + 63; 128 = 49 + 79).  One block
  (every player's 79-vertex mouth) carries 77 x 4 copies instead of 79 x 4, so the next
  header is searched for rather than computed when the arithmetic does not land on one.
- `WGHT`: u32 count, per vertex `u32 n, u32 bone[n], f32 weight[n]` (1-3 bones).
- `WDGE`: u32 vertex count, u32 n, u32[n] - the exporter's pre-strip wedge order; count
  equals the mesh's index count but it is not needed to draw.
- `MESH` version 5: name, f32[6] bbox, u32 id, u32 index count, u32 strip count, 0, 0,
  u32, u32, u32 **data id** (= the DATA chunk index), 4 x (u32 attribute word, u32)
  where byte 2 of the word is the index width (1 = u8, 2 = u16, 4 = u32 on version-3
  files), 96 reserved bytes, then strips: `u32 n, n x (one index per attribute) padded
  to 4, u32 trailer` (trailer 1 marks the last strip of a run, 0 otherwise).  Version 3
  (`intro_models.AST`, crowd) puts id / counts before the bbox and 0, 0, data id after
  it.  The per-attribute indices are always identical - one interleaved buffer.  Winding:
  plain alternating strip, first triangle as stored - checked against the authored
  normals, 95-100% of faces agree on every player and stadium mesh.
- `LOD`: f32 distance, skeleton name, u32 n, u32 mesh ids, per-mesh counts.  Players
  have four (100 / 75 / 50 / 25); the **smallest distance is the full-detail set**
  (Ryu_Top: 231 triangles at 100, 770 at 25).  Stadium models have one.

### Textures (`BMAP name > IMAG`)
Body: u16 w, h, w, h, u32 0, then `log2 w, log2 h, 1, compressed(7|0)`, then
`bits-per-pixel, kind, 0, 0`, u32 0, u32 0x10000.  `IMAG` payload is `GC\0\0` + GX-tiled
pixels: CMPR when the compressed byte is 7 (all player skins, 128x128 = 8 KB), else by
depth: 4 = I4, 8 = I8 (stadium walls are greyscale I8 - verified by eye, the graffiti
wall and fence tile cleanly, IA4 does not), 32 = RGBA8 (the 256x256 `1LightingMap`),
16 = RGB5A3 (unseen).  Decoded with `gcrip/formats/gx_texture.py`.

## Plugin behaviour
One Scene per file segment (a team file yields four player scenes, named by their `MDL`);
each `MDL`'s full-detail LOD meshes become primitives with positions / normals / uvs /
colours, materials named after the mesh, textures bound from every `*texture*.ast` in the
same directory (home kit before away), matched case-insensitively (`Ryu_Trainers` in the
player's own file, `Ryu_trainers` in the team file).  Skinned meshes carry JOINTS/WEIGHTS
from `WGHT` over the `SKEL` joints.  Texture files export as textures-only scenes.
Coordinates are kept as authored (Z-up, players ~200 units tall).

## Before / after (same source files, `gcrip.quality`)

| model | before | after |
|---|---|---|
| `thestreet-kai_models` (team) | 88 verts / 242 tris, 2 unique positions, 99.7% degenerate, **garbage** | 4 scenes: Ryu 3,612 tris / 2,422 verts / 32 joints / 6 textures; Shuko 3,795; Takashi 3,894; Tetsuo 3,969 - 0.03-0.17% degenerate, median edge 1.1-1.3% of the diagonal, **ok** |
| `Ryu_Models` | (not exported - unclaimed) | 3,612 tris, skinned, 6 CMPR textures, **ok** |
| `BasketBallCourt_Models` | (not exported) | 66 models, 185 meshes, 13,985 tris, 74 textures bound, **ok** |
| `intro_models` (nike_ball) | (not exported) | 180 tris, textured, **ok** |

Renders (`scratchpad/hishare/renders/GUVE51_*_after.png`): the player wireframe is a
T-posed footballer with head, hands and shoes in the XZ view; the stadium is a 20,000-unit
sky dome over a court with centre markings, fences, lamp posts and a BMX kid.

## Open
- Crowd `Skins/crowd/<team>/<team>_models.ast` (7 concatenated single-strip models, the
  "Force Single Strip" export) come out with ~50% of faces wound against their normals -
  the strip bridges must use an odd number of repeats; per-strip crowd files (`01_models.AST`)
  are fine.  Winding only; geometry is right.
- The 128 bytes per vertex of bone-space copies, the second MTRL variant (0x06 flags, 0.6),
  `LGHT` bodies and the per-mesh counts after the LOD id list are skipped, not decoded.
- Animations (`Anims/**/*.fab`, `.bvd`) are a separate format; `.fab` looks like float
  keyframe tables and is what the scanner turns into `[0.12, y, 0.12]` "meshes".
