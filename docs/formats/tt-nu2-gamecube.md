# Traveller's Tales NU2 on GameCube (LEGO Star Wars 1/2, Crash: Wrath of Cortex, Finding Nemo, Super Monkey Ball Adventure, Narnia, Bionicle Heroes)

Status 2026-08-29 (evening): two GameCube generations.  **LSW1-era** (LEGO Star Wars 1,
Bionicle Heroes `.csc`, some Finding Nemo `.nus`): little-endian NU20 chunk files whose OBJ0
holds the tagged `03 01 00 01` vertex stream - decoded in `gcrip/formats/nu2.py` (see the
"LSW1 stream" section below).  **LSW2-era** (LEGO Star Wars II `.csc` 480 files / `.chg`
258 characters, Narnia `.csc` 52 levels+chars / `.chg` 94): big-endian chunk files with
reversed tags (`02UN`, `LBTN`, `0TST`, `00SM`, `PSID`) whose geometry is a `DISP` display
program - decoded in `gcrip/formats/ttdisp.py` + `gcrip/plugins/ttdisp.py`:

## DISP display programs (LSW2 / Narnia `.csc`, `.chg`)

- Every u32 pointer inside DISP is **self-relative** (target = field address + value).
  Payload header words: 0 -> source path string, 2 -> command stream, 4 = draw-table count,
  5 -> draw table; the rest are node / instance tables.
- Command stream: 8-byte records `u8 op | u8 | u16 | u32 arg`.  `0x85` block header (arg
  = link to the next block), `0x80` material (pointer into the `MS00` chunk or the `.chg`
  material table; the target is record start + 8 in `.csc`, + 4 in `.chg`), `0x8b`, `0x84`,
  `0x87` state, `0x83` node (pointer to a 0x64-byte record = two 3x4 f32 matrices, rotation
  rows + translation in column 3, column-vector convention), `0x82` draw (pointer to a mesh
  descriptor), `0x8e` end.  Materials declared before the draws are *not* the draws'
  materials: the draw table `(count, A -> (material index, x) pairs, B -> command indices)`
  says which material each `0x82` (at stream + id * 8) uses.
- Mesh descriptor (0x60 bytes): `u16 0 | u16 fmt | u16 vertex count | .. | [4] normals s8[3]
  (/64) | [5] uvs u8[2] (/255) | [6] colours RGBA8 | [8] display list (self-relative) | [9]
  DL byte size | .. [16..18] f32 = node translation copy | [19] positions s16[3] (/1024;
  level chunks are 64-unit cubes spanning the full s16 range)`.  `fmt` is a GX-style vertex
  descriptor: bit 14 matrix-index u8, bits 0/3 position index u8/u16, bits 6/8 normal index
  u8/u16, bit 2 colour index u8, bits 1/4 uv index u8/u16 - one index per enabled attribute
  per strip row in that order (bits 7, 12, 13 add no bytes).  Display lists are raw GX
  (`0x98` strips, `0x90`, `0xa0`) zero-padded to 32 bytes.  19 distinct fmts seen across
  the samples, all consistent.
- Materials: LEGO Star Wars II records (0x124 bytes in MS00, 0x130 in `.chg`): texture
  index at word 62 from the 0x80 target (-1 = untextured), diffuse f32[3] at 53-55.  Narnia
  records (0x11c / 0x120): word 60 and 51-53.  LEGO brick colours are per-mesh RGBA vertex
  colours (`[6]`), e.g. tan (251,239,159).
- Textures: `TST0`: `u32 count | u32 0 | entries of 0x3c (u32 | u16 w | u16 h | u16 GX fmt
  | u16 mips | u32 pixels, offset relative to its own field)`; CI8 (fmt 9) palettes (RGB5A3,
  0x200 bytes) follow the pixels.  `.chg`: header `u32 size | u32 2 | u32 ntex | u32 texture
  table | u32 nmat | u32 material table | u32 nbones | u32 bone records (0x60: 4x4 local,
  name ptr +0x4c, parent = top byte of +0x50, 0xff root) | u32 bind 4x4 | u32 inverse 4x4 |
  0 | u32 root | u32 names | .. | u32 nlists | u32 lists`; LSW2 entries are inline
  (`u32 | u32 0 | w h fmt mips | offset`, pixels follow, next entry after them), Narnia's
  table is a list of absolute entry offsets.
