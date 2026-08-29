# Avalanche Software DBL / DBU on GameCube (Tak 1/2/3, Chicken Little, DBZ Sagas, Rugrats Royal Ransom)

Status 2026-08-29: container mapped, records NOT decoded (no plugin yet). Sample: Tak and the
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

## Open

- record types for meshes / skeletons / materials (look at `chicken.dbl` inside Burial.dbu);
- texture record pixel formats; `.sdb` (skeleton?), `.mdb`, `.env`, `.dbv` (visibility?).
