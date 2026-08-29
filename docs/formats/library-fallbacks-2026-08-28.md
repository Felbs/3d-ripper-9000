# GameCube library sweep: verified facts from 2026-08-27/28

Source: 3D Ripper 9000 (`Z:\3d ripper`, gcrip) run over all 638 discs of the user's
LaunchBox GameCube library, twice, with per-disc hash verification. Everything below was
observed in data or reproduced in tests.

## Outcome numbers (2026-08-28, after pass 2 + verify-all + pass 3)

- 638 discs processed, 0 errors. 96 games yield 3D models, 220 yield only standalone
  textures (TPL/BTI), 322 yield nothing. 167,651 models and 68,660 animation clips in the
  dump (`D:\3d dump\GameCube`).
- The J3D (Nintendo first-party) games rip completely: rigs, facial expressions (BTP), clips,
  and for Wind Waker the assembled levels. Non-J3D plugins mostly yield static textured
  models; animations only for HSD (Melee / Kirby Air Ride).
- Verify-all: 612/638 discs matched their manifest hashes on re-read. 22 mismatches were the
  multi-disc collision below; 4 were genuine bad reads (re-ripped): DBZ Budokai, Dragon's Lair
  3D, NHL Hitz 2002, PSO Episode I&II.

## Format facts

- **Multi-disc games share one game id** (boot.bin) - only header byte 6 (`disc_number`,
  0-based) differs. Ripping both discs into `<game id>/` makes disc 2 overwrite disc 1 and
  `verify` compare disc 1 against disc 2's manifest (sys/boot.bin + sys/fst.bin "mismatch").
  Fix: folder `<id>` for disc 1, `<id>_disc<N>` for later discs. 44 such ISOs in the library.
- **EA BIG4 index-only headers** (Fight Night Round 2 `.bh`): every entry has offset 0 and a
  size far past the file; the members live in a sibling file. Slicing yields the header itself
  -> infinite recursion. Rule: skip entries with offset+size > len(file); a manifest walker must
  refuse any member byte-identical to its container.
- **RE4 plugin vs EA TERF**: EA's `*.dat` TERF tables expand to `NNNN.bin` members; the RE4
  plugin claimed every `.bin` under a `.dat/` path (its own dat members are `dat_NNN.EXT`).
  Path-based membership rules must match the expander's own naming.
- **Radical RCF** ("ATG CORE CEMENT LIBRARY", Crash Tag Team Racing, 1.38 GB of .rcf on the
  disc): header u32 @0x24 dir offset (0x3c), @0x28 dir size, @0x2c names offset, @0x30
  names size, @0x38 count. Directory entries are 20 bytes: (name hash, offset, packed size,
  unpacked size, flags); flags&1 with size != unpacked = compressed with Radical's own LZ
  (NOT zlib; first bytes look like `f9 0b 00 10 00 03` then the raw P3D header). Members
  include P3D models ("P3D\xff", u32 header size 0x0c, u32 file size), RSD6RADP audio, text.
  Entries are sorted by hash, not by offset - generic table finders must not require order.
- **Treyarch Spider-Man (2002)**: 63 `.gcs` level packs (319 MB, uncompressed, entropy
  5.6-6.9) = chunk system: 64-byte header (u32 payload size, magic 0x5afe0005, chunk count,
  table offset 0x40, ...), first chunk `GCNM` with an asset name (`ac2_e000`) and matrices.
  526 `.gct` texture files: `GCNT`, u32 format (3), then dimensions - a plain GX texture
  container. `.gsw` = sound banks, `.h4m` video, `.adp` audio. No GX display lists in the
  packs: the engine stores float32 vertex runs (e.g. 1,680 xyz triples) and u16 arrays and
  builds GX commands at load time. A per-engine plugin is needed; shared with Treyarch's other
  GC titles.
- **Ty the Tasmanian Tiger 2**: one 838 MB `RKV2` archive (Krome). **Bratz**: `.gcp` packages
  (Blitz Games) 224 MB, entropy ~5. **Billy Hatcher**: `.prd`/`.mpb` + AFS/ADX/SFD (Sonic
  Team). Half the bytes of the "nothing" games are video/audio: THP, H4M, Bink, SFD, ADP, DSP,
  AST, ADX - never models.

## The universal-fallback approach (gcrip/gxscan.py, gcrip/formats/generic.py)

- No universal *file* format exists across 25+ publishers / 257 studios. The universal handle
  is the hardware: GX display lists (opcode 0x80/0x90/0x98/0xA0 | VAT bits, u16 count, index
  tuples or inline vertices, 0x00 NOP padding to 32 bytes), f32 / s16 vertex arrays, tiled GX
  textures - stored as-is because the console DMAs them.
- Scanner: chain primitive headers at one vertex stride (padding tolerated), infer u8/u16 index
  fields from byte columns, find a position array (f32 exponent-plausible run, or s16) big
  enough for the max index, or read inline vertices; choose by a geometry score = mean edge /
  10-90 percentile bbox diagonal * sqrt(triangles) (real meshes ~1-2 at any size, spaghetti
  ~0.5*sqrt(N)); accept < 2.2 (< 1.6 for s16 kinds), >= 20 triangles. 0 false positives on
  random bytes; ~100% of the GMA plugin's triangle total on F-Zero GX files.
- Neutral mode for engines with no display lists: f32 vertex run x u16 index run, sized like
  an index buffer (0.8V..12V indices, max ~V-1, >=60% unique), list and strip layouts.
- Generic containers: (offset,size) tables at stride 4..64 near the start or at a header
  pointer, any column order, unsorted rows allowed, empty rows tolerated, 4-aligned, non-
  overlapping, >=40% coverage; zlib/deflate/LZ10/LZ11/Okumura-LZSS streams validated by size
  and entropy. Recovers 187/187 RCF members blind.
- Both are FALLBACK plugins: consulted only when no real plugin claims a file.
- Limit learned: multi-platform engines (Treyarch, Radical P3D) keep platform-neutral buffers
  behind proprietary containers/compression; the fallback maps them but per-studio plugins
  finish them. LaunchBox's local catalogue (`D:\LaunchBox\Data\Platforms\Nintendo GameCube.xml`)
  supplies developer/genre for the whole library: ~65 non-ripping games are compilations /
  puzzle / rhythm / emulated and can be skipped; developer = engine = plugin ROI order.

## Hardware lesson

- Three BSODs (0x1A, 0x154) during the sweep were one bad DDR4 module (G.Skill F4-3600C16,
  8x16 GB, TRX40 AORUS MASTER / Threadripper 3970X): a pattern test (`memtest.py`, numpy,
  fill/verify in 64 MB chunks) showed the same address flipping bits 5/7 in <60 s on every
  pattern; fault moved with the sticks, not the slots. The earlier belief that the D: HDD
  "returns wrong data on ~3% of reads" was almost certainly this RAM. TRX40 boots with 4 or 8
  DIMMs only. Rips made on the bad RAM were re-verified on the clean 4-stick config.
