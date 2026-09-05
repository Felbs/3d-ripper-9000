# Krome Studios (Merkury engine) on GameCube: RKV archives, MDL2 models, GTX textures

Games: Ty the Tasmanian Tiger (2002, RKV v1 + MDL2 `.gmd` + `.gtx`); Ty 2 (2004), Ty 3
(2005), The Legend of Spyro: A New Beginning (2006) and King Arthur (2004) ship RKV2
archives with MDL3 `.mdl` + `.mdg` pairs and `.tex` textures. Jimmy Neutron: Jet Fusion is
NOT a Merkury disc (its Data_GC.rkv is a different, unknown container). Verified
2026-08-29: Ty 1 `files/Data_GC.rkv` (20,208 members; 978 .gmd -> 971 models / 1.43 M
triangles, 278 skinned; 2,411 .gtx); Ty 2 Data_GC.rkv (30,104 members; 2,317 .mdl ->
1,953 models / 3.19 M tris, 422 skinned); King Arthur (7,385 members; 1,109 .mdl -> 1,021
models / 1.23 M tris, 126 skinned); Ty 3 and Spyro samples parse (Ty 87 bones, Spyro 81).
gcrip: `gcrip/formats/rkv.py`, `gcrip/formats/mdl2.py`, `gcrip/formats/mdl3.py`,
`gcrip/plugins/rkv.py`, `gcrip/plugins/mdl2.py`, `gcrip/plugins/mdl3.py`.

## RKV v1 (Ty 1)

The archive is member data followed by the directory at the END of the file, all
little-endian:

- `nfiles` entries of 64 bytes: `char name[32], u32 dir index, u32 size, u32 0, u32 offset,
  u32 crc, u32 time, u32, u32`. Offset 0xffffffff = a source file that was not shipped
  (tga/max sources are listed but absent).
- `ndirs` directory names of 256 bytes (e.g. `_PP_Files\`).
- Footer: `u32 nfiles, u32 ndirs` (last 8 bytes of the file).

Member extensions in Ty 1: gsb 7028 (sound), awf 5734 (audio wave), gtx 2411 (textures),
gpk 1405, gmd 978 (models), anm 448 (animations), bad 229 (skeleton/bone text files), dlg,
localisation text, ini.

## MDL2 model (.gmd, GameCube; PC .mdl shares the tables) - big-endian

Header: `"MDL2" | u16 fragments | u16 subobjects | u16 colliders | u16 bones | u32 subobject
table | u32 collider table | u32 bone table | u32 vertex buffer | u32 vertex count (0x1c) |
bbox floats`. Name strings live in the header area.

- Subobject (80 B): bounds, u32 name ptr @48, u32 material @52, u32 triangles @56, ...,
  u16 mesh count @66, u32 mesh table @68.
- Mesh (16 B): u32 material name ptr, u32 display list offset, u32 `(size / 16) << 16`,
  u32 strip count.
- Display list: GX primitives (0x98 strips, also 0x80/0x90/0xa0 seen) whose vertices are
  FOUR u16 indices - position, normal, colour, uv - into ONE interleaved vertex buffer.
  Indices that fall outside the vertex count mean "use the position index".
- Vertex record (28 B): `f32 x y z | s8 nx ny nz, u8 flag | s16 u, s16 v (/4096) |
  s16 weight (/4096), s8 bone a, s8 bone b | u8 r g b a`. Normals need renormalising
  (|n| ~ 0.12 raw). Weight w applies to bone a, 1-w to bone b.
- Bones (16 B each): a world-space position vec3 + pad. NO hierarchy in the model; the
  parent tree is in the sibling `.bad` text file (not parsed yet).
- Vertex count 0 (placeholder/effect models: gem, chest, logo, sparks) -> nothing to rip.

Material name == `.gtx` texture stem, case-insensitive (`Act_01_TY_01` ->
`act_01_ty_01.gtx`); Ty 1 resolves 12.5k of 14k mesh materials that way; the misses are
font glyph materials (`T0103_01_*`).

## GTX texture (.gtx) - big-endian

`u32 version | u32 width | u32 height | u32 0 | u32 0 | u8 extra mip levels, ... | pixels
@0x20`. Version 2 = GX CMPR (DXT1-like), base level first then the mip chain (extra levels
= byte @0x14); version 0 = GX RGB5A3, no mips (used for textures with alpha: moth,
jellyfish, glass, water). Decode with `gcrip.formats.gx_texture.decode(14 or 5, w, h, data)`.

## RKV2 (Ty 2 / Ty 3 / Spyro ANB / King Arthur) - little-endian

Header: `"RKV2" | u32 nfiles | u32 name table size | u32 nsources | u32 source table size |
u32 directory offset | u32 directory size | u32 version (0x070b070b) | u32 0x32e`. Data
archives keep the directory at 0x80 (before the member data); media archives put it at the
end. Directory = `nfiles` 20-byte entries `u32 name offset, u32 flags (0), u32 size, u32
offset, u32 crc`, then the name table (bare file names, no folders), then per-file build
info (`u32 source path offset, u32 0, u32 mtime, u32 name offset`, 16 B) and the source
path strings (`O:\Builds\DATA\040826-117g\Data\..\GC_Specific\music\..`). Music
members carry a 0x80-byte header and 64 KB-aligned bodies (sizes end in 0x80).

Ty 2 member extensions: gsb 10506, tex 3276, bni 2417, pkg 2323, mdg 2317, mdl 2317, bbi
1410, ang 1404, anm 1404, bpk 1221. Spyro adds `.min`/`.sub`; King Arthur `.cgr`.

## MDL3 (.mdl) + MDG3 (.mdg) - big-endian

`.mdl`: `"MDL3" | u16 subobjects | u16 textures | u16 bones | u16 refpoints | u16 ? | u16
blocks | ...`; u32 table offsets at 0x50: `subobjects (64 B: bbox min xyz, radius, size
xyz, 0, pivot xyz, 1.0; u32 name @48), texture name pointers, refpoints (position, radius,
name, bone), bones (16 B position + pad), table3, 0, block table, 0`. The block table is
`textures x subobjects` u32 offsets into the `.mdg` (row-major over textures; 0 = no
geometry for that pair), so a block's material is its row's texture name and its subobject
its column. Texture name == `.tex` stem (case-insensitive); `.tex` has the same header as
`.gtx` (version 2 CMPR + mips, version 0 RGB5A3). Refpoints are `r_*`, subobjects `m_*`,
collision `C_*`/`CM_*` (untextured placeholder materials like `T0103_01_i`).

`.mdg`: `"MDG3"` + 28 pad, then blocks back to back: `u16 vertex refs | u16 uv refs | u16
? | u16 primitives | u16 (0xffff static) | u16 (16 rigged) | u16 0 | u16 0 | u32 display
list size | u32 colour size | u32 position size | u32 uv size` then the four sections
(32-byte padded). Display list: GX 0x98 strips (also 0x80/0x90/0xa0) with 9-byte vertices
`u16 position index, s8 nx ny nz, u16 colour index, u16 uv index`. Positions: f32 xyz per
record, 16-byte records `xyz | u8 bone a, u8 bone b, u8 weight (a), 0` when the model has
bones (single-bone props still use 12-byte records - pick the size the indices fit),
otherwise 12. Colours RGBA8. UVs s16 / 4096 (tiling allowed: torch -0.6..1.85).

**Position count (2026-09-04 fix):** the position section holds exactly
`max(position index) + 1` records; `position size` is that padded to the 32-byte
boundary, and the pad bytes are junk (NaN / 1e38 float patterns), NOT zeros.
`pos_size // rec` (record size verifies as `align32(nv * rec) == pos_size`, byte-exact
on 1543/1543 Ty 3 world-chunk blocks) over-counted by 1-2 "vertices" per block; those
junk vertices never hit a triangle, so renders looked fine, but they blew the bounding
box (extent 1e37-1e38) of ~2,044 world models across GIZE52 Ty 3 / GYTE69 Ty 2 /
G6SE7D Spyro ANB / GKHEA4 King Arthur - the entire #1-#4 garbage cluster of the
2026-09-04 quality audit. RR3_01 after the fix: extent 58442, median edge ratio
0.0039, 0 NaN, score ok.

