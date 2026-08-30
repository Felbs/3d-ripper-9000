# Cracked formats - the running ledger

Every GameCube file format gcrip reads, grouped by the studio / engine that produced it.
"Rips" means textured models (and rigs / clips where noted) come out as glTF; "container"
means the archive is opened so the members reach the plugins and the fallback scanner;
"textures" means only the pixel data is understood. Each row names the module that
implements it and the note under [`docs/formats/`](formats/) that documents the byte layout
(the notes are the reverse-engineering record, written as the formats were cracked).

Chart of how these plug into the pipeline: [PIPELINE.md](PIPELINE.md) section 7.


What is **not** cracked yet, with what is blocking each one, is tracked in [OPEN.md](OPEN.md).

> **Writing a container plugin:** `is_container(name, head)` is offered only the first
> `gcrip.classify.SNIFF_BYTES` (64) bytes of a file, at both manifest and rip time.  Detect on
> the magic and validate the directory in `expand`, which gets the whole file - a check that
> reads a field beyond byte 64 silently never fires - see
> [formats/gcrip-plugin-sniff-limit.md](formats/gcrip-plugin-sniff-limit.md).
> A container also needs a no-op `detect`/`extract` pair: `all_plugins()` only registers a
> module that has both, so `is_container`/`expand` alone means the plugin is **never registered**
> and the archive is never expanded.  That is what kept every AFS disc at zero.


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
| EA Sports EBO | NHL 2005/06, NBA Live 2005/06, FIFA 05, FIFA WC 2006, UEFA CL | models + rigs + textures (the sibling `.gsh` shapes: mixed-case `ShpG` tag and a one-image header variant; NBA Short3 open) | `gcrip/plugins/ebo.py`, `gcrip/formats/ebo.py` | same note |
| Capcom RE4 DAS / DRS / UDAS + BIN | Resident Evil 4 | rooms, characters, textures | `gcrip/plugins/re4.py` | |
| Ubisoft Jade `.bf` | BG&E, Prince of Persia x3 | levels, characters, textures | `gcrip/plugins/jade.py` | later Jade (King Kong) open |
| Neversoft PRE | Tony Hawk's Underground | container + models | `gcrip/plugins/neversoft.py` | |
| Criterion RenderWare DFF / TXD / BSP, `.one`, HIP/HOP | Sonic Heroes, Shadow the Hedgehog, Heavy Iron titles, Bloody Roar, D.O.N | models, worlds, textures | `gcrip/plugins/renderware.py`, `gcrip/formats/one.py`, `rwstream.py`, `rwgc.py` | Shadow's `One Ver 0.60` in [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| Radical Pure3D (`P3DZ` LZR, RCF archives) | Simpsons Hit & Run / Road Rage, Hulk x2, Crash Tag Team Racing, Dark Summit, Godzilla, Monsters Inc | meshes, skeletons, DDS/PNG textures (skin weights open) | `gcrip/plugins/p3d.py`, `rcf.py`, `gcrip/formats/p3d.py`, `lzr.py`, `rcf.py`, `dds.py` | [formats/radical-pure3d-gamecube.md](formats/radical-pure3d-gamecube.md) |
| Nintendo U8 archives (`.arc`: `55 AA 38 2D`, 12-byte nodes + string table) | Harvest Moon: A Wonderful Life / Another Wonderful Life, F-Zero GX (`vehicle_parts/parts_all.arc`), Swingerz Golf, Ultimate Muscle, One Piece: Treasure Battle - 12 discs, 1,414 archives | expanded as a container, members keep their in-archive paths (`gcrip/plugins/u8.py`, `gcrip/formats/u8.py`) | [formats/u8-and-loose-textures.md](formats/u8-and-loose-textures.md) |
| Loose RenderWare textures (`.dds` / `.tga` / `.tgx` named after the material) | MLB SlugFest 2003 / 2004, Outlaw Golf, RedCard 2003 | bound by `gcrip/plugins/renderware.py` through the new `gcrip/formats/tga.py` (SlugFest 0 -> 100% textured, Outlaw Golf 0 -> 92%) | [formats/u8-and-loose-textures.md](formats/u8-and-loose-textures.md) |
| Plain ZIP game data | Alien Hominid, Freedom Fighters, Hitman 2, NFL Blitz 2002 / 2003, Powerpuff Girls, Wallace & Gromit, X-Men Legends (8 discs) | expanded as a container (`gcrip/plugins/zip.py`); members are per-game formats (`.brec`, `.ovl`, `.igb`) | [formats/backlog-map.md](formats/backlog-map.md) |
| THQ `pack` archives | Avatar: The Last Airbender | named members and nested packs (`gcrip/formats/thq_pack.py`); the `rad0` objects inside are open | [formats/backlog-map.md](formats/backlog-map.md) |
| `res` resource files (tagged sections, end-of-file directory) | Digimon Rumble Arena 2, Lemony Snicket, Samurai Jack: The Shadow of Aku (3,804 files) | split into labelled sections by `gcrip/plugins/res.py`; **`surf` textures decode** (`gcrip/formats/res_surf.py`: GX C4/C8 with an `RGB565` palette, mip levels at +11, tile-padded chain) - 532 of 553 sections on Samurai Jack; `rdms` meshes still to decode | [formats/backlog-map.md](formats/backlog-map.md) |
| Nintendo `TPL` textures, loose or embedded | everywhere; Mega Man X: Command Mission wraps one in a 32-byte header in each of 1,467 `.arc` | textures - gcrip has read TPL for years but only from inside game-specific plugins, so a loose or wrapped one was claimed by nothing.  `tpl.parse(data, base)` resolves every internal offset against the base | `gcrip/plugins/tpl.py`, `gcrip/formats/tpl.py`, `tpl_hvs.py` | [formats/capcom-arc-tpl.md](formats/capcom-arc-tpl.md) |
| `MDGC0200` blocks | Superman: Shadow of Apokolips (255 `.dgc`) | models: block type `0x1007`, a 64-byte header giving the vertex count and the offsets of a **GX display list**, the RGBA colours and the s8 normals; the list draws indexed triangle strips (position, colour and normal index per corner).  **947 meshes, 89,023 vertices, 130,937 triangles** | `gcrip/plugins/mdgc.py`, `gcrip/formats/mdgc.py` | [formats/superman-mdgc.md](formats/superman-mdgc.md) |
| `.jam` archives - three formats: `FSTA` (High Voltage, members open `HVSI`), `JAM2`, `LJAM` | Billy & Mandy + Kids Next Door (`FSTA`, 155 files), Charlie and the Chocolate Factory, Hunter: The Reckoning | `FSTA` expands (`gcrip/plugins/fsta.py`): members come out as `<name>.<ext>` - 477 from 20 archives on Billy & Mandy.  its `TPL` members are a High Voltage variant - extra `u32` at +8, image headers inline in the table at 0x2c stride - read by `gcrip/formats/tpl_hvs.py`, and loose stock TPLs anywhere are now claimed by `gcrip/plugins/tpl.py` | | [formats/jam-fsta-hvs.md](formats/jam-fsta-hvs.md) |
| `XMDL` / `NTGC` models (sections `MDEL`, `MATR`, `TXNM`, `GRPV`, `VRTX`, `INDX`; 32-byte big-endian f32 vertex) | Home Run King (`data.afs`: 69 members) | models - **6,273 models, 199,226 vertices, 155,356 triangles** | `gcrip/plugins/xmdl.py`, `gcrip/formats/xmdl.py` | [formats/afs-inner-formats.md](formats/afs-inner-formats.md) |
| Byte-swapped DDS texture packs (GX `CMPR` behind a big-endian DDS header, fourcc stored reversed as `1TXD`) | Home Run King (`data.afs`: 236 members, ~118 textures each) | textures | `gcrip/plugins/dds_pack.py`, `gcrip/formats/dds_pack.py` | [formats/afs-inner-formats.md](formats/afs-inner-formats.md) |
| Terminal Reality POD2 / POD3 archives | BloodRayne, Blowout, RoadKill (POD3), 4x4 Evo 2 (POD2) - 38 archives, 19,678 members | expanded as a container (`gcrip/plugins/pod.py`, `gcrip/formats/pod.py`); the `.bst` / `.bqs` models, `.tex` textures and `.pkg` packages inside are open | [formats/terminal-reality-pod.md](formats/terminal-reality-pod.md) |
| Terminal Reality `.TEX` textures | BloodRayne (3,685 / 3,785), Blowout (787 / 787) | textures: GX `CMPR` (code 11) and `C8` + 256-entry `RGB5A3` palette (code 19); the header is 24 bytes in version 2 and 28 in version 3 | `gcrip/plugins/tr_tex.py`, `gcrip/formats/tr_tex.py` | [formats/terminal-reality-pod.md](formats/terminal-reality-pod.md) |
| Terminal Reality `.PKG` packages | BloodRayne, Blowout, RoadKill | named chunks: `1tex` textures, `_smf` static meshes, `_dfm` skinned meshes, `_skl` skeletons, `smpl` audio (18/18 sampled packages walk clean to the `NoMo` terminator; 3,199 / 3,262 textures decode) | `gcrip/plugins/tr_pkg.py`, `gcrip/formats/tr_pkg.py` | [formats/terminal-reality-pod.md](formats/terminal-reality-pod.md) |
| Terminal Reality `_smf` static meshes | Blowout (v7), BloodRayne (v4), RoadKill (v6) | models: GX display lists with INLINE vertices (quad opcode `0x84`); v7 is a 13-byte vertex (s16 pos * 2^-8, s8 normal, s16 uv), v4 a 16-byte one (s16 pos * 2^-15, Q1.14 s16 normal, u16 uv); degenerate triangles dropped and winding fixed from the stored normals | `gcrip/plugins/tr_smf.py`, `gcrip/formats/tr_smf.py` | [formats/terminal-reality-pod.md](formats/terminal-reality-pod.md) |  v6 is the indexed form of the same vertex (arrays + big-endian u16 indices) with a per-mesh power-of-two position scale taken from the stored bounding box.  Blowout's `_dfm` rigid-part characters remain open.
| Blitz `.gcp` packs | Pac-Man World 3, Bratz, Bad Boys, Chicken Little, ... (9) | archive directory cracked: 337 named per-level members (0x800-sector offsets + byte sizes), members split into stamped packages; object stream read by `gcrip/formats/blitz_obj.py` (tag 0x00 carries a byte rather than ending the stream - walks 99.7% of a pack); level packs are scene graphs, naming assets and navigation meshes, the 1,121 stampless `common_*` packs carry chained texture descriptors (`width | height | format | 0x101 | 0 | 0xff000000 | width*height` at 0x820); read by `gcrip/plugins/blitz_tex.py`: a chain of 160-byte descriptors from 0x820, each followed by its pixels - format 15 is GX `RGBA8`, 21 is GX `CMPR` (17 and 19 undecoded). Verified on Bratz: Rock Angelz and Fairly OddParents: Shadow Showdown, both previously at zero textures | `gcrip/plugins/blitz.py`, `gcrip/formats/blitz_gcp.py` | [formats/blitz-gcp-gamecube.md](formats/blitz-gcp-gamecube.md) |
| Krome RKV v1 + MDL2 `.gmd` + `.gtx` | Ty the Tasmanian Tiger | models, two-bone skins, textures | `gcrip/plugins/rkv.py`, `mdl2.py`, `gcrip/formats/rkv.py`, `mdl2.py` | [formats/krome-mdl2-gamecube.md](formats/krome-mdl2-gamecube.md) |
| Krome RKV2 + MDL3 / MDG3 + `.tex` | Ty 2, Ty 3, Spyro: A New Beginning, King Arthur | models, two-bone skins, textures | `gcrip/plugins/mdl3.py`, `gcrip/formats/mdl3.py` | same note |
| Eighting FPK + PRS (GNTool variant) | Naruto CoN 1-2, GNT 3-4, Bloody Roar PF, Zatch Bell x2, Battle Stadium D.O.N | container -> HSD / RenderWare models | `gcrip/plugins/fpk.py`, `gcrip/formats/fpk.py` | [formats/eighting-fpk-gamecube.md](formats/eighting-fpk-gamecube.md) |
| Eurocom EngineX Filelist + GEOM `.edb` (v170-252) | Sphinx, Buffy, Spyro: A Hero's Tail, Robots, Batman Begins, Ice Age 2 | meshes, textures, assembled levels (map placements: 256 maps, 24,799 placements, 6.29M triangles, 5,988,747 triangles); rigs / map zones open | `gcrip/plugins/eurocom.py`, `gcrip/formats/eurocom.py` | [formats/eurocom-enginex-gamecube.md](formats/eurocom-enginex-gamecube.md) |
| Hudson `.bin` archives + HSF | Mario Party 4-7 | rigged, skinned models, textures | `gcrip/plugins/mpbin.py`, `hsf.py`, `gcrip/formats/mpbin.py`, `hsf.py` | [formats/hudson-hsf-gamecube.md](formats/hudson-hsf-gamecube.md) |
| Sega PRS, SA2B chunk models (big-endian Ninja), GVM / GVR | Sonic Adventure 2: Battle | rigged characters, textures (stages open) | `gcrip/plugins/segaprs.py`, `sa2b.py`, `gvm.py`, `gcrip/formats/prs.py`, `sa2b.py`, `gvr.py` | [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| Nintendo REL modules + SA Tools split tables: SADX Basic models / land tables, SA2B stage land tables (Ginja) | Sonic Adventure DX, Sonic Adventure 2: Battle stages | characters rigged, stages textured (SADX stage textures open) | `gcrip/plugins/sadx.py`, `gcrip/formats/rel.py`, `satools.py`, `sadx.py`, `gcrip/data/satools/` | [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| PSO BML, NJCM (GC order), GJCM "Ginja" | Phantasy Star Online Ep I & II (+ Plus) | rigged models, textures (`.rel` levels open) | `gcrip/plugins/bml.py`, `ninja_gc.py`, `gcrip/formats/bml.py`, `ginja.py` | same note |
| Traveller's Tales NU2 vertex stream (`03 01 00 01` blocks in NU20 `.gsc` / `.csc`) | LEGO Star Wars: The Video Game (chars + levels), Bionicle Heroes cutscene scenes | meshes with UVs, normals, colours (materials / textures open) | `gcrip/plugins/nu2.py`, `gcrip/formats/nu2.py` | [formats/tt-nu2-gamecube.md](formats/tt-nu2-gamecube.md) |
| Dreamcast Ninja (NJ / NJCM / NJBM, PVR, AFS, PRS) | Dreamcast library (dcrip) | rigged models, clips | `dcrip/` | |

## Universal fallback

| Layer | What it does | Modules | Notes |
| --- | --- | --- | --- |
| Structure-based archives + zlib / LZ10 / LZ11 / LZSS | opens unknown tables and streams so real plugins see what is inside (never inside a real plugin's archive) | `gcrip/plugins/generic.py`, `gcrip/formats/generic.py` | [formats/library-fallbacks-2026-08-28.md](formats/library-fallbacks-2026-08-28.md) |
| GX display-list scanner | raw meshes from any file that stores GX display lists + vertex arrays | `gcrip/plugins/gx.py`, `gcrip/gxscan.py` | same note |

## Mapped, not decoded yet

| Studio / engine | Games | State | Notes |
| --- | --- | --- | --- |
| Ubisoft UE2 GameCube builds (`.umd` zlib archives of Unreal packages, `.lin`) | Splinter Cell x3 (5 dumps), Rainbow Six 3, Ghost Recon 2, XIII | Pandora Tomorrow rips (meshes, textures, assembled levels); the other titles' bundles are still being mapped | [formats/ubisoft-gamecube.md](formats/ubisoft-gamecube.md) |
| Ubisoft OpenSpace / CPA (`.lvl` + `.ptr`) | Rayman 3, Rayman Arena | reference loader exists (byvar/raymap) | same note |
| Traveller's Tales later / older variants: LSW2 & Narnia `.gcm`/`.cc2`, SMB Adventure `.chr`/`.chg`, LSW1 `.nus` scenes, `.ghg` | LEGO Star Wars II, Narnia, Crash WoC, Finding Nemo, SMB Adventure | containers seen, vertex encodings differ from the `.gsc` stream | [formats/tt-nu2-gamecube.md](formats/tt-nu2-gamecube.md) |
| Avalanche DBL / DBU / MDB: sub-database records (type byte 0x82 texture tables, 0x67 material lists, 0x2x meshes); a mesh = GX-native arrays (f32 positions, s8 normals, f32 uvs) + a list of raw GX FIFO display lists (index rows laid out by the stream's own VCD loads, per-DL material index + bone ids); textures CI4 / CI8 (RGB5A3 palette at the entry's palette offset), CMPR, RGBA8 | Tak and the Power of Juju, Tak 2, Tak: The Great Juju Challenge, Chicken Little, Dragon Ball Z: Sagas, Rugrats: Royal Ransom | ripped through `plugins/dbl.py` + `formats/dbl_mesh.py`; open: skeletons / skinning (only bone ids per DL) | [formats/avalanche-dbl-gamecube.md](formats/avalanche-dbl-gamecube.md) |
| Billy Hatcher `.prd` (PRS + `U:8-` archive), `.arc` (Ninja object trees with Ginja attaches, skin sets into the GX vertex cache, embedded / sibling GVM), `.lnd` (stage terrain: vertex pool + GX display lists) | Billy Hatcher and the Giant Egg | ripped - rigged characters, enemies, items, stage objects, terrain, textures (`plugins/billy.py`); the 79 `.lnd` terrain files were never detected until 2026-08-30 - `is_lnd` wanted 96 bytes and `detect` gets 64 ([formats/gcrip-plugin-sniff-limit.md](formats/gcrip-plugin-sniff-limit.md)); motions (`ge_player.arc`) open | [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| Sega PSO `.rel` levels, Sonic Riders `80 00 00 01` containers | PSO, Sonic Riders | containers mapped | [formats/sonic-team-gamecube.md](formats/sonic-team-gamecube.md) |
| Traveller's Tales GameCube `DISP` display programs: `.csc` scenes / levels (big-endian NU2, reversed tags), `.chg` characters (skeleton wrapper), `.fpk` / `.cpk` packs | LEGO Star Wars II, The Chronicles of Narnia | ripped - textured meshes, vertex colours, level instancing, rigid-skinned LEGO characters (`plugins/ttdisp.py`); Narnia `.chg` skinning and `.hgo` (Crash WoC / Finding Nemo) open | [formats/tt-nu2-gamecube.md](formats/tt-nu2-gamecube.md) |
| Traveller's Tales reversed-tag NU2 (`FOGH` / `0CSG` trees, big-endian sizes): `.hgo` characters (HGO0: node matrices, meshes of `u32 blocks | u32 material | u32 count` + 28 / 36-byte f32 vertices `xyz | normal | RGBA | [uv]`, index groups prim 5 list / 6 strip, per-vertex skin `3 f32 weights + 4 bone ids`), `.nus` levels (GST0 meshes + INST 4x4 placements), TXM0 textures (0x80 CMPR, 0x81 RGB5A3), MS00 / MS03 materials | Crash Bandicoot: The Wrath of Cortex, Finding Nemo | ripped through `plugins/hgo.py` + `formats/hgo.py` (bind pose, flat joints; the Nemo levels use normal-less vertices and raw GX display lists; node hierarchy / bind matrices and unskinned part transforms open) | [formats/tt-nu2-gamecube.md](formats/tt-nu2-gamecube.md) |
| Unreal Engine 2 packages (Ubisoft GameCube builds): `.usx` static meshes, `.utx` textures, `.umd` / `.lin` chunked-zlib package archives | Splinter Cell: Pandora Tomorrow (ripping); Splinter Cell 1 / Chaos Theory / Double Agent, Rainbow Six 3, Ghost Recon 2, XIII (containers + LE tables) | Pandora Tomorrow static meshes, DXT1 / P8 textures and assembled levels rip (`plugins/unreal.py`: every actor with a `StaticMesh` property placed by Location / Rotation / DrawScale over the sibling `.usx` - 34 maps, 11,830 actors, 819k triangles, 0 missing meshes); the `.lin` / `.umd` bundles hold package headers with sequential name / import / export tables and the object data in separate blocks, so SC1 / Chaos Theory / Double Agent / XIII / R6-3 / GR2 still do not rip; BSP (`Model` / `Polys`) not exported | [formats/ubisoft-gamecube.md](formats/ubisoft-gamecube.md) |
| Ubisoft OpenSpace / CPA levels: `.lvl` + `.ptr` relocated memory images, super-object tree, GeometricObjects with GX strip mappings, Nintendo TPL textures | Rayman 3: Hoodlum Havoc, Rayman Arena | ripped - placed level geometry with textures (`plugins/openspace.py`); characters (Perso families / animations) open | [formats/ubisoft-gamecube.md](formats/ubisoft-gamecube.md) |
| Konami TMNT 1-3: `AFS` archives (`TMNT.DAT`, named members), TMNT 2 / 3's `LPAC` packs of named RenderWare streams, little-endian RenderWare 3.x `.dff` clumps / worlds / `.anm`, and Konami texture packs (chunk 0x23: TMNT 1 name table + rwID_IMAGE, TMNT 2 rwID_IMAGE + rwID_TEXTURE) | Teenage Mutant Ninja Turtles 1, 2: Battle Nexus, 3: Mutant Nightmare (5 discs), TMNT: Mutant Melee (`archive.dat` + its `archive.arc` directory) | ripped through `plugins/renderware.py` + `plugins/afs.py` + `plugins/lpac.py` + `formats/konami_pac.py` + `plugins/melee.py` (Mutant Melee: 2,331 rigged scenes / 615k triangles) | [formats/konami-gamecube.md](formats/konami-gamecube.md) |
| Konami others (Frogger, Yu-Gi-Oh FK, Disney Sports, ESPN, Evolution) | 12 | containers seen, one engine per title | [formats/konami-gamecube.md](formats/konami-gamecube.md) |
| Treyarch (Spider-Man 1-2, Ultimate Spider-Man, ...) | 7 | parked by decision | |

Status per disc: [GAME_STATUS.md](GAME_STATUS.md) (regenerated by each dump pass).
