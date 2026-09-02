# Sonic Team / Sega on GameCube: Sega PRS, SA2B chunk models, GVM/GVR textures, Shadow's ONE

Verified 2026-08-29. gcrip: `gcrip/formats/prs.py` (standard Sega PRS), `gcrip/formats/sa2b.py`
(big-endian Ninja chunk parser on top of dcrip's), `gcrip/formats/gvr.py`, `gcrip/plugins/segaprs.py`
(.prs container -> `payload.bin`), `gcrip/plugins/sa2b.py`, `gcrip/plugins/gvm.py`, `gcrip/formats/one.py`
(Shadow variant). Tests: test_sa2b.py, test_gvr.py.

## Sega PRS (standard)

Flag bits LSB-first from flag bytes: 1 = literal; 0,0 = short copy (length = 2 flag bits + 2,
offset = byte - 256); 0,1 = long copy (u16 LE: offset = (v >> 3) - 0x2000, length = (v & 7) + 2
or, when 0, next byte + 1); v == 0 ends the stream. Copies must use the absolute start
position (overlapping runs) - a negative-index copy loop is wrong for lengths > 1.
there was a second, duplicate PRS decoder in the Dreamcast module; the two were verified byte-identical (40 random inputs and a hand-assembled stream) and only gcrip's is kept now.

## Sonic Adventure 2: Battle (GSNE8P) - 1782 .prs

`*mdl.prs` (characters, enemies `e_*`, bosses, minimal `mh##*`): PRS -> a table of `u32 id,
u32 offset` (BE, terminated by 0xffffffff) pointing at NJS_OBJECT trees (52 B: flags, attach,
pos f32[3], rot i32[3] BAMS, scale f32[3], child, sibling; big-endian). Attach = NJS_CNK_MODEL
`u32 vlist, u32 plist, f32 center[3], f32 radius`. Chunk data is the Dreamcast layout with
every field byte-swapped: vertex-chunk header reads `u16 size, u8 flags, u8 type, u16 count,
u16 index offset` (word-swapped pairs), poly-chunk headers `u8 flags, u8 type`, strip
indices / UVs / s16 normals per-u16 BE, floats BE. dcrip's chunk cache evaluator
(`dcrip.ninja_eval.evaluate`) then builds the rigged scene: Sonic = 2790 tris / 60 joints,
Eggman, Metal Sonic, 52 Sonic variants in one archive. Texture archive = model name with
`mdl` -> `tex` (`sonictex.prs`): GVM inside; material texture ids index the GVM order.
`*mtn.prs` = motions (NMDM-like, not ripped yet). Stage geometry is NOT in .prs (land tables
live in the `.rel` modules / main.dol - open).

## GVM / GVR

GVM: `GVMH | u32 LE header size | u16 BE flags | u16 BE count | entries (u16 id, name[28]
if flags & 8, u16 formats if & 4, u16 dims if & 2, u32 gbix if & 1)` then GVR chunks at
header size + 8. GVR: `[GCIX | u32 size | u32 index] GVRT | u32 LE size | u16 0 | u8 palette
flags | u8 data format | u16 BE w | u16 BE h | GX pixels`; data format = GX format (0 I4, 1
I8, 2 IA4, 3 IA8, 4 RGB565, 5 RGB5A3, 6 RGBA8, 8 C4, 9 C8, 0xe CMPR); palette flag bit 1 =
internal palette (format in the top nibble: 0 IA8, 1 RGB565, 2 RGB5A3), bit 3 = external
.gvp. SADX ships bare `.gvm` files (680) - the gvm plugin handles them directly.

## Shadow the Hedgehog (GUPE8P) - `.one` "One Ver 0.60"

`u32 0 | u32 size - 12 | u32 RW 0x1c020037 | "One Ver 0.60" | u32 0 | u32 count`, 0xcd
padding to 0xb0, then 56-byte entries `char name[44], u32 unpacked size, u32 offset, u32
compressed (1)`; each member has a 12-byte slot before its PRS stream (which may run into
the next slot); members are RenderWare DFF / TXD / UVA -> the renderware plugin rips them
(EFFSHEWORLD.DFF: 1770 tris, 31 joints).

## Phantasy Star Online Episode I & II (GPOE8P) - `.nj`, `.bml`, `.gvm`, `.rel`

`.nj` (198 player parts: `plAbdy00.nj`) = `NJTL` / `NJCM` / `POF0` blocks with LITTLE-endian
block sizes and BIG-endian payloads: the NJCM payload is the SA2B chunk layout (same
byte-swapped headers) -> `gcrip/formats/sa2b.GcChunkParser` (`plAbdy00`: 64
objects, 512 tris). `.bml` (293) = archive: 64-byte header (`u32 0, u32 BE count`), 64-byte
entries (`name[32], u32 BE packed, u32 0, u32 BE unpacked, u32 BE texture packed, u32 BE
texture unpacked`), data from 0x800: per entry PRS(model) then, 32-byte aligned, PRS(GVM).
Members are `.nj` (chunk) or `.gj` = `GJTL` / `GJCM` "Ginja": GX-native attaches (SA Tools
GCAttach layout: vertex sets `u8 attr, u8 size, u16 count, u32 struct|type<<4, u32 ptr`;
meshes `u32 params, u32 count, u32 prims, u32 size`; params `u8 type .. u32 data` with type
1 = index attribute flags (bit 3 pos, 5 nrm, 7 col, 11 uv; bit-1 companions = 16-bit) and
type 8 = texture id; primitives = raw GX strips). Dark Falz boss parts (boss06_plotfalz_dat.bml)
rip rigged + textured (6,348 tris / 108 joints). gcrip: `formats/bml.py`, `formats/ginja.py`,
`plugins/bml.py`, `plugins/ninja_gc.py`. Open: `.rel` (647, 175 MB: `files/Scene/map_*n.rel`
level geometry) - PSO "rel" = raw big-endian data with a 32-byte FOOTER `u32 pointer table
offset, u32 pointer count, u32 1, u32 0, u32 root offset, ...` (the table lists the file
offsets that hold pointers); the geometry is tag-less Ginja-style attaches reached from the
root - not decoded; `.gsl`, Episode III.

## SADX / SA2B `.rel` modules (SA Tools split tables)

X-Hax SA Tools ships `GameConfig/GC_SADX` (53 INIs) and `GC_SA2B` (93) listing every model /
land table / animation address inside the GameCube `.rel` modules (`datafile=STG00.rel`,
`key=C900000`; INIs without a datafile line map to `<stem>.rel`). gcrip bundles them under
`gcrip/data/satools/`. Pipeline: `formats/rel.py` resolves the Nintendo REL relocations
against base 0 (so pointers become file offsets: OSModuleHeader, section table, imp table,
`u16 offset, u8 type, u8 section, u32 addend` entries with 201 NOP / 202 SECTION / 203 END),
then `formats/sadx.py` reads Basic models (NJS_MODEL BE, 28-byte "DX" meshsets, materials
whose texture id is valid even though NJD_FLAG_USE_TEXTURE is clear), SA2B chunk models,
Ginja models and land tables (SADX 0x24 COLs: object @0x18; SA2B 0x20 COLs: object @0x10,
first `chunk count` entries visible Ginja, rest Basic collision). Results: SA2B City Escape
`stg13D.rel` -> 26,106 tris textured from `landtx13.prs`; SADX `ModelsMiles.rel` -> 44
models (Tails 1,651 tris / 68 joints), `stg00.rel` Emerald Coast 4,460 tris (stage texture
archive name not in the table - BEACH01/02/03.GVM by act - open). Entry `texture=NAME` ->
`NAME.gvm`.

## Billy Hatcher and the Giant Egg (GEZE8P) - `.prd` / `.arc` / `.lnd` (ripped 2026-08-29)

`.prd` (91 files, 295 MB; `gcrip/formats/prd.py`): `u32 1 | u32 unpacked | u32 packed | u32
| u32` then a standard Sega PRS stream from 0x20 that inflates to a `Uª8-` ("U:8-")
archive: `magic | u32 table (0x20) | u32 names size | u32 data offset`; at the table `u32 1 |
u32 0 | u32 count + 1` then `count` entries `u32 name offset, u32 offset, u32 size` (name
offsets relative to the byte after the entries).  Members per stage package: `stg_*.lnd`
terrain, `stg_*.mc2` ("CSNI" collision, not ripped), `geobj_*.arc` placed objects,
`ge_player*.arc` Billy variants, `ar_ene_*.arc` enemies + sibling `ene_*.gvm` textures,
`egg_*.arc`, `set_*.bin` placement, `ptcl2_*` particles, `ae_*.arc` UI textures.

`.arc` (`gcrip/formats/billy.py`): `u32 size | u32 pointer table (relocation list at the
end) | u32 | 0 | 0 | "0100" | 0 | 0`, a resource record list at 0x20 (first word = type:
0x20 model, 0x10 UI, 0x1c animated model, 0x1a0 player, 0x84080 motion-only
`ge_player.arc`, ...).  **Every pointer is relative to 0x20**, so `data[0x20:]` is a plain
Ginja buffer.  Objects are NJS_OBJECTs (`u32 flags | u32 attach | f32 pos[3] | s32 BAMS
rot[3] | f32 scale[3] | u32 child | u32 sibling`) padded to 0x38 with `FD FD FD FD`; roots
are found by scanning for that pad (objects not referenced as child/sibling).  The attach is
SA Tools' GCAttach (`vertex sets | skin sets | opaque meshes | translucent meshes | u16
counts | bounds`).  Vertex sets and meshes are the PSO `GJCM` layout
(`gcrip/formats/ginja.py`); mesh parameter type 0 (`u16 attribute | u8 | u8 fraction bits`)
gives the fixed-point scale of `s16` vertex sets (positions/normals/uvs all `/256` here).

Skinning (new for Ginja): mesh nodes of a character carry only a UV set and index the GX
vertex cache; bone nodes carry skin-set records `u16 type | u16 size | u16 slot | u16 count
| u32 rows | u32 weights` where rows are `s16 pos[3] + s16 nrm[3]` in bone space and weights
are `u16 slot, u16 weight/255` pairs: type 0 = single bone (slot + i, weight 1), 1 = first
weighted write at slot + i, 2 = accumulate into the named slot.  Because the drawing node
comes *before* its bones, `dcrip.ninja_eval` evaluates `kind="ginja"` trees in two passes
(all cache writes, then draws).  Results: Billy 141 joints / 2.3k tris, Sonic 51 joints,
zako enemies (root object directly after the record list at 0x40), bosses (240 joints).
Textures: embedded `GVMH` or sibling `<name minus ar_>.gvm`.  Disc census: 1,247 arcs ->
5,053 rigged scenes, 852k triangles, 0 failures; empties are particles / params / events.

`stg_*.lnd` terrain (`gcrip/formats/billy_lnd.py`): same `0100` header; 0x20: `u32 level |
u32 n extra | u32 0x18 | u32 extra ptr | u32 0x20 | u32 GVM | u32 extra[n] | u32 texlist |
u32 count` (12-byte NJS_TEXNAME entries follow; GVM in texlist order).  level -> parts:
`(count, ptr)` pairs for materials (`(1, ptr)` -> 40 bytes, word 9 = texlist index),
vertex pools (`u32 0 | u32 slots`, six slots `u8 0 | u8 kind | u16 count | u32 data`:
f32 positions, f32 normals, RGBA8 colours, colour 1, s16/256 uvs, uv 1), display lists
(`(0, ptr)` -> `flags | data' | size' | data | size`, one pair used; flags bit 0 pos, 1 nrm,
2 col, 3 col1, 4 uv, 5 uv1 = one u16 index per set bit in every strip row), groups (64
bytes, bounds), then `u32 1 | u32 batch count | u32 batches` (`kind 1 / 2 / 4 (translucent)
| count | entries`; entries `u32 group | u32 pool | u32 material | 0 | u32 display list`).
Stages: 19-23k triangles, 32-63 textures each; boss arenas 4k.

Open: `ge_player.arc` motions (type 0x84080, keyframe blocks with scale triplets), `.mc2`
collision, the alternate-lighting pool (`ge_player1n.arc` "night" variants use it).

## Sonic Riders (GXEE8P)

1,563 extension-less files (`files/0`, `0M`, `0V`, `1`, `10`...) all starting `80 00 00 01`
- an unknown Sonic Team container (no Ninja / GVM tags in the first 16 KB). Open.

## Open

- SADX (GXSE8P): models are Basic/Chunk data inside `.rel` modules + `.bin`; textures `.gvm`.
- PSO Ep I&II / III (`.rel` + `.xj`/`.nj` in .bin?); Sonic Riders; Billy Hatcher motions.
- SA2B `.rel` stage land tables, `*mtn.prs` motions.
