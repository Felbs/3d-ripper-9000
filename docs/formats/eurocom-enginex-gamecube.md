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
- map (`map_list`) placements for level assembly; Nightfire / HP CoS formats.