## Open

- `.bad` (Ty 1) / `.bni`? skeleton hierarchy -> proper joint tree; `.anm`/`.ang` animations.
- ~9 % of Ty 2 `.mdl` give no geometry: `*_shadow.mdl` pairs use a different `.mdg` block
  (`u32 129 | u32 381 | u32 0x40 | u32 0x850` then f32 rows - a shadow-volume mesh, not
  decoded) and rig-only models (`A217_NanoHand`: 32-byte `.mdg`) carry no mesh at all;
  grass/collision materials have no `.tex`.
- Jimmy Neutron: Jet Fusion container.


## `GC01` - Jimmy Neutron: Jet Fusion (2026-09-03)

Jet Fusion's `Data_GC.rkv` (RKV v1, 12,646 members) carries 1,317 `.mdl` + `.mdg` pairs
whose `.mdl` open `GC01`, not `MDL3`, so the MDL3 reader declined them all and the disc
yielded 18 models (its `.bpk` level packs).  `Jimmy.elf` keeps its symtab (no DWARF):
`Model::UnpackTemplate` fixes the file's pointers and `Model::ExploreBuildVertex` - the
tooling's vertex decoder - names the vertex.

`.mdl` (`ModelTemplate`): `u16` at +4, `i16 subobjects` +6, `i16 refpoints` +8, `u32`
subobject table +12, refpoint table +16, seven bounds floats +32.  A subobject is 0x50
bytes: bounds, name pointer +0x30, `i16 materials` +0x42, material list pointer +0x44.  A
material is 16 bytes: name pointer (the `.tex` stem, `Material::Create`), `.mdg` offset,
`u16 bytes >> 4`, `u16`, `u32 strips`.  Refpoints are 0x20 bytes with the name at +16.

`.mdg`: bare GX display lists - opcode (`0x98` strips), `u16 count`, then 24-byte vertices:
`f32 position[3], s8 normal[3] / 64, u16 RGBA4, s16 uv / 4096`, three bytes of padding (the
stride 0x18 and the constants 1/64, 15 and 4096 sit next to `ExploreBuildVertex`).  Every
material's span walks list by list to its end: `room_6b_02` gives 1,786 lists and 68,616
triangles (a tube level), the rock prop 218 at 0.96 normal agreement, textured.
