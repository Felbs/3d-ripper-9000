# Traveller's Tales NU2 on GameCube (LEGO Star Wars 1/2, Crash: Wrath of Cortex, Finding Nemo, Super Monkey Ball Adventure, Narnia, Bionicle Heroes)

Status 2026-08-29: mapped, NOT decoded (no plugin). Samples: LEGO Star Wars 1 (USA)
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
