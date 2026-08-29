# Cracked formats - the running ledger

Every GameCube file format gcrip reads, grouped by the studio / engine that produced it.
"Rips" means textured models (and rigs / clips where noted) come out as glTF; "container"
means the archive is opened so the members reach the plugins and the fallback scanner;
"textures" means only the pixel data is understood. Each row names the module that
implements it and the note under [`docs/formats/`](formats/) that documents the byte layout
(the notes are the reverse-engineering record, written as the formats were cracked).

Chart of how these plug into the pipeline: [PIPELINE.md](PIPELINE.md) section 7.

## Nintendo first party and second party

| Engine / format | Games | What we get | Modules | Notes |
| --- | --- | --- | --- | --- |
| J3D (BMD / BDL, BCK / BTK / BRK / ...) | Wind Waker, Mario Sunshine, Mario Kart DD, Pikmin 2, Luigi's Mansion props, Zelda TP, ... | rigs, skins, materials, clips, expressions | `gcrip/formats/j3d*.py`, `gcrip/export` | core pipeline, [PIPELINE.md](PIPELINE.md) |
| RARC / Yaz0 / Yay0 / TGC | most Nintendo discs | container + decompression | `gcrip/formats/rarc.py`, `yaz0.py`, `yay0.py`, `tgc.py` | |
| Retro Studios PAK / CMDL / MREA | Metroid Prime 1 & 2 | models, areas, textures | `gcrip/plugins/retro.py` | |
| HAL sysdolphin `.dat` (HSD) | Smash Melee, Kirby Air Ride, + Eighting's Naruto GNT | JOBJ rigs, meshes, textures, anims | `gcrip/plugins/hsd.py`, `gcrip/formats/hsd.py` | |
| Amusement Vision GMA / TPL / LZ | F-Zero GX, Super Monkey Ball 1-2 | models, textures | `gcrip/plugins/gma.py` | |
| Pikmin `.mod` | Pikmin 1 | rigged models | `gcrip/plugins/pikmin.py` | |
| Luigi's Mansion `.mdl` / `.bin` | Luigi's Mansion | characters, rooms | `gcrip/plugins/lm.py` | |
| Star Fox Adventures MODELS.bin / .tab | Star Fox Adventures | models with skeletons | `gcrip/plugins/sfa.py` | |
| Paper Mario TTYD | Paper Mario: TTYD | models | `gcrip/plugins/ttyd.py` | |
| Fire Emblem PoR pack / LZ10 | Fire Emblem: Path of Radiance | models | `gcrip/plugins/feporr.py` | |
| Wave Race offset bundles | Wave Race: Blue Storm | container | `gcrip/plugins/waverace.py` | |
| TPL / BTI textures, GX pixel formats | everywhere | textures | `gcrip/formats/gx_texture.py`, `tpl.py` | |

## Third-party engines (cracked 2026-08-27 .. 08-29)

