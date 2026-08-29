# Avalanche Software DBL / DBU on GameCube (Tak 1/2/3, Chicken Little, DBZ Sagas, Rugrats Royal Ransom)

Status 2026-08-29 (later): CRACKED - `gcrip/formats/dbl_mesh.py` + `gcrip/plugins/dbl.py` rip meshes, textures and materials (see the last section); container notes below still hold. Sample: Tak and the
Power of Juju `files/data_gcn/Burial.dbu` (10.8 MB), `files/data_gcn/fluff/fonttex.dbl`.

Disc layout (Tak 1: 1171 files): `.bik` video 962 MB, `.dbu` level databases 197 MB (21),
`.adp` streams, `.dsp` sounds, `.dba` = SOUND banks (not models: header `0x30 | 0 | "DB" |
... | "SMOD"` + sound names), `.dbl` small databases (fonts, icons), `.cut` cutscenes.
Chicken Little adds `.dbp`, `.sdb`, `.mdb`, `.var`.

## DBL file

Text header first: `"%-7d\n"` = header length in ASCII (e.g. `320    ` / `8704   `), then
build notes (source path, `Export Mode: GCN`, texture list or, for a DBU, the DBLMerge
command line and the numbered member list `n: path size`). Binary header (0x60) at that
offset, BIG-endian on GCN: `0x30 | 0 | "GCN" | 0 | 0x100 | 0 | 1 | u32 payload size |
0x86000e | payload size | u16 4 | "1000"`. Records follow at +0x60: `u32 type | u32 count
| u32 record size | u32 | u32 header size (0x48) | u32 data size (0x278) | ...` - type 8 =
textures: a source path then 72-byte texture entries (`name[32]`, flags 0x041c, u16 w, u16
h, u16 pixel offset/format ...: `Bit32_000.tga` 128x64, `Bit08_*` = palettised). After the
record chain a data area (`0x120 | 0xeeeeeeee` marker) holds the pixel blocks.

## DBU (DBLMerge "UBERDBL")

Global LITTLE-endian header at the text-header end (`0x30 | 0 | "DB" | 0 | 0x100 | 0 | u32
member count (0x12e = 302) | u32 total | ... | "1000"`), then members back to back: 256-byte
member name (`fluff/fonttex.dbl`), a 0x40 LE member header (`u32 flags 0xe0086 | u32 size |
u16 4 | "1000"`), then the member's BE records + data (`size` bytes). Members include the
model databases (`blowgun.dbl`, `chicken.dbl`, `mumking.sdb`, `shrineorbs.mdb`,
`burial.env`, `burial.dbv`) whose record types are the open work.

## Chicken Little variant (GHCE4Q)

