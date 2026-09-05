# Library quality audit - 2026-09-04

Automated pass over every exported glTF (`gcrip/quality.py`, thresholds calibrated on GZLE01/GALE01/G6WE69 good vs GDQE7L pre-fix bad). Machine verdicts: `garbage` (spaghetti index decode, collapsed geometry, NaN), `suspect` (one soft signal: mild spaghetti, shattered micro-crumbs, tiny vs siblings, unreadable/missing pieces), `untextured` (bare model in an otherwise-textured game).

Outputs consumed by tooling:
- `D:/3d dump/GameCube/quality_report.json` - per-game counts + 10 worst models each
- `D:/3d dump/GameCube/quality_flags.json` - `"<GID>/<out_rel>" -> {score, reasons}` for every non-ok model (library UI hook)

## Library-wide counts

- games audited: **636**
- models scored: **921,827**
- garbage: **5,025** (0.5%)
- suspect: **13,503** (1.5%)
- untextured: **45,721** (5.0%)

## Top 15 worst games (the rip fixers' work list)

| # | game | title | scored | garbage | suspect | untextured | example bad models |
|---|------|-------|--------|---------|---------|------------|--------------------|
| 1 | GIZE52 | Ty3 | 2651 | 707 | 123 | 208 | RR3_01.gltf, RR4_01.gltf, RR7_01.gltf |
| 2 | GYTE69 | Ty2 | 2045 | 609 | 89 | 87 | RC3_02.gltf, Rr3_02.gltf, RR4_02.gltf |
| 3 | G6SE7D | spyro06 | 1163 | 478 | 38 | 76 | E01_01.gltf, A10_01.gltf, P7002_vikingShip.gltf |
| 4 | GKHEA4 | King Arthur | 1072 | 250 | 37 | 47 | rc9_01_01.gltf, rc3_01_Rc3_Chunk_02.gltf, rc3_01_Rc3_Chunk_06.gltf |
| 5 | GPTE41 | Prince of Persia : The Sands of Time | 10624 | 214 | 316 | 859 | 6101_Tour_wow_ff02a28d#29002044_6101_Tour_VIS.gltf, 2201_Aviary_wow_ff0b5b96#2b005b7a_2201 |
| 6 | GH3E69 | NHL 2003 | 6815 | 203 | 4 | 1212 | 2dc_lowersides.gltf, 2dc_lowersides.gltf, goalieShadow.gltf |
| 7 | G4FE69 | FIFA 07 | 25866 | 177 | 68 | 295 | m48__.gltf, m38__.gltf, m723__0_0_0.gltf |
| 8 | G4OE69 | The Sims 2 Pets | 21474 | 162 | 32 | 2364 | 29ab6dae.gltf, 2ec6a9b7.gltf, 59c19921.gltf |
| 9 | G9TE52 | Shark Tale | 1460 | 158 | 7 | 128 | e67620b3.gltf, d13c537b.gltf, 725ca3b8.gltf |
| 10 | GF6E69 | FIFA 06 | 19613 | 143 | 106 | 764 | m48__.gltf, m241__.gltf, m117__.gltf |
| 11 | GNZE69 | NBA STREET Vol.2 | 834 | 113 | 5 | 71 | phillyo.gltf, phillyo.gltf, centera.gltf |
| 12 | GF5E69 | FIFA Soccer 2005 | 22616 | 111 | 22 | 138 | pitchdetail__detail__model1020314988__.gltf, divthreeeurocn__track_divthreeeuro_cn__model3 |
| 13 | GMHE52 | Mat Hoffman's Pro BMX 2 | 533 | 106 | 366 | 0 | misc4drgn030x020x50.gltf, poground21.gltf, chchunk19.gltf |
| 14 | GXFE69 | FIFA Soccer 2004 | 5925 | 100 | 15 | 2 | pitchdetail__detail__model1020314988__.gltf, alpicd__track_alpi_cd__model81689453125__.glt |
| 15 | GUCP69 | UEFA Champions League 2004 - 2005 | 8865 | 83 | 30 | 9 | pitchdetail__detail__model1020314988__.gltf, ataturkod__track_ataturk_od__model69641113281 |

## Patterns in the top offenders

