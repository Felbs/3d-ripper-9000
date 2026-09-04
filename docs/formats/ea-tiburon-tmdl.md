# EA Tiburon `TMdl` (`.ea3`) models and `MMAP` texture packs - 2026-09-03

The model format inside Tiburon's `TERF` archives (Madden NFL, NCAA Football, NFL Street,
NASCAR Thunder on GameCube).  Read by `gcrip/formats/ea_tmdl.py`, exported by
`gcrip/plugins/ea_tmdl.py`; most members reach it through the `LZH1` codec
([ea-tiburon-comp5.md](ea-tiburon-comp5.md)).

## Layout (big-endian, every offset absolute)

```
TMdl   u32 file size, u16 section count, u16 header size (16), u8[4] version (10 10 06 00)
       section table, 16 bytes each: tag, u32 offset, u32 size, u32 flags
Info   model name: "EAG_DUSK.ea3", "Ball.ea3", "sky_aft2oca1.ea3"
Geom   u32 mesh table, u32 mesh count, u32 attribute table, u32 attribute count,
       u32 attribute mask, u32 extra
Matl   u32 count, u32 record offset[count]
Text   one MMAP texture pack
Swap / Extn / Lite / Loca   swap chains, extents, lights, locators (not read)
```

Mesh record (24 bytes): `u32 display list, u16 display-list size / 32, u16 material,
u16 0xffff, u16 triangles, u16 vertices, u16 first attribute, u8 attribute count, pad[3]`.

Attribute record (12 bytes): `u32 array, u16 count, u8 GX attribute, u8 stride, u8 component
count, u8 component type, u8 fraction bits, u8 index type`.  GX attributes 9 POS, 10 NRM,
11 CLR0, 13 TEX0; component types 0 u8, 1 s8, 2 u16, 3 s16, 4 f32 (5 = RGBA8 on colours);
index type 2 = one byte per index in the display list, 3 = two.  Madden 06 stadiums use
f32 positions, RGBA8 colours and s16/12 texture coordinates; props use s16/15 positions and
s8/6 normals.

The display list is plain GX: `opcode, u16 count, then per vertex one index per attribute in
the mesh's attribute order`.  Opcodes seen: 0x98 strips (2,520 in one stadium), 0x80 quads,
0xa0 fans, 0x90 triangles.  Zero padding to the declared size.

Material record: `u32 name, u32 shader name ("OnePass", "Flat"), u16 texture count, u16 0,
u32 texture name` - the texture name is 15 characters, the key into the pack.

## MMAP as a texture pack

A model's `Text` section is one `MMAP` whose "levels" are separate textures (base level
only, no mips) and whose header's fourth pointer (`+0x20`) is a name block of 16-byte slots.
Stadium packs declare 79 slots and fill 61; the stale slots have zero sizes or nonsense
formats and are skipped with one warning.  Paletted levels take palette records in level
order.  `ea_terf.mmap_pack` returns `(name, rgba, warnings)` per texture; the plain
`decode_mmap` path (no name block) is unchanged.

## Verified

* Madden 06 `STADATA.DAT`: all 73 geometry-bearing `.ea3` files read (Football500 562 tris,
  Ball 220, Trophy_Inflatable 878, 39 sky domes at ~220 each); the two `Loca`-only files
  (SunPositions, SidelineLocators) are skipped as geometry-less.
* Madden 06 `STADIUMS.DAT` member 148, `EAG_DUSK.ea3`: 114 meshes, 5,381 triangles, 80
  materials, 61 textures (concrete, seating, jumbotron, rails, scoreboard digits); the
  thumbnail is a stadium bowl with stands and a jumbotron.
* Tests in `tests/test_ea_tmdl.py` build a model from the description above (strip and u16
  quad lists, every attribute type, a two-texture pack with stale slots) and read it back.

## Open

* The Geom header's sixth word points at a block of 12-byte records `u16 idx[4], u16 k,
  u16 0xa4` on stadiums (850 of them on EAG_DUSK, indices descending by four, `k` cycling
  0..7) - crowd billboard quads, most likely; not exported.
* `Swap` (texture swap chains - home/away, day/dusk), `Lite`, `Extn` are not read.
* ~~Player models~~ - **read 2026-09-04**: Madden 06's `PLADATA.DAT` holds 61 `TMdl`
  (`fm2400.ea3` faces, `pm2400ngc_*.ea3` bodies and shadow rigs) whose display lists open
  with `GX_CMD_LOAD_INDX_A` / `_B` (`0x20` / `0x28`: `u16 index, u16 address`) bone-matrix
  loads and whose vertices then lead with a matrix-index byte the attribute table does not
  list; the shadow-only rigs index `0xff` into a three-entry colour table (read as white).
  With those two rules **all 61 read, 81,446 triangles**; a face renders.  The bone
  matrices are not applied (bind pose).