`Data_GCN/Characters/*.DBL` and `*.mdb` have NO text header: the 0x60 binary header starts
at 0 (`0x30 | 0 | "GCN" | 0 | 0x100 | 0 | 3 | payload size | 0x82000e | .. | u16 4 |
"1000"`), then records of a different shape than Tak's texture record: `u32 1 | 0 | 0 | u32 1
| 0 | 0 | source path (c:\dev\chick\data_gcn\character ...)`. `.mdb` = LE "DB" header +
named node table (`cannon`, `cannon1`, `thrust1`, identity matrices) = model/bone database.
Still undecoded.

## Records decoded (2026-08-29, gcrip formats/dbl_mesh.py)

Every `.dbl` / `.dbu` / `.mdb` is a chain of sub-databases with a 0x40 header `u16 id | u16
kind | u32 size | u16 count | "1000" | 0x30 zeros` (BE in standalone GameCube files, LE for
DBLMerge members). Kind 0xe = GCN record, 0xb = 0x100-byte name block (starts a new model in
a merged `.dbu`), 0xa = motion / bone database. The record TYPE is the second byte of the id
(first byte in the LE headers): 0x82 texture table, 0x86 particle / font texture table, 0x67
material list, 0x20-0x23 mesh, 0x01 skeleton (Rugrats), 0x98 model header.

Mesh record (prefixed form, ids 0x22 / 0x23): `u32 0x10001 | u32 8 | u32 flags (0x13000160 /
0x15000160) | f32 sphere[4] | f32 bbox[6] | char name[32] | u32 vertex count | u32 positions |
u32 x6 | u32 rows | u32 dl count | u32 dl list | u32 x2 | u32 normal count | u32 normals | u32 uv
count | u32 uvs | u32 x2 | u32 uvs` - every offset is relative to payload + 8 (the flags word).
The older ids 0x20 / 0x21 (Tak 1 `blowgun`, `monkey`, `ShrineOrbsGreen`, all of Rugrats) lack
the 8-byte prefix; offsets are then relative to payload + 0, so the parser just prepends it.
Arrays are GX-native: positions f32 xyz (Rugrats: 16-byte stride), normals s8 / 64 (Rugrats
f32), uvs f32 pairs indexed separately from the positions. The DL list runs from `dl list` to
the first array (the `dl count` word is not the list length: `monkey` says 852 but holds
115): entries `u32 total | u32 material (1-based in prefixed records, 0-based in the old ones)
| u32 | u32 bone ids (one byte each, the skin matrix slots of that batch) | u32 | u32 size |
u16 rows | u16 triangles | u16 0x64xx | u16` followed by `size` bytes of raw GX FIFO: CP loads
`08 50 <VCD_LO>` / `08 60 <VCD_HI>` (0x1401 = matrix index u8 + pos / nrm index8, 0x1e01 =
index16, VCD_HI 2 / 3 = tex0 index8 / 16), XF `10 ...`, BP `61 e2/e3 ...`, indexed matrix loads
`20 / 28`, then primitives `0x98 | VAT` (strips; 0x90 / 0xa0 / 0x80 also handled) whose rows hold
only the enabled index attributes in GX order (PNMTXIDX, POS, NRM, TEX0) - no VAT is needed
because every attribute is indexed. The VCD persists across a record's DLs (later lists do not
repeat the CP loads). Verified: `dodgeball.DBL` 240 rows / 214 triangles match the entry's
counts; `pSphereShape1` positions all sit on a 0.1-radius sphere.

Texture table: `u32 count | u32 x5 | char dir[32]` then 0x48-byte entries `u32 code | u32 x2 |
u32 pixel offset | u16 w | u16 h | u32 x2 | u32 palette offset | u32 x2 | char name[32]` and
the palette / pixel data (offsets relative to the payload). Pixel format by bytes per pixel:
0.5 = CMPR (code 0x405) or CI4 (code 8, 16-entry RGB5A3 palette), 1 = CI8 (code 9, 256-entry
RGB5A3 palette), 2 = RGB5A3, 4 = RGBA8 (code 0x41c). The 0x8000 code flag doubles the
palette area (4 bytes per entry) but the first half is still the RGB5A3 palette (feather_ar,
Bit08_* sheets). Material list (0x67): `u16 version 2-8 | u16 1 | u32 header size 0xc / 0x10 /
0x14 | ...` then entries whose ASCII names are texture file names (Tak: `ygord_c.tga`) or Maya
material names (Chicken Little: `file1`, `Map #1`); a DL's material index binds by name stem,
else by index into the model's textures. Models in a `.dbu` are the runs between kind-0xb
blocks: texture tables, material list, mesh (plus kind-0xa motions).

Census (2026-08-29, plugins/dbl.py): Tak 1 (39 db files) 626 scenes / 1.11M triangles /
3,089 textures, 1,904 of 2,523 materials bound; Tak 2 1,642 / 429k / 4,068, 1,427 of 1,447;
Tak 3 1,117 / 335k / 2,308, 942 of 999; Chicken Little 1,047 / 278k / 4,695, 838 of 856; DBZ
Sagas 939 / 230k / 5,733, 272 of 335; Rugrats 476 texture-only scenes (3,923 textures).

## Open

- skeletons / skinning: the bone ids per DL are kept (`extras.bones`) but the bind poses live
  in the kind-0xa motion databases (`.mdb`: named nodes + matrices) - not wired yet;
- Rugrats: Royal Ransom (2002): mesh record ids 0x21 with the old header (flags top byte 0x0e),
  positions f32 with a 16-byte stride, f32 normals, DLs that start straight with `98 00 04`
  rows (no CP loads: the VCD is set by the game), plus a type-0x01 skeleton record (`spine1`,
  `clavleft` ...);
- `.sdb` / `.env` / `.dbv` members, particle sheets (0x86 tables decode but are not bound).
