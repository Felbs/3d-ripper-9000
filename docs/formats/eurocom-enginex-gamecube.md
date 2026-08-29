# Eurocom EngineX on GameCube: Filelist.bin/.000 and GEOM .edb databases

Games in the library with this pipeline (all verified 2026-08-29 on samples): Sphinx and the
Cursed Mummy (Filelist v5, EDB v182), Buffy: Chaos Bleeds (v5 / v170), Spyro: A Hero's Tail
(v7 / v240), Robots (v7 / v248), Batman Begins (v7 / v251), Ice Age 2 (v7 / v252).
NOT this pipeline: 007 Nightfire (`common/*.bin`), Harry Potter CoS (`*.geo`).
References: github.com/eurotools/eurochef (Rust EDB crates), eurotools/binary-templates
(`EX_Filelist_v4-7.bt`), Swyter/sphinxtools. gcrip: `gcrip/formats/eurocom.py`,
`gcrip/plugins/eurocom.py`, tests/test_eurocom.py.

## Filelist.bin (big-endian on GC)

`u32 version (4-7) | u32 size | u32 count | [v5+: u16 build type, u16 extra lists] | i32
rel. pointer to the name table` then per file `[v4: u32 offset] u32 length | u32 hashcode |
u32 version | u32 flags | [v5+: u32 nlocs, (u32 offset, u32 list index) x nlocs]`. The name
table is `count` relative pointers (relative to their own position, like every EngineX
pointer) to C strings `x:\sphinx\binary\_bin_gc\doors.edb`; v7 obfuscates every byte
(including the terminator) as `stored = char - 0x16 + file index + char index`. Files
often appear twice in `Filelist.000` (seek optimisation). `.edb` lengths are the BASE size;
the full size is at EDB offset 0x14 - read that many bytes.

gcrip treats `Filelist.000` as the container and reads the sibling `Filelist.bin` through
the new `NEEDS_SIBLING` / `expand_with(data, name, sibling)` container hook (manifest and
rip both support it).

## GEOM .edb (big-endian on GC)

Header `"GEOM" | u32 hashcode | u32 version | u32 flags | u32 time | u32 file size | u32
base size | u32[6] platform versions`; hash arrays (`i16 count | i16 hash size | i32 rel`)
at 0x54 (v < 248) or 0x40: sections, refpointers, entities, anims, animskins, animscripts,
maps, animmodes, animsets, particles, swooshes, spreadsheets, fonts, [v248+: forcefeedback,
materials], [v240 only: 8 pad bytes], textures. Elements: `u32 hashcode, u16 section, u16
debug, u32 address (absolute), u32 ptr` + extras (entity element 32 B for v < 213, 20 B for
240+; texture element 28 B: + u16 w, u16 h, u32 game flags, u32 flags).

### Mesh entities (type 0x601; 0x603 = split with `u32 count [+u32 if v > 213]` then
relative pointers to children)

| field | v170 / v182 | v240 / v248 | v251 / v252 |
| --- | --- | --- | --- |
| texture index list (`u16 n, u16[n]`) | none - strip texture index is the EDB texture index | +0x54 | +0x54 |
| tri-strips | +0x44 | +0x58 | +0x58 |
| vertices | +0x48 (12 B f32 xyz; skinned entities 16 B - pick the size that fits before the UV block) | +0x5c (16 B: xyz + u32) | +0x5c |
| texcoords (s16 pairs) | +0x4c | +0x60 | +0x60 |
| colours RGBA8 | +0x50 | +0x64 | +0x64 |
| normals? (4 B entries, unresolved) | +0x54 | +0x68 | +0x68 |
| tristrip count, vertex count | +0x5c, +0x60 | +0x7c, +0x80 | +0xa4, +0xa8 (ten floats precede them) |
| index word (UV divisor = 65536 >> ((w >> 28) & 7)) | +0x68 | +0x88 | +0xb0 |

