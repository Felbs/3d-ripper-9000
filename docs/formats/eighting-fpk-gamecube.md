# Eighting FPK archives on GameCube (Naruto: Clash of Ninja / GNT, Bloody Roar: Primal Fury, Zatch Bell!, Battle Stadium D.O.N)

Verified 2026-08-29 on Naruto GNT4 (439 fpk), Naruto CoN (78), Bloody Roar PF (87), Zatch
Bell Mamodo Battles (277), Battle Stadium DON (173). gcrip: `gcrip/formats/fpk.py`,
`gcrip/plugins/fpk.py` (container only - the members are read by existing plugins).

## Container (big-endian)

`u32 0 | u32 count | u32 header size (16) | u32 file size`, then `count` entries:
`char name[20] | u32 offset | u32 packed size | u32 unpacked size` (Naruto GNT: names like
`hr/ank/0000.dat`) or `char name[32] | ...` (RenderWare-based Bloody Roar / D.O.N:
`chr/ar2/0000_gc.dff`). Pick the width whose entries all point inside the file. Data is
16-byte aligned after the table.

## Compression: Eighting PRS (GNTool's PRSUncompressor)

Sega-PRS-like but with the flag bits read MSB-first and the long-copy pair big-endian:
- read 1 flag bit: 1 -> literal byte;
- 0 then 0 -> short copy: length = 2 flag bits + 2, offset = next byte - 256;
- 0 then 1 -> long copy: `u16 BE` p; offset = (p - 0x10000) >> 3 (arithmetic), length =
  p & 7 (+2; 0 -> next byte + 1).
Stop at the unpacked size. `packed == unpacked` -> stored. All 22 GNT4 sample members and
the other four games' samples decompress to their exact sizes.

## Members

- Naruto GNT / CoN: `.dat` = HAL sysdope (HSD) DAT files - the `hsd` plugin already reads
  them (GNT4 Anko `hr/ank/0000.dat`: 11.7k tris, 118 joints, 14 textures); `.jcv` joint
  lists, `.mot` motions, `.txg` Eighting texture packs (`u32 count | u32 0x20 | offsets`),
  `.ptl` particles.
- Bloody Roar / D.O.N: `.dff` RenderWare models (`renderware` plugin), `.txd` textures,
  `.anm` animations.
