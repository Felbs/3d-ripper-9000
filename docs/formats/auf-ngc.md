# 007: Agent Under Fire - `maps/*.ngc` (EA Redwood Shores, a Quake III derivative) - 2026-09-03

38 map files, 6-9 MB each, 273 MB - the whole level content of the disc (the `.gsf` beside
them are sound).  `Bond.elf` ships a **symtab** (17,636 symbols) and the engine is id Tech 3
with EA's additions: `BSP_Init`, `BSP_InitBrushes`, `R_InitSurfaces`, `CM_TraceBrushesAndPatches`,
`C_Q3Object3D`, `ME_LoadTIKIfile` (Ritual's TIKI model format), `NGCObject3D` with
`NGC_EntVtxPos_s / NGC_EntTriStrip_s / NGC_EntGeomSection_s` structs and a pointer-fixup
loader (`RecoverPointer<T>`, `FixupNGCModelData`).

## The chunk stream (`RSRC_Load`, `GetChunkHeader`, `ReadChunkData`, `SkipChunkData`)

A file is chunks at 32-byte alignment, each a 32-byte header then its bytes:

    +0   char tag[8]     stored reversed: b".bla_dns" is "snd_alb"
    +8   u32 size        unpacked bytes
    +12  u32
    +16  u32 compressed  1 = BOA
    +20  u32
    +24  u32 stored      bytes on disc (the compressed size)
    +28  u32 unpacked

`ReadChunkData` mallocs `unpacked + 0x40`, reads `stored` bytes to the end of that buffer and
`BOA_ExpandInplace`s them to the front.  **BOA** is a byte LZ: a flags byte, LSB first; a set
bit copies one literal; a clear bit reads `b0, b1` and copies `(b0 & 0xf) + 2` bytes from
`out - ((b0 >> 4) | (b1 << 4))` (a 12-bit distance; 0 means nothing).  Scratchpad `bond/auf.py`
has it and reproduces every chunk's unpacked size.

`dm1.ngc`: `snd_alb` (14 KB), `sndbank` (2.1 MB), **`restxtrs`** (3.2 MB - the textures:
`f32 1.2, u32 358, u32 16, u32 0x5b0`, then what looks like a hash table), **`shaders`**
(31 KB, `SHDR_Init`), **`bspfile`** (724 KB, uncompressed - itself a chunk stream), `shockprf`,
**`restable`** (2.7 MB - `FS_UseResourceTable`: the models, animations and other resources the
level names; `u32 0x370` then `(offset, size, hash)` triples).

`bspfile`'s chunks are the Quake III lumps by other names: `bspinfo` (32 B), `planes`,
`brushsds`, `brushes`, `patches`, `leafsrfs`, `leafbrsh`, `bspleavs`, `bspnodes`, `visareas`,
`areaprtl`, `visdata`, `entities` (the Q3 entity text, 15 KB - `"_color"`, `classname`,
`model "*N"` and TIKI references, i.e. the placements), `ligtmaps` (328 KB: `f32 1.2, u32 5,
0, 16, u32 6, u16 128, u16 128 ...` - five 128x128 lightmaps), **`ngcsurfs`** (442 KB: `f32
1.15, 0, u32 240, ...` - the GX world surfaces), `bmodels` (1.5 KB, 48-byte brush models with
bounds), `entlight`.

## Where the models are

`FixupModelData__11NGCObject3D(hdr)`: the model's word 0 `>> 20 & 0x4ff == 0x484` is the
magic check, byte 7 the header offset, and at `data + 8 + offset` sits a `C_Object3D` header
(`FixupModelData__10C_Object3D`) whose +0x80 points at the NGC block that
`FixupNGCModelData` relocates: `(count, ptr)` pairs from +0x30 - positions +0x34, normals
+0x3c, ST +0x44, `NGC_EntVtx` +0x4c, u16 array +0x54, u8 array +0x5c, tri strips +0x64,
matrix map +0x6c, geom groups +0x74, geom sections +0x7c (16 B, count at +0x80: owner ptr,
shader id -> `SHDR_LookupID`), morph deltas / vertices / groups +0x84 / +0x8c / +0x94.  The
models live in `restable`.

## Next

`R_InitSurfaces` (572 B) for `ngcsurfs`, `RSRC_InitStaticTextures` + `TexMgr_AddTexture` for
`restxtrs`, `FS_UseResourceTable` for `restable`, then `FixupNGCModelData`'s structs (the
`RecoverPointer<T>` functions are 16 bytes each: `ptr ? base + ptr : 0`).  Everything Nothing
(2004) and From Russia with Love (2005) are the same studio; their `.ngc` / `.exa` may be the
next versions of this.

## The world geometry reads (2026-09-03, later)

