# Traveller's Tales NU2 on GameCube (LEGO Star Wars 1/2, Crash: Wrath of Cortex, Finding Nemo, Super Monkey Ball Adventure, Narnia, Bionicle Heroes)

Status 2026-08-29 (later): the LSW1 `.gsc` / `.csc` vertex stream IS decoded (`gcrip/formats/nu2.py`,
`gcrip/plugins/nu2.py`): inside OBJ0 every mesh is a run of tagged blocks - `03 01 00 01 | u8
fmt|0x80, u8 count, u8 0x6c` + count x `f32 x y z nz`; `01 00 00 05 | .., count, 0x6d` + count x
`s16 u v nx ny` (/4096); optional `00 00 00 05 | .., count, 0x6e` RGBA8 colours; optional `04 80
count 65` second UV set; `01 01 00 01 00 03 00 14` ends the mesh. Each block is one triangle
strip in vertex order (no index list; 255 verts max per block, hence 400+ blocks per model).
Verified: Gungan Bongo 404 blocks / 15.5k tris, Pod Race level chunk 420 blocks. Materials /
texture binding (MS00 + the 16-byte descriptors `d2 80 01 6c | count 80 .. | 00 40 02 30 | 12 05`
before each block) still open -> meshes export untextured with UVs. The same stream appears in
Bionicle Heroes `.csc` and a few Finding Nemo `.nus`; NOT in LSW1 `.nus` (chunk sizes stored
negated, geometry encoded differently), Crash WoC / Nemo `.hgo`, SMB Adventure `.chr`, LSW2 /
Narnia `.gcm` - those variants are still open.

LSW1 `.nus` (24 files, 223 MB, the big level scenes): chunk sizes are stored NEGATED
(`GSC0 | -size`, `TST0 | -313940`), chunks VERS, NTBL, NAME, NAMS, TST0, MS0X x3, PLGT (484
KB), LDIR, GST0 (580 KB), BNDS, INST, SPEC, SST0, DYNO. PLGT and GST0 hold PC-style 32-byte
vertex records (`f32 xyz | RGBA 7f7f7fff | f32 nx ny nz | u32 0` in PLGT; `f32 xyz | f32 nrm
| RGBA | f32 uv` in GST0, header `u32 1 | 0 x5 | u32 0x12 | 0 | u32 vertex count`) with a small
index / strip table at the chunk end - not decoded; the same level geometry also exists as the
decoded stream in the level's `.gsc`, so `.nus` is not needed for a first rip.
Finding Nemo / Crash WoC `.hgo` = the same NU2 chunk tree big-endian with reversed tags
(`FOGH | size | LBTN | size | names...`, `TSH0` ...) - the vertex encoding was not located
(no `03 01 00 01` markers in either byte order); open.

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