- **Krome engine sweep (#1-4): GIZE52 Ty3, GYTE69 Ty2, G6SE7D Spyro 06, GKHEA4 King Arthur.**
  The garbage is concentrated in world-chunk models (`RR3_01`, `RC3_02`, `rc3_01_Rc3_Chunk_*`,
  `E01_01`) - the Krome GC01 world/chunk path is decoding wrong at scale even though the
  format "ships". Biggest single fix available: ~2,000 garbage models across four games.
- **EA ball-sports family (FIFA 04/05/06/07/WC06, UEFA, NHL 2003, NBA Street 2): the same
  few meshes garbage in every title** (`pitchdetail__detail__model1020314988__`, `m48__`,
  arena/`2dc_lowersides`). One EAGL pitch/arena sub-format bug repeated across ~10 games.
  **FIXED 2026-09-04**: world packets store f32 positions (element size from the stream
  gap), read as s16/256 they saturate into +-128 clouds - that recurring "extent ~440" in
  the worst lists was the s16 diagonal, the audit signature of this exact bug. Plus a
  per-model s16 quantization recovered from `__BBOX` (stadium stands are 1 fraction bit,
  players 8). 100/100 flagged FIFA 2004 stadium models fixed, 0 clean regressed, players
  byte-identical; discs pending re-rip. See
  [ea-eagl-gamecube.md](ea-eagl-gamecube.md).
- **GCJE41 Splinter Cell Chaos Theory: 51 of 53 models garbage** - the whole export is a
  bad decode, not individual models.  **FIXED 2026-09-04**: the 51 "models" were
  `screens/<lang>/*_loading*.tga` **loading-screen pictures** (type-1 color-mapped TGA,
  640x448) that no plugin claimed, so the `gx` fallback scanned their palette-indexed
  pixel data for display lists and exported noise (`autocrack.probe` on the source bytes
  rates the GX evidence "WEAK - sparse accidental-looking chains, no CP/XF setup").
  `gcrip/formats/tga.py` + `gcrip/plugins/tga.py` now decode them as textures-only
  scenes (a recognizable loading screen each), and claiming them keeps the scanner off
  the class entirely.  Both discs re-ripped: disc 1 now exports 462 tga + 2 tpl, 0
  failed, and re-auditing scores **462 models, 0 garbage / 0 suspect / 0 flagged**
  (disc 2's 26 gx-noise "models" were the same class).  One other title shipped
  gx-claimed `.tga` sources - GSGE5D MLB Slugfest 2003, 5 models - queued for re-rip.
- **GMHE52 Mat Hoffman Pro BMX 2: 472 of 533 flagged** - park chunk models
  (`chchunk19`, `poground21`), another whole-format failure.
- Untextured hotspots (Sims 2 Pets 2364, NHL 2003 1212, PoP:SoT 859) are texture-pipeline
  gaps, not geometry bugs - different work queue.

## Flag reasons across all games' worst lists

- `shattered`: 908
- `degenerate_edges`: 782
- `untextured`: 585
- `spaghetti_mild`: 423
- `spaghetti`: 388
- `degenerate_edges_mild`: 239
- `collapsed_positions`: 200
- `tiny_vs_siblings`: 154
- `nan_positions`: 28
- `collapsed_extent`: 26
- `unreadable_geometry`: 11
- `unreadable`: 10

## Calibration (thresholds tuned until known-good FP < 5%)

| game | expectation | scored | garbage | suspect | untextured |
|------|-------------|--------|---------|---------|------------|
| GZLE01 Wind Waker | good | 1856 | 4 (0.2%) | 44 (2.4%) | 78 |
| GALE01 Melee | good | 1495 | 0 (0.0%) | 3 (0.2%) | 148 |
| G6WE69 Tiger Woods 06 | good | 428 | 0 (0.0%) | 14 (3.3%) | 0 |
| GDQE7L Darkened Skye (pre-fix exports) | bad | 2512 | 2 | 6 | 192 |
| GTWE70 Taz (mid-re-rip, bins truncated) | bad | 104 | 0 | 0 | 0 |

Notes and known limits:
- Tiger Woods `*.hog` meshes are exempt from the spaghetti signals (`SPAGHETTI_EXEMPT`): the ter decode is known-plaintext-verified byte-identical, yet its small slabs measure exactly like tangled indices (median edge 0.26-0.33 of the diagonal, isotropic normals). Faithful to source, so not flagged - but if TW terrain ever *looks* wrong in preview, the index topology is the place to dig.
- Folded-pose garbage (pre-fix Darkened Skye skx: right topology, wrong joint frames - crumpled shard-balls) passes every geometric oracle here (median edge ratio 0.07-0.11, connected, finite). Catching it needs pose priors or render-side checks; the skx re-rip makes it moot for GDQE7L.
- Melee-style merged exports (per-part gltf replaced by one merged file, .bin kept) are recognized and skipped, not flagged.
- Models > 500k triangles are scored from metadata only (shared HDD; the rip cascade was running during this audit).