- `.chg` skeleton binding: list 1 of the lists table has one pointer per bone -> 12-byte
  triplet whose third word is a 0xd0-byte node record inside DISP; node + 0xb0 links (self-
  relative) to a draw-table entry whose B ids are the bone's draws.  Bone-space vertices go
  through the bind matrix (row-vector: `p @ M[:3,:3] + M[3,:3]`).  LSW2 minifigs: 21 of 65
  draws belong to bones, the other 44 (identity nodes without parents) are the break-apart
  pieces and are skipped.  Narnia `.chg` (29-bone rhino, 24-bone ankle slicer) uses a
  different wrapper (fmt bit 14 matrix indices per vertex, bind-pose positions) - exported
  static, skinning open.
- Verified: LEGO desert skiff (44 draws, 4.3k tris, 6 colour materials), BattleDroid rigged
  (14 bones), Narnia fox (4.4k tris, CI8 fur texture), rhino, ankle slicer, Narnia
  BonusFollow level (243 draws, 16 textures), LSW2 E5VehicleBonus level (527 draws, 132k
  tris, 23 textures).
- Disc census 2026-08-29 through `plugins/ttdisp.py`: LEGO Star Wars II 687 files -> 682 scenes
  (476 `.csc`, 206 `.chg`, 47 rigged), 18.2 M triangles, 6,737 textures, 0 failures (48 s);
  Narnia 145 files -> 145 scenes, 4.2 M triangles, 2,295 textures, 0 failures.
- `.fpk` (LSW2, LE) / `.cpk` (Narnia, BE): `magic 0x12345678 | u32 count | u32 total | u32
  hash | 0 | 0 | 28-byte entries (name offset, data offset, size, 0x10, 0 x3) | names`;
  members are `.ca3` animations (ANI4/ANI5 tags, open).
- Open: `.ca3`/`.can` animations, Narnia `.cct` (cutscene anim), `.cc2`, `.ctr` terrain
  heightfields?, `.obj` (5 MB Wavefront text = collision); `.hgo` / `.nus` of Crash / Nemo are
  ripped (see below).

LSW1 `.nus` (24 files, 223 MB, the big level scenes): chunk sizes are stored NEGATED
(`GSC0 | -size`, `TST0 | -313940`), chunks VERS, NTBL, NAME, NAMS, TST0, MS0X x3, PLGT (484
KB), LDIR, GST0 (580 KB), BNDS, INST, SPEC, SST0, DYNO. PLGT and GST0 hold PC-style 32-byte
vertex records (`f32 xyz | RGBA 7f7f7fff | f32 nx ny nz | u32 0` in PLGT; `f32 xyz | f32 nrm
| RGBA | f32 uv` in GST0, header `u32 1 | 0 x5 | u32 0x12 | 0 | u32 vertex count`) with a small
index / strip table at the chunk end - not decoded; the same level geometry also exists as the
decoded stream in the level's `.gsc`, so `.nus` is not needed for a first rip.
Finding Nemo / Crash WoC `.hgo` / `.nus` - CRACKED 2026-08-29 (`gcrip/formats/hgo.py`,
`plugins/hgo.py`): the NU2 chunk tree with reversed 4CC tags and big-endian sizes (`FOGH` =
HGOF, `0CSG` = GSC0, `LBTN` = NTBL, `0TST` = TST0 > `0HST` TSH0 count + `0MXT` TXM0 per
texture, `00SM` MS00 (Crash) / `30SM` MS03 (Nemo), `0OGH` HGO0, `0TSG` GST0, `TSNI` INST,
`CEPS` SPEC, `0TSS` SST0).  TXM0 = `u32 code | u32 w | u32 h | u32 bytes | GX pixels` with
0x80 = CMPR and 0x81 = RGB5A3 (verified visually on the narwhal eye / skin).  Materials are
84-byte records: `s32 | u32 flags | u32 x3 | f32 rgb | u32 x4 | f32 x2 | s32 texture (-1 none)`
(same offsets in MS00 and MS03).  HGO0 = `u8 node count | u8` + variable node records (4x4
f32 local matrix, flag bytes, optional bind matrix; NTBL names in node order) followed by the
meshes; GST0 = `u32 mesh count` + meshes.  A mesh is `u32 1 | u32 x4 | u32 blocks | u32
material | u32 vertex count | vertices | index groups | skin`, its further blocks `u32 0 |
u32 0 | u32 material | count ...` (NarWhal: one mesh of 10 blocks, one per material; Bruce:
2 meshes, 139 blocks).  Vertices are big-endian `f32 xyz | f32 normal | RGBA8 | [f32 uv]`
(28 bytes when the material has no texture, 36 with uv) in model space; index groups `u32 |
u32 | u32 prim (5 = triangle list, Crash; 6 = strip, Nemo) | u32 count | u16 indices` 4-aligned;
a skinned mesh ends with `u16 0x0101` + per-vertex `f32 w0 w1 w2 | u8 bone[4]` (4th weight
implied).  INST = `u32 count` + 80-byte `f32 4x4 (row vectors, translation in row 3) | u32 x4`,
one per GST0 mesh in order (alphbet.nus: 36 meshes, 36 placements -> the letter grid).  The
parser finds meshes by scanning for plausible vertex blocks (unit normals) so the node
records are not walked; joints are exported flat with identity binds (vertices are already in
the bind pose).  Census: Crash Bandicoot: 244 of 250 `.hgo` characters (267,839 triangles, 157 skinned, 2933 of 4146 materials textured), 66 of 74 `.nus` levels (4,137,424 triangles, 2585 of 3030 materials textured), 387 s; Finding Nemo: 57 of 71 `.hgo` characters (78,145 triangles, 50 skinned, 310 of 386 materials textured), 3 of 54 `.nus` levels (135,940 triangles, 82 of 112 materials textured), 729 s.
Open: node hierarchy / bind matrices (for animation), transforms of unskinned `.hgo` parts,
SPEC records (35 x 80 bytes, named objects), `.ter` terrain (Crash 41 files / 19 MB), `.ani`.