| Studio / engine | Games in the library | What we get | Modules | Notes |
| --- | --- | --- | --- | --- |
| EA BIG / VIV / RefPack, Tiburon TERF, Black Box ZZDATA | ~70 EA discs | container | `gcrip/plugins/ea.py` | [formats/ea-eagl-gamecube.md](formats/ea-eagl-gamecube.md) |
| EA Canada EAGL (`.ord` + `.orp` ELF) | FIFA 2002-2004, NBA Live 2003-04, NHL 2003-04, MVP, Def Jam, Fight Night, SSX | rigged, skinned models; textures from SHPG `.gsh` | `gcrip/plugins/eagl.py`, `gcrip/formats/eagl.py` | same note |
| EA Sports EBO | NHL 2005/06, NBA Live 2005/06, FIFA 05, FIFA WC 2006, UEFA CL | models + rigs (NBA Short3 open) | `gcrip/plugins/ebo.py`, `gcrip/formats/ebo.py` | same note |
| Capcom RE4 DAS / DRS / UDAS + BIN | Resident Evil 4 | rooms, characters, textures | `gcrip/plugins/re4.py` | |
| Ubisoft Jade `.bf` | BG&E, Prince of Persia x3 | levels, characters, textures | `gcrip/plugins/jade.py` | later Jade (King Kong) open |
| Neversoft PRE | Tony Hawk's Underground | container + models | `gcrip/plugins/neversoft.py` | |
| Criterion RenderWare DFF / TXD / BSP, `.one`, HIP/HOP | Sonic Heroes, Shadow the Hedgehog, Heavy Iron titles, Bloody Roar, D.O.N | models, worlds, textures | `gcrip/plugins/renderware.py`, `gcrip/formats/one.py`, `rwstream.py`, `rwgc.py` | Shadow's `One Ver 0.60` in [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| Radical Pure3D (`P3DZ` LZR, RCF archives) | Simpsons Hit & Run / Road Rage, Hulk x2, Crash Tag Team Racing, Dark Summit, Godzilla, Monsters Inc | meshes, skeletons, DDS/PNG textures (skin weights open) | `gcrip/plugins/p3d.py`, `rcf.py`, `gcrip/formats/p3d.py`, `lzr.py`, `rcf.py`, `dds.py` | [formats/radical-pure3d-gamecube.md](formats/radical-pure3d-gamecube.md) |
| Blitz `.gcp` packs | Pac-Man World 3, Bratz, Bad Boys, Chicken Little, ... (9) | container only (object stream open) | `gcrip/plugins/blitz.py` | [formats/blitz-gcp-gamecube.md](formats/blitz-gcp-gamecube.md) |
| Krome RKV v1 + MDL2 `.gmd` + `.gtx` | Ty the Tasmanian Tiger | models, two-bone skins, textures | `gcrip/plugins/rkv.py`, `mdl2.py`, `gcrip/formats/rkv.py`, `mdl2.py` | [formats/krome-mdl2-gamecube.md](formats/krome-mdl2-gamecube.md) |
| Krome RKV2 + MDL3 / MDG3 + `.tex` | Ty 2, Ty 3, Spyro: A New Beginning, King Arthur | models, two-bone skins, textures | `gcrip/plugins/mdl3.py`, `gcrip/formats/mdl3.py` | same note |
| Eighting FPK + PRS (GNTool variant) | Naruto CoN 1-2, GNT 3-4, Bloody Roar PF, Zatch Bell x2, Battle Stadium D.O.N | container -> HSD / RenderWare models | `gcrip/plugins/fpk.py`, `gcrip/formats/fpk.py` | [formats/eighting-fpk-gamecube.md](formats/eighting-fpk-gamecube.md) |
| Eurocom EngineX Filelist + GEOM `.edb` (v170-252) | Sphinx, Buffy, Spyro: A Hero's Tail, Robots, Batman Begins, Ice Age 2 | meshes, textures (rigs open) | `gcrip/plugins/eurocom.py`, `gcrip/formats/eurocom.py` | [formats/eurocom-enginex-gamecube.md](formats/eurocom-enginex-gamecube.md) |
| Hudson `.bin` archives + HSF | Mario Party 4-7 | rigged, skinned models, textures | `gcrip/plugins/mpbin.py`, `hsf.py`, `gcrip/formats/mpbin.py`, `hsf.py` | [formats/hudson-hsf-gamecube.md](formats/hudson-hsf-gamecube.md) |
| Sega PRS, SA2B chunk models (big-endian Ninja), GVM / GVR | Sonic Adventure 2: Battle | rigged characters, textures (stages open) | `gcrip/plugins/segaprs.py`, `sa2b.py`, `gvm.py`, `gcrip/formats/prs.py`, `sa2b.py`, `gvr.py` | [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| Nintendo REL modules + SA Tools split tables: SADX Basic models / land tables, SA2B stage land tables (Ginja) | Sonic Adventure DX, Sonic Adventure 2: Battle stages | characters rigged, stages textured (SADX stage textures open) | `gcrip/plugins/sadx.py`, `gcrip/formats/rel.py`, `satools.py`, `sadx.py`, `gcrip/data/satools/` | [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| PSO BML, NJCM (GC order), GJCM "Ginja" | Phantasy Star Online Ep I & II (+ Plus) | rigged models, textures (`.rel` levels open) | `gcrip/plugins/bml.py`, `ninja_gc.py`, `gcrip/formats/bml.py`, `ginja.py` | same note |
| Dreamcast Ninja (NJ / NJCM / NJBM, PVR, AFS, PRS) | Dreamcast library (dcrip) | rigged models, clips | `dcrip/` | |

## Universal fallback

| Layer | What it does | Modules | Notes |
| --- | --- | --- | --- |
| Structure-based archives + zlib / LZ10 / LZ11 / LZSS | opens unknown tables and streams so real plugins see what is inside (never inside a real plugin's archive) | `gcrip/plugins/generic.py`, `gcrip/formats/generic.py` | [formats/library-fallbacks-2026-08-28.md](formats/library-fallbacks-2026-08-28.md) |
| GX display-list scanner | raw meshes from any file that stores GX display lists + vertex arrays | `gcrip/plugins/gx.py`, `gcrip/gxscan.py` | same note |

## Mapped, not decoded yet

| Studio / engine | Games | State | Notes |
| --- | --- | --- | --- |
| Ubisoft UE2 GameCube builds (`.umd` zlib archives of Unreal packages, `.lin`) | Splinter Cell x3 (5 dumps), Rainbow Six 3, Ghost Recon 2, XIII | containers understood, package reader needed | [formats/ubisoft-gamecube.md](formats/ubisoft-gamecube.md) |
| Ubisoft OpenSpace / CPA (`.lvl` + `.ptr`) | Rayman 3, Rayman Arena | reference loader exists (byvar/raymap) | same note |
| Traveller's Tales NU2 (NU20 chunks, `.ghg`) | LEGO Star Wars 1-2, Crash WoC, Finding Nemo, SMB Adventure, Narnia, Bionicle Heroes | chunk tree mapped, OBJ0 mesh records open | [formats/tt-nu2-gamecube.md](formats/tt-nu2-gamecube.md) |
| Avalanche DBL / DBU | Tak 1-3, Chicken Little, DBZ Sagas, Rugrats | container + texture records mapped | [formats/avalanche-dbl-gamecube.md](formats/avalanche-dbl-gamecube.md) |
| Sega PSO `.rel` levels, Billy Hatcher `.prd`/`.arc` (PRS + `U:8-` archives of Ginja objects), Sonic Riders `80 00 00 01` containers | PSO, Billy Hatcher, Sonic Riders | containers mapped | [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| Treyarch (Spider-Man 1-2, Ultimate Spider-Man, ...) | 7 | parked by decision | |

Status per disc: [GAME_STATUS.md](GAME_STATUS.md) (regenerated by each dump pass).