`ngcsurfs` (`R_InitSurfaces`, `R_DrawSurf`, `R_AddVisibleLeaves`): `f32 1.15` then `(ptr,
count)` pairs at +8 - vertices (+8, 14 bytes each), strip indices (+0x10, `u8`), surfaces
(+0x18, 28 bytes), surface groups (+0x20, 0x70 bytes), shader ids (+0x28, `u32`, resolved by
`SHDR_LookupID`), a pointer table (+0x30), three more arrays, and **a 3x4 world matrix at
+0xc0** that `R_InitVtxTForm` loads as the position matrix.  The GX vertex format
(`R_InitVtxDesc`'s tables at `0x80261ca0` / `0x80261cc0`) is `POS s16 frac 0, TEX0 s16 frac
8, TEX1 s16 frac 15`, all index8, so a 14-byte vertex is `s16 x, y, z, s16 s, t, s16 lm_s,
lm_t` and world position = `M * (x, y, z)`; a surface (28 bytes) is `u8 type (0 strip, else
patch), u8 lightmap, u16 0x400, u16 shader index, u8 4, u8 vertices, u32 0, ptr vertex array,
u16 first index, u16, u16 0x7fff, u16, u32` and draws one `GX_TRIANGLESTRIP` of `vertices`
`u8` indices from the index array at `first`.  `dm1.ngc`: 4,039 strips, 10,223 triangles,
an octagonal deathmatch arena spanning -2016..1136 x -448..1456 x -128..768 (scratchpad
`bond/auf.py::world`, rendered).  The shader index goes into the `shaders` chunk (`f32
0.945, u32 92 shaders, (count, offset) x 5`: 16-byte shader records at +0x1b6c, stages at
+0x3ed0 ...) whose textures are `u32` ids into `restxtrs` (`f32 1.2, u32 358 ids, 16, 0x5b0`:
the id table then the texture headers at +0x5b0) - `SHDR_FixupShaderTable` (924 B) and
`SHDR_SetupStage` name the fields.  Not yet done: the shader -> texture id path, the texture
headers, patches (`R_DrawPatch`), `bmodels`, the entity placements and the `restable` models.

## Shipped: the world with its textures (2026-09-03, end of day)

`gcrip/formats/auf_ngc.py` + `gcrip/plugins/auf_ngc.py`.  The shader path closed the loop:
a surface's `u16` at +4 indexes the `shaders` chunk's 16-byte shader array (`SHDR_GetIDX`
is `base + idx * 16`), a shader's pointer at +0xc reaches its 20-byte body (`ptr stages, u8,
u8 stages`), a stage (20 bytes) carries a `u32` texture id at +4 (`0xccddccdd` is the
lightmap stage), and `restxtrs` maps ids to 68-byte headers - `u32 GX format, u16 width,
u16 height, u32, u32, u32 data offset, u32 bytes, ...` - whose pixels are already tiled for
the hardware (`gx_texture.decode`).  `dm1.ngc` binds 42 of its 43 shaders; `alp1_1.ngc`
(Alpine) is 17,412 triangles / 91 textures, `carrier1.ngc` 26,346 / 40.  Read against
`SHDR_FixupShaderTable` (the chunk's `(ptr, count)` pairs and which record fields are
pointers), `R_AddVisibleLeaves` (the sort key: `shader << 7 | lightmap`, `SHDR_GetIDX`,
`SHDR_SetupStage`, `R_DrawSurf`).

Not read: the bicubic patches (surface type != 0, `R_DrawPatch`), the lightmaps (the second
uv set is exported, the `ligtmaps` images are not), `bmodels` and the entity placements, and
the `restable` models (`NGCObject3D`) - the characters, weapons and props.  Wave 57 re-rips
the disc.

## The models read too (2026-09-04, small hours)

`restable` (`FS_UseResourceTable`): `u32 count, u32[3]`, then 16-byte entries `ptr name, ptr
data, u32 size, u32 hash` - 880 members on `dm1.ngc`: 380 `.gca` animations, 225 `.men`
effects, **124 `.gcm` models** (`models/actors/actorheads/*.gcm`, `models/weapons/*_view.gcm`,
props), UI, fonts, scripts.  A `.gcm` is the `NGCObject3D` image: word 0's bits 20..31 are
0x484 and byte 7 the header offset (`FixupModelData`), the `C_Object3D` header sits at
`8 + offset` with sub-block pointers at +0x74..+0x94 (each re-pointed to `block + 8 + byte 7`
by `FixupHeaderOff`), and +0x80 is the NGC block: a 3x4 matrix, then `(ptr, count)` pairs
from +0x34 - positions (`s16` x3, through the matrix), normals (`s8` x3 / 128), uvs (`s16`
x2 / 2048), 6-byte vertices (`u16` position / normal / uv indices), the `u16` index stream,
per-vertex matrix bytes, 8-byte strips (`u16 first, u16 count, u16 matrix bytes, u8, u8
slot`), the matrix map (`u8 bone, u8 slot`), 8-byte groups (`u16 first map, u16 maps, u16
first strip, u16 strips`) and 16-byte sections (`u32, u32 shader id, u16 first group, u16
groups, u16 triangles, u16 indices`) - the walk `R_DrawGeomSection` makes, with
`R_InitEntVtxDesc`'s formats (`POS s16 frac 0, NRM s8 frac 7, TEX0 s16 frac 11`).  The
section's shader id is looked up by hash in the `shaders` chunk (`SHDR_LookupID`) and binds
the same way as the world's.  The strips are wound the other way round from the world's
(0.63 signed agreement after the flip, 85% of triangles).  `dm1`: **all 124 models, 25,827
triangles**, the Frinesi shotgun and a thug's head render textured.  The bones (`BuildViewMatrixList`,
the per-vertex matrix bytes) are not applied - the vertices are the bind pose.