Earlier mapping (kept for the containers): Samples: LEGO Star Wars 1 (USA)
`files/Chars/GunganBongo/gunganbongo.{gsc,nus,ghg}`, `files/Levels/.../PodRace_A/a.gsc`.

## Files on the LSW1 disc (6219 files)

`.nus` levels 223 MB (24), `.gsc` characters/level chunks (NU20), `.ghg` (2, a different
table-based layout), `.csc` cutscene scenes 169 MB (171, "02UN" = NU20 magic stored
little-endian), `.cct` cutscene animation (114), `.gcm` = AUDIO (cutscene streams, not
models), `.an3`/`.ca3`/`.can` animations, `.scp` scripts.

## NU20 chunk files (.gsc, .csc) - LITTLE-endian even on GameCube

Header `"NU20" | i32 size (negative/odd on GC) | u32 version 6 | u32 0`, then chunks
`4cc | u32 LE size (including the 8-byte header)`: NTBL (name table: u32 size, u32 count,
C strings), TST0 (texture set: u32 count, then u32-sized texture entries `u16 w, u16 h,
u8 fmt ...` with GX pixel data), MS00 (materials, 0x20b0 bytes for 18), OBJ0 (objects:
counts at +0x14 (0x12 = 18 meshes?), +0x34 (0x7b), 0x1c8, 0x315, then mesh records
with LE f32 vertex buffers of 16 bytes: xyz + packed normal/colour, and u16 index
buffers - PC-style DirectX layouts, no GX display lists), INST (instances), SPEC, SST0,
BNDS (bounds), TAS0, IABL, INID, ALIB (levels).

`.nus` = `"GSC0" | u32 | "VERS" | u32 0x38 ...` outer container around the same chunks.

`.ghg` (GC) = big-endian offset-table layout: `u32 size | u32 2 | u32 texture count |
u32 texture table | u32 material count | u32 material table | u32 matrix count | u32
matrices | u32 bind matrices | u32 inverse | 0 | u32 root node` ...; textures `u32 0,
u16 w, u16 h, u16 GX fmt (0xe = CMPR), u16 mips, u32 pixel offset`; scene nodes with
names (`defaultLayer`, `TT1_HighRes`) and 0xd0-byte mesh headers (two 4x4 matrices,
bbox, `u32 0xcdcdcdcd` marker).

## Open

- OBJ0 mesh record layout (vertex stride/format flags, index buffer, material index) -
  reverse from the PC LSW1 NU2 documentation (fandom wiki is unreachable from here);
- whether the later games (LSW2, Bionicle Heroes = "NU2 v2"?) share the layout.

### Finding Nemo levels (2026-08-29 evening)

The Nemo `.nus` GST0 meshes drop the normals: vertices are `f32 xyz | RGBA8 | f32 uv` (24
bytes) or `f32 xyz | RGBA8` (16), and instead of the `u32 | u32 | u32 prim | u32 count | u16
indices` groups they end with a raw GX display list: a `u32 size | u8` prelude, CP array-base
and stride loads (`08 a0/a2/a4 <u32 base>`, `08 b0/b2/b4 <u32 24>`) that name the indexed
attributes, then primitives (`98` strip) whose rows carry one index per attribute - u8 while
the array fits in a byte, u16 above 255 vertices.  `formats/hgo.py` tries both widths and
keeps the parse that consumes more of the list.  luxo_04.nus went from nothing to 5,248
triangles, jelly.nus to 2,154 on a 3 MB slice.  Open: strips that index across the blocks of
one mesh are still skipped (the CP array bases would give the offset).
