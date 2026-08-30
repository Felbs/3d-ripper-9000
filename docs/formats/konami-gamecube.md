# Konami on GameCube - engine map (census 2026-08-29; TMNT 1-3 ripped)

17 Konami discs without models; no shared engine:
- Teenage Mutant Ninja Turtles 1-3 (Konami TYO) - **ripped 2026-08-29**: `TMNT.DAT` /
  `TMNT_V0n.DAT` are Sega/CRI AFS archives (`"AFS\0" | u32 count | (offset, size) x count |
  u32 name-table offset, size`; 48-byte name records) -> `plugins/afs.py`.  Members are
  little-endian RenderWare 3.x streams (lib ids 0x1003ffff / 0x1005ffff): `.dff` clumps
  (characters, props), `.pac` = either a world (chunk 0x0b) or a texture pack, `.anm` =
  rwID_ANIMANIMATION (0x1b), `.txd` = Konami texture pack: chunk 0x23 with payload `u32 count`
  then per texture `char name[16] | 56 bytes | rwID_IMAGE (0x18) chunk` (`Struct { width,
  height, depth, stride }`, one byte per pixel, `2 ** depth` RGBA palette) ->
  `formats/konami_pac.py`, read by `plugins/renderware.py`'s texture index (`.pac` counts as a
  texture dictionary path).  Models decode through the existing RenderWare plugin (bg.dff
  14,836 triangles / 14 materials).  Census: TMNT 1: 4 AFS archives -> 749 members (401 .txd, 179 .pac, 109 .dff), 466 texture packs; 187 RenderWare streams -> 177 scenes / 127k triangles (6 s); TMNT 2 / 3 use .lpac packs (open), Mutant Melee its own archive (open).
  TMNT 2: Battle Nexus (GNIEA4, 2 discs): the AFS members are `LPAC` packs (`"LPAC" | u32
  records | 0xcd x 56`, records `u32 kind | u32 size | u32 | u32 | char name[48] | stream`
  separated by 0xcd padding and 0x80-byte index blocks -> `plugins/lpac.py` finds records by
  their header signature) holding RW 3.4 streams (lib 0x1c02000a): 5,829 `.anm`, 663 texture
  packs, 236 `.dff`, 198 worlds.  Its texture pack is `u16 n | u16 1 | u32 count` then
  rwID_IMAGE chunks each followed by rwID_TEXTURE (struct | name | mask) - `konami_pac.parse`
  handles both layouts.  Census disc 1: 434 scenes / 743k triangles, 663 textures, 400 of
  2,839 materials bound (world sectors carry no texture names in either game).
  TMNT 3: Mutant Nightmare (G3QEA4, 2 discs): same AFS + LPAC wrappers with a 0x80-byte record
  header (`plugins/lpac.py` probes 0x40 / 0x80 for the RenderWare chunk).  Census disc 1: 13,200
  members (10,996 `.anm`, 1,103 packs, 351 `.dff`, 192 worlds) -> 543 scenes / 771k triangles,
  1,105 textures, 450 of 2,050 materials bound.
  TMNT: Mutant Melee (GNMEA4, 2004) - RIPPED 2026-08-29 (`gcrip/formats/melee_arc.py`,
  `plugins/melee.py`): `files/archive.arc` (218 KB) is the directory of the 220 MB
  `files/archive.dat` blob.  Header `char "archive\0" | 0x5c bytes of 0xcd | u32 size | u32
  folder count (238) | u32 file count (8371) | u32 | u32 name-table offset | u32 file-record
  offset`, then 20-byte folder records `u32 name offset | i32 parent | u32 | u32 index | u32
  hash`, the C-string name table, and 20-byte file records `u32 name offset | u32 folder |
  u32 data offset | u32 size | u16 resource type | u16 group`.  Offsets address `archive.dat`
  directly; the member's own magic gives the extension (RW chunk id -> dff / txd / anm / pac,
  `DDS `, `ktf\0`, UTF-16 text).  Contents: 2,256 RenderWare 3.4 clumps (lib 0x1003ffff),
  1,777 animations, 2,081 DDS (DXT1 atlases, several DDS per member for UI), 427 `ktf`
  Konami images (`"ktf\0" | u32 format 9 | u32 w | u32 h | RGBA palette | pixels`, not decoded
  - UI only), 39 TXDs holding the model textures by name (`characters.txd`, `effects.txd`,
  `weapons.txd`).  Census: 2,331 scenes / 614,914 triangles, all rigged, 3,851 of 4,674
  materials textured, 3 s once the disc read is done.  The sound banks (`MUSIC.MCP`,
  `VCLIP.BKT`) and the `.thp` videos are the rest of the disc.
  Earlier note: `archive.dat` (219 MB, `1b 00 00 00 dc 16 00 00`), `.bkt`, `.mcp` - not
  AFS, open.  (TMNT 2007 is Ubisoft Jade and already rips.)
- Frogger Beyond: `.bin` x35 (238 MB), `.mcp` 66 MB, `.bkt`; Frogger's Adventures similar.
- Yu-Gi-Oh! The Falsebound Kingdom: `.pac` x2 (221 MB), `.mrg` x62 (165 MB).
- Disney Sports Soccer/Football/Basketball, ESPN MLS / Winter Sports (`.irx`, `.sxq`, `.bin`,
  `.rom`), Evolution Skateboarding/Snowboarding (`.bin`, `.fbd`, `.rel`), Winning Eleven 6,
  Captain Tsubasa, WTA Tour Tennis: each its own container.
Priority: low per title; TMNT 1-3 (3 discs, one engine) would be the first to reverse.

  World sector textures (checked 2026-08-29 evening, still open): the `.pac` world materials
  really do carry `isTextured = 0` - the RW material struct is `u32 flags | RGBA | u32
  0x0f5f62ec (the same constant in every material, so not a texture id) | u32 textured 0 |
  f32 ambient / specular / diffuse`, and the material list has no texture chunks and no
  extension data.  The sectors are drawn with vertex colours plus a texture the game binds
  from elsewhere (a per-sector table in the level's other members), so binding them needs
  that table, not a change to the RenderWare reader.
