# 007: Agent Under Fire - `maps/*.ngc` (EA Redwood Shores, a Quake III derivative) - in progress 2026-09-03

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
