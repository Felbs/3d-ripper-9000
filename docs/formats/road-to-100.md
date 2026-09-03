# The road to 100% - every disc still under 20,000 triangles, by engine (2026-09-03)

An engine census over the **443 discs** still under 20,000 triangles - the biggest low-entropy
file on each, its magic, and which plugin claims it - clusters them into 351 groups.  Most
are singletons.  The ones worth attacking as a group, in return-on-effort order:

| # | engine | discs | GB | state | the way in |
|---|---|---|---|---|---|
| 1 | **EA Tiburon `TERF` + `comp5`** | **14** | 17.5 | **cracked 2026-09-03** - `comp5` is GCMP.LIB `LZH1`, ported from the DOL; `TMdl` models and `MMAP` packs read | re-rip the fourteen (pass 7) - [ea-tiburon-comp5.md](ea-tiburon-comp5.md), [ea-tiburon-tmdl.md](ea-tiburon-tmdl.md) |
| 2 | Capcom `AFS` | 9 | 8.4 | container reads; inner formats per game | [afs-inner-formats.md](afs-inner-formats.md) - Auto Modellista and CvS2 done, seven to go |
| 3 | Sega `.sfd` (MPEG) | 8 | 9.0 | video - **nothing to rip from these files** | the models on those discs are elsewhere: PSO, Sonic Riders, Sonic Mega Collection need their own look |
| 4 | Baten Kaitos (Monolith) | 5 | 6.1 | biggest files are THP video; game data is in unnamed files | survey the non-video files |
| 5 | EA `BIGF` (SSX 3, SSX On Tour, Goblet of Fire, ...) | 5 | 5.5 | container reads; members are EA RenderWare streams | `ea_rws` reads them; find which members hold CLUMP / native geometry |
| 6 | EA `SCHl` audio banks as biggest file (MVP 2004/2005, FIFA Street) | 4 | 3.6 | biggest file is audio | models are in the `.big`/`.viv` beside them - EAGL, already handled on siblings |
| 7 | `BOLT` archives (Muppets Party Cruise, Namco Museum, Shrek Super Party) | 3 | 0.8 | **cracked 2026-09-03** - archive, LZ codec, node tree, meshes and material lists read from Muppets' DWARF ELF; Pac-Man Fever joins (its FST archives are the older 1.3 exporter); Namco Museum is 2D | re-rip (wave 37) - [bolt-mass-media.md](bolt-mass-media.md) |
| 8 | Visual Concepts `DAT` | 3 | 3.7 | codec cracked tonight; census still shows 0 triangles because the members are textures | the `TMdl`-equivalent for VC is unlocated |
| 9 | `ZSND` (Aggressive Inline, Dave Mirra BMX 2, BMX XXX) | 3 | 1.6 | biggest file is sound | Z-Axis engine; models elsewhere on disc |
| 10 | `MPQ` (WWE Day of Reckoning 1/2, WrestleMania XIX) | 3 | 4.0 | unread container (Blizzard MPQ, used by Yuke's) | MPQ reader - documented format, listfile likely absent |
| 11 | zero-magic `.arc` (The Sims, Shark Tale, Over the Hedge; also The Sims 2, Pets, Bustin' Out, The Urbz) | 7 | 2.8+ | **Edge of Reality**: models, textures and shaders read on The Sims 2, Pets, The Sims, Bustin' Out and The Urbz (2026-09-03, from the mapped ELF; datasets opened); Shark Tale / Over the Hedge read too (their record is self-describing GX) | re-rip the seven (waves 38-39) - [edge-of-reality-arc.md](edge-of-reality-arc.md) |
| 12 | `BGIB` `.pss` (Bionicle, I-Ninja) | 2 | 1.0 | Argonaut; `gx` claims it | see what the scanner gives after wave 30 |
| 13 | `cd_bigfile` `.pac` (Captain Tsubasa, Yu-Gi-Oh Falsebound) | 2 | 1.4 | container reads | inner formats |
| 14 | `hff` (Casper, Tonka Rescue Patrol) | 2 | 0.4 | container reads, carves PNG | geometry unread - [hff-carving.md](hff-carving.md) |
| 15 | `FANG` `.mst` (Freaky Flyers) | 2 | 1.3 | unread | survey |
| 16 | `BIG4` (Prisoner of Azkaban, Marvel Nemesis) | 2 | 2.7 | EA `BIG4` variant | check `ea_big` handles the version |
| 17 | Climax `.bad` (Italian Job, ATV Quad Power Racing 2) | 2 | 0.2 | codec cracked; inner container open | [climax-bad.md](climax-bad.md) |

Below these: 351 minus the above is roughly **330 singleton discs**.  Many will resolve as
"no 3D" (compilations, FMV-driven titles, 2D games) and many share an engine that the biggest
file does not reveal.  Each needs a five-minute look at its file list before it can be placed.

## What is NOT in this table, and why

Discs whose biggest file is video or audio are not dead ends - they are discs whose *models*
were not in the census's biggest file.  Rows 3, 4, 6 and 9 are that.  They need a second pass
that ranks files by "looks like geometry" rather than by size.

Tiger Woods 2003-2005 (five discs, not in the table because they were counted under `.hog`) fell the same day: `Rdat` is EA's `rcmp`, also read out of a DOL.

Mortal Kombat: Deception and Deadly Alliance (two singletons - the census saw `.ssf`) fell on 2026-09-03: Midway `SEC` archives of in-place RenderWare, read from Deception's mapped ELF - [mk-ssf-midway.md](mk-ssf-midway.md).

Ultimate Spider-Man and Spider-Man 2 (two singletons - the census saw `amalga_gc.pak`) fell on 2026-09-03: Treyarch NGL, read from Ultimate Spider-Man's full symbol map - [treyarch-ngl-gamecube.md](treyarch-ngl-gamecube.md).

Need for Speed: Underground (a singleton at 962 triangles beside its 7-million-triangle sequel) fell the same day from `Speed.elf`'s DWARF - [ea-black-box-underground.md](ea-black-box-underground.md).

Super Mario Strikers (376 triangles; an ELF with DWARF and three maps) fell the same day - [nlg-strikers-gl.md](nlg-strikers-gl.md).

## Running total

Library: **1,085,308 models / 479.4 M triangles over 637 discs** before wave 30.  Wave 30 is
re-scanning 216 zero-triangle discs with the salvage scanner and is returning small counts
(700 to 4,000 triangles) on discs that had none - the scanner finds *something*, but the
formats above are where the volume is.