Tri-strip record: `u16, u16 texture index, u16 flags, u16 transparency, u32 data size,
u32, u32[4]` (32 bytes) + display list of `data size` bytes: `u16 0x0098 | u16 count` then
`count` rows of `u16 position index, u16 normal?, u16 colour index, u16 uv index`; several
strips per list. Normals: the second column runs past the entity's normal block (Sphinx
doors: indices up to 0xf8 with an 11-entry block) - probably a global quantised table;
left out for now.

### Textures

Struct at the element address (+4 on v <= 205): `u16 w, u16 h, u16 depth, u16 game flags,
s16 scroll u, s16 scroll v, u8 frames, u8 images, u8 rate, u8 pad, u8 values, u8 regions,
u8 mips, u8 format, u32, u8 colour[4]`, then 2-4 i16 relative pointers + version pads, `u32
data size`, `i32 rel frame offsets[images]`. gcrip scans +0x20..+0x30 for the (size,
pointer) pair whose target is a 64-byte GX header (byte 27 = GX format) followed by the
pixels. Eurocom format codes: 0 CMPR, 1 RGBA8, 3 RGB5A3, 4 I4, 5 I8, 7 IA4, 8 IA8.

## Open

- normals; anim skins (skeleton hashcodes in the animskin list, bone weights unknown);
- UV divisor on Ice Age 2 looks off (5-6 range) - check the index word for v252;
- map zones (see below); Nightfire / HP CoS formats.

## Map placements / level assembly (2026-08-29)

Header list 6 (`map_list`, the same 20-byte hash-array elements as the entity list) points at
map headers: `u32 0x500 magic | i32 rel bsp tree | ... | u32 placement count (+0x48) | i32 rel
placement pointer (+0x4c) | ... | f32 bounds box[6] (+0xa8 on v182)`.  Placements are 56-byte
records (v182; eurochef documents a 60-byte variant for the later PC versions): `u32 hashcode
(0xffffffff when unnamed) | f32 position[3] | u32 flags | f32 rotation[3] (radians, X then Y
then Z, row-vector matrices) | f32 scale[3] | u16 engine flags | u16 map | u32 object
reference (an entity hashcode of this EDB) | u16 light set | i16 group`.

`gcrip/plugins/eurocom.py` builds one `eurocom-map` scene per map by placing every referenced
mesh entity (`_rotation` + scale + translation applied to positions and normals); entities not
named by a placement are still exported individually, so nothing is lost.  Verified on Sphinx
`_lu_pala.edb` (405 placements, 99,814 triangles - the props sit in a coherent layout) and
`f00_fron.edb` (78 placements, the front-end sky dome).  Census: Batman Begins: 75 maps, 8,884 placements (1 unresolved), 2,124,082 triangles, 276 EDBs / 11,693 scenes, 33 s; Buffy the Vampire Slayer - Chaos Bleeds: 16 maps, 741 placements (2233 unresolved), 70,200 triangles, 218 EDBs / 8,465 scenes, 9 s; Cubix Robots for Everyone - Showdown: no filelist; Ice Age 2 - The Meltdown: 29 maps, 1,069 placements (26 unresolved), 467,733 triangles, 222 EDBs / 2,066 scenes, 6 s; Robots: 13 maps, 525 placements (0 unresolved), 482,465 triangles, 172 EDBs / 4,619 scenes, 11 s; Sphinx and the Cursed Mummy: 49 maps, 3,555 placements (316 unresolved), 973,985 triangles, 417 EDBs / 8,831 scenes, 14 s; Spyro - A Hero's Tail: 61 maps, 7,441 placements (847 unresolved), 1,870,282 triangles, 323 EDBs / 4,587 scenes, 18 s.

Open: map zones (`EXGeoMapZone.entity_refptr`, the static world chunk of each zone - the
zone table's offsets for v182 are not located, so terrain still comes out as an unplaced
entity at the origin), placement groups, lights / paths / portals.
