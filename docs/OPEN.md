# Open formats - what is left to crack

Live list, updated as work happens.  Ordered by return: discs affected first, then how close it
is to falling.  A format only leaves this list when it ships and a real disc yields models or
textures through the plugin chain.

Companion to [FORMATS.md](FORMATS.md), which lists what already works.

## Closed 2026-09-03: Smashing Drive (Point of View `PHM` / `TG_` layouts)

A zero-triangle disc with a DWARF `smash.elf`: `s_model` is the file, so the reader is a
transcription - 44-byte f32 vertices, u32 index lists (u16 was the trap: every triangle
touched vertex 0), 8-byte strip commands, materials mapping texture defs to the `TIM`
records.  The `TG_<phase>` layout (no symbols) places props and traffic by the wad record
id; the buildings sit in world space unplaced.  Ten phases, 63k-196k triangles each.  See
[formats/pov-smashing-drive.md](formats/pov-smashing-drive.md).  Left: Spawn / Scorpion
King's older `s_model` versions could take the same header table.

## Closed 2026-09-03: EA Tiburon `comp5` - fourteen discs

The largest cluster in the road-to-100 census fell by reading the game's own decompressor out
of Madden 06's DOL: `comp5` is codec five of EA's `GCMP.LIB` (`NONE`, `RLE1`, `HUFF`, `LZM1`,
**`LZH1`**), an MSB-first LZ+Huffman with deflate's tables and an Adler-32 trailer.  Behind it
are `TMdl` (`.ea3`) models - stadiums, props, sky domes - and named `MMAP` texture packs, both
read now.  Madden 06's `STADATA.DAT` alone goes from 0 to 194 models / 35,217 triangles / 251
textures through the plugin chain.  [formats/ea-tiburon-comp5.md](formats/ea-tiburon-comp5.md),
[formats/ea-tiburon-tmdl.md](formats/ea-tiburon-tmdl.md).  Still open on those discs: the
stadium crowd-quad block, `Swap` chains, and whatever `PLADATA` / `PLYRFACE` turn out to be.

**The lesson generalises**: a private bit-level codec is not a dead end when the disc ships the
decoder.  Score the DOL's functions for shifts + byte loads + loops - calls, follow the
zero-caller hits to their vtable, and the codec's *name* is usually sitting next to it.  The
same route closed Tiger Woods `Rdat` the same day and closed Frogger `PRS1` too; High Voltage `GMS` turned out to be audio and the models (`GGG`) were readable without any codec.

## Closed 2026-09-03: EAGL 2004 generation (Def Jam: Fight for NY, NBA Street V3)

The `.o` objects the rip skipped are EAGL packets with f32 streams and a display list behind a
`ff ff 00 00` preamble; `_decode_packet_v2` reads them (40 of 55 sampled objects, 8.5k
triangles, T-posed clothing).  FFNY alone has 14,953 of them.  See the closing section of
[formats/ea-eagl-gamecube.md](formats/ea-eagl-gamecube.md).  Also found: NBA Street, NBA
Street V3, SSX 3 and Goblet of Fire were ripped before the EAGL `.orl` fix of 09-01 - stale
rows, queued for wave 36.

## Closed 2026-09-03: Blitz Games `.gcp` actors - nine discs

Bratz: Rock Angelz ships an ELF with full DWARF debug info, and the engine's own struct
layouts (`_TBPackageIndex`, `_TBActor`, `_TBMesh`, `_TBTexture` ...) read straight out of it.
The packs have a resource index naming every actor and texture; actors are GX display lists
over indexed arrays or prim-vertex streams.  27 packs: 107 actors, 107k triangles, 458
textures bound, a textured Bratz NPC with a 30-joint skeleton.  See the closing section of
[formats/blitz-gcp-gamecube.md](formats/blitz-gcp-gamecube.md).  **When a disc ships debug
symbols, read them before anything else.**

## Closed 2026-09-03: Mass Media `BOLT` - Muppets Party Cruise, Shrek Super Party, Pac-Man Fever

Muppets ships `Muppets.elf` with DWARF; the archive structs, `MMI::Decompress` (a prefix-byte
LZ), `LoadNode`, `MESH::Load` and `LoadMaterials` were all read from it, then re-found in the
Shrek and Pac-Man DOLs, which turned out to be two more exporter generations (1.9.18 with a
flat material record; 1.3.10 with flag-chained nodes and float arrays).  Three Muppets archives
give 238 models / 16k triangles with every one of 436 textures bound.  See
[formats/bolt-mass-media.md](formats/bolt-mass-media.md).  Left: Pac-Man Fever's real game
data lives outside the FST (scan the image for `BOLT`), skinned meshes, animations.

## Closed 2026-09-03: Medal of Honor: Frontline

EA LA's 2002 engine, read from the shipped ELF's symbols: `.msh` static meshes and `.cpt`
level compartments over GX arrays with the display-list headers filled in at load, materials
as embedded `SHPG` shapes, compartments sharing the level's art file.  One level: 132k
triangles, 1,172 of 1,289 materials textured.  See
[formats/ea-la-frontline.md](formats/ea-la-frontline.md).  The `.dmf` characters followed the same day: cluster frames rebuilt from the `.skl` and the mesh's rest angles (`DMClusterSynthesizeMatrices`), textures from the `TPAC` packs - a 1.48 m soldier in a T-pose.  Left: joints for the skin.

## Closed 2026-09-03: Scooby-Doo! Mystery Mayhem

A2M's 2003 engine over RenderWare: the `.gcr` level archive is a `DTStreamFAT`
(`EFRessourcesMgr::LoadLevel` in the shipped `engine_ret.elf` + `.MAP`; class ids from the
`RegisterDynamicClass` calls) whose class-24 record is the RW world and class-91 records the
clumps; the `TEXDIC_*.txd` beside it is a run of RW IMAGE chunks with names, not a texture
dictionary.  One level: 102 scenes, 77,715 triangles, 188 of 240 materials textured.  See
[formats/a2m-gcr.md](formats/a2m-gcr.md).  Scaler and Scooby-Doo! Unmasked (2004-05) are
the next engine - closed the same day, below.

## Closed 2026-09-03: the Nintendo SDK character pipeline (`.gpl`)

Nine discs kept the Dolphin SDK's own `GeoPalette` / `DisplayObject` files: Harvest Moon
A Wonderful Life and Another Wonderful Life, Zatch Bell! Mamodo Fury, Def Jam Vendetta (a
disc that reported zero triangles), Doshin the Giant, Ultimate Muscle, Swingerz Golf,
PoolEdge and Universal Studios Theme Parks Adventure.  Display-object-relative pointers,
quantised arrays, the vertex descriptor in a display state (its id moved between SDK
versions), GX lists under the states set so far.  See
[formats/nintendo-gpl.md](formats/nintendo-gpl.md).  Left: `.act` actors placing the
parts (Def Jam's wrestlers are one palette a limb), Lotus Challenge's Kuju layout.

## Closed 2026-09-03: Scooby-Doo! Unmasked, Scaler

A2M's 2004-05 `HG` layer: the `.ghr` level archive's `EF3dObjRes` / `EFStatic3dObj` records
are `DTBinaryPersistStream` serialisations, transcribed field by field from the symbol-named
loaders in `engine_ret.elf` (`Load3dObj`, `ImportSubSurfaces`, `ReadVertex`,
`EFStatic3dObj::LoadFromStream`, the PVS and env-clone readers in front of the static
container); textures from the `.htd` dictionaries.  60-80 scenes and 60-67k triangles a
level, ~90% textured, characters with bones and weights.  See
[formats/a2m-hg.md](formats/a2m-hg.md).  Left: env-clone placements,
`EFDynamicGeometryMgr` models, the `.as` streams.

## Closed 2026-09-03: Medal of Honor: Rising Sun, GoldenEye: Rogue Agent

EA LA's 2003-04 EAGL packets: streams indexed separately, element sizes from the pointer
gaps, the display list found behind the last stream and checked against the header's corner
count; the wrapped ELFs joined with their tails from `symbols.rtc` / the compartment `.rtc`
(`TLT_GetRelocationTable` in the shipped ELFs).  One Rising Sun level: 30 scenes, 48k
triangles, 94% of primitives textured.  See the closing section of
[formats/ea-la-frontline.md](formats/ea-la-frontline.md).  Left: the `Human.skel.o`
skeleton header, the shared texture file half a compartment's materials name.

## Closed 2026-09-03: Super Mario Strikers

Next Level Games' GL layer, read from the shipped `MarioSoccerR.elf` (the DOL matches none
of the three maps, so the ELF was disassembled directly): `.glg` chunk units of packets
over shared-index streams, `.glt` `PTLG` bundles.  Mario 4,909 triangles, Mario Stadium
45,366 with 75 of 75 textures.  See [formats/nlg-strikers-gl.md](formats/nlg-strikers-gl.md).
Left: skinning (bind pose ships), lightmap slot.

## Closed 2026-09-03: Need for Speed: Underground

The 2003 Black Box build differs from Underground 2 in two places the existing reader
guessed at: a strip corner is four indices (u8, or u16 when the entry's VertexDescription
is 1) and the texture pack's stream entries are 20 bytes with record-described JDLZ streams.
Both read out of `Speed.elf` (DWARF 1 + 17,000 symbols).  Supra: 76,109 triangles, 51 of 51
textures.  See [formats/ea-black-box-underground.md](formats/ea-black-box-underground.md).

## Closed 2026-09-03: Treyarch NGL - Ultimate Spider-Man and Spider-Man 2

Ultimate Spider-Man's `symbolgc-final.map` names every function in the DOL, so the one
archive that holds the whole game (`amalga_gc.pak`) was read loader by loader: the
amalgapak directory, each pack's "mashed" resource directory, the `GCNM` mesh files with
their per-display-list VCDs and index rebasing, `GCNT` textures, `.IFL` frame lists and the
`FastSkinS16` CPU-skinning bytecode (replayed to recover bones and weights; Spider-Man
comes out in T-pose over 66 joints).  Spider-Man 2 is the same engine a generation earlier.
See [formats/treyarch-ngl-gamecube.md](formats/treyarch-ngl-gamecube.md).  Left: the
procedural city buildings (not meshes), morphs, animations, the skeleton hierarchy.

## Closed 2026-09-03: Mortal Kombat: Deception and Deadly Alliance (`SEC` `.ssf`)

Deception's ELF has a linker map: `load_ssf` / `get_ssf_dir_entry` gave the directory, and
`RpGameCubeVtxFmtSetTexCoord(S16, 11)` the texcoord fraction the streams leave at 0.  The
members are RenderWare, written Midway's way - the geometry struct declared around its own
material list and native data, `PAD32` text inside the counted sizes, and on Deadly Alliance a
big-endian RW 3.2 payload.  The shared RenderWare reader now takes all three.  Sampled: The
Pit 17,868 triangles / 28 of 28 textures, Scorpion's costume skinned over 56 joints, Deadly
Alliance's grasslands 14,806 / 9 of 9.  See [formats/mk-ssf-midway.md](formats/mk-ssf-midway.md).

## Closed 2026-09-03: Edge of Reality models on The Sims 2 and Pets

The Sims 2 ships its ELF with a linker map.  `ERModel::LoadModel`, the strip readers, the
texture creator and the shader definition were read by name; models are strips over packed
s16 arrays (or GX display lists), textures are GX-tiled CMPR / C4 / C8 / RGBA8 whose 32-bit
palettes are two IA8 TLUTs on disc, shaders bind textures by name hash.  3,631 + 5,475 models
across the two discs, then the `Datasets` packs of The Sims, Bustin' Out and The Urbz opened
the same day (three layouts, per-game wrappers, the same strips).  See the closing sections of
[formats/edge-of-reality-arc.md](formats/edge-of-reality-arc.md).  Shark Tale and Over the Hedge
followed: their record is self-describing GX (CP strides in the display list) and reads
without the DOL.  Seven discs on one engine.

## Close - one focused session each

| format | discs | state | what is blocking |
|---|---|---|---|
| EA content on Tiger Woods 2003 / 2004 / 2005 | 6 | **closed 2026-09-03** - `Rdat` is EA's `rcmp` LZ, read out of the 2005 DOL (`gcrip/formats/ea_rcmp.py`); one 2005 hole yields 428k triangles + 95 textures through `shoc` -> `ea_obg` / `ea_txg`.  See the closing section of [formats/ea-shoc-hog.md](formats/ea-shoc-hog.md) | re-rip the five discs (wave 32) |
| `.adb` | 11 | **low value, do not size it by file count.**  14 large `Sounds.adb` on the Acclaim discs (200-660 MB, ascending `u32` offset table, no recognised magic in the first member) whose discs are already served by `asb_tex`; and 411 tiny ones elsewhere - Shadow the Hedgehog's 364 total 0.1 MB, about 300 bytes each | see [formats/dgc-adb-survey.md](formats/dgc-adb-survey.md) |
| Pac-Man Fever data outside the FST | 1 | the FST lists three `.BLT` (two of them 1.3 leftovers the DOL cannot read); the DOL opens `BoardGam`, `DataHUD` ... by name from the raw disc - 300 MB the manifest never sees | scan the image for `BOLT` headers when the drive is idle, hand the hits to `plugins.bolt` (see [formats/bolt-mass-media.md](formats/bolt-mass-media.md)) |
| Yuke's `YOBJ` models (`.ymg`, behind a 16-byte `DUMY` stamp) | 3 (WWE Day of Reckoning 1-2, WrestleMania XIX) | **packs opened 2026-09-03** (`plugins.yukes_pac`: the `.tex` TPL textures rip); the model: `"YOBJ", u32 size, u16 4, u16 3, u32 0x40`, then (count, offset) pairs - bones (64-byte records, 16-char names, parent at +0x18), textures (16 B: name + extension), materials (variable, RGBA colours), hair/accessory records (0x68), a `POF0` pointer-offset table at the end; mesh records of 0x30 bytes from +0x4c (`u16, u8 groups, u8, 0x0a000000, data, 0, table A (16 B rows), table B (8 B rows: u8 index, u8 count, u16 count, u32 offset), bbox centre + radius, 4 x u16`); the group data are runs of u16 triangle indices behind a short header, not GX lists; no 12/16/8-byte stride of the "data" block puts the points inside the record's bounding sphere, so the positions are elsewhere (quantised, or in the 16-byte rows) | no symbols on any of the three discs; work from the `.ycg` (skeleton?) and `POF0` pointers, or gxscan-style brute force on the 16-byte rows |
| Blitz texture format 17 | 9 discs, ~13% of textures | 8 bits a pixel behind a 512-byte block; not C8 over an RGB5A3 / RGB565 / IA8 palette in tiled or linear order (2026-09-03).  Everything else on the engine now reads | see the closing section of [formats/blitz-gcp-gamecube.md](formats/blitz-gcp-gamecube.md) |
| Terminal Reality `_dfm` **vertex record** | 3 (BloodRayne, 4x4 Evo 2, Blowout, RoadKill) | **the block layer is solved (2026-09-02)**: blocks tile on 106/106 and 47/47 and every triangle indexes 0..vertices-1 exactly, giving 4,215 vertices and 3,914 triangles on `soldier.dfm`.  What is left is only the 20-byte vertex record.  Byte 3 is always 0x04, byte 4 0x00, byte 15 0x44, bytes 16-17 0x01FE; the best of all 240 s16 column triples scores 0.44 on triangle locality where a real surface scores 0.1, and eleven bytes carry ~40 distinct values over 130 vertices - so read it as **packed bit fields**, not s16 columns | see [formats/terminal-reality-dfm.md](formats/terminal-reality-dfm.md)  **2026-09-03: the normal is found** - bytes 8-13, LE `s16`/32767, unit length on 12 of 12 blocks - and the vertices are in **bone space**, which is why no box test could ever work.  Bytes 2-7 as three `s16` score 0.68-0.73 normal agreement against 0.51 shuffled: partly right, not decoded.  Twelve bytes left, with a working oracle |
| FSTA `GKA` / `GGG` | 3 (Billy & Mandy, Kids Next Door, Charlie and the Chocolate Factory) | **`GGG` read 2026-09-03** (models; `GKA` is animation) - **not compressed** - body entropy 5.28 (`GGG`) and 6.82 (`GKA`) against 7.73 for `GMS`.  Magic is `ISVH` (`HVSI` reversed) but the fields are big-endian: the `u32` at +12 is the exact file size on both | what they hold.  Neither shows f32 runs, so any geometry is quantised.  Note the models are in `GMS`, which is compressed - these may be animation or collision |

## Mapped but blocked on a codec

| format | discs | state |
|---|---|---|
| Pokemon `FSYS` non-model members | 2 (Colosseum, XD) | **the models are done (2026-09-02)** - they are HAL sysdolphin archives behind a prefix, see [formats/fsys.md](formats/fsys.md).  What is left is the 836 members that are neither images nor sysdolphin archives; they do not declare an archive size in their first word, so the locator passes over them | see [formats/fsys.md](formats/fsys.md) |
| High Voltage `GMS` | 3 | **closed 2026-09-03 - it was never a model.**  `GMS` is DSP-ADPCM sound (the DOL lists `GmsFormat` among the sound formats; 99.8% of its 8-byte frames validate).  The models are `GGG`, uncompressed s16 geometry with GX strips, read by `gcrip/formats/hvs_ggg.py` + `plugins/hvs_ggg.py` with textures through the `.AGM` databases: 57 models / 39k triangles from one level archive.  Skinned characters and the `JAM2` disc (Charlie) remain - [formats/jam-fsta-hvs.md](formats/jam-fsta-hvs.md) |

Both need bit-level reverse engineering of a private codec before any geometry exists to parse.
Worth saying plainly: there is no mesh layout to hunt in either until the codec falls.

## Mapped, needs a session

| format | discs | state |
|---|---|---|
| Asobo `.dgc` (Ratatouille) | 1 | **Asobo Studio "Internal Cross Technology"**.  Container mapped: 24-byte big-endian directory at 0x120 (`type | uncompressed | stored | block size | hash`), payload back to back, and **raw when uncompressed == stored and block size is 0** - 16 of 55 records, 29% of the archive, needs no codec.  Uniform 150/160 KB chunks mean it is a **paged virtual file system**, so cracking the codec yields an address space, not files - the name-to-page directory is a second problem.  See [formats/asobo-ict-dgc.md](formats/asobo-ict-dgc.md) |
| Darkened Skye `.skg` skeletons | 1 | `SKX` models ship (255 of 255, 135,749 triangles) and their skinning records give a joint index and weight per influence, but the positions are in **joint space** and there is no skeleton in the `SKX`.  The 17 `.skg` open `\0GKS` and are **now partly read (2026-09-02)**: +8 is the file own length on 17 of 17, the model name follows at +12, and there are **788 `SKT` records at an 84-byte stride** - 140 of them in `BoneSkye.skg`, none at all in five of the files.  One section is **20-byte animation keys, a frame number and a unit quaternion**: over 400 consecutive records the frames run 0-90 and all 400 quaternions are unit length (358 distinct, sd 0.0000).  That is one section layout and not the file - read whole that way only 3.0%% are unit length - so the block bounds are still unread, and the bind pose that would fix the joint-space positions is most likely in `BoneSkye.skg` `SKT` records.  Until they are bound the exporter takes the first influence, which is coherent but not exact on multi-joint models | see [formats/darkened-skye.md](formats/darkened-skye.md) |
| Acclaim `.SKN` skinned meshes | 3 (All-Star Baseball 2002, 2003, 2004) | **`.GDF` is done (2026-09-02)** - see [formats/acclaim-gdf.md](formats/acclaim-gdf.md).  `.SKN` uses a 36-byte name and carries a 23-bone name table (`ROOT`, `L_UP_LEG`, `L_FOOT`) between the materials and the mesh records, and its vertex record is not the `.GDF` one: sweeping every 4-byte offset from 76 to 4,000 for a mesh table whose **radius identity** holds finds nothing in any of the three samples.  Find the skinned vertex stride first - the radius is the oracle, and it is exact | see [formats/acclaim-gdf.md](formats/acclaim-gdf.md) |
| Free Radical `gcr` meshes | 3 (TimeSplitters 2, Future Perfect, Second Sight) | 2,467 in a 149-archive sample.  **Not GX display lists** - `gxscan` finds nothing in any of them.  The header is three or four big-endian offsets (`12, 7372, 29312, 7456` on a prop) that divide the file into a geometry region, a small block, an **embedded `CMPR` texture region** and a trailer.  The geometry region opens with 64-byte groups of repeated words (`00 00 04 12`, `00 00 80 3b`, `30 2e 40 00`, four of each) that look like register state, and `s16` triples that read as coordinates start after them.  Three `gct` codes (9, 11, 12) are also unidentified, together under 3% of the textures | see [formats/free-radical-pck.md](formats/free-radical-pck.md)  **2026-09-02**: header is **big-endian** - `+12` is a table of 16-byte records holding nine consecutive texture ids (775-783), terminated by `0xFFFFFFFF` at +156.  The "`s16` multiples of 256" at byte 30,032 are **little-endian `u16`**: 8-byte vertex records of (0, uv index, position index, normal index) with the position column incrementing.  So a `gcr` is many small indexed primitives over shared arrays, which is why whole-file statistics and `gxscan` both find nothing  **2026-09-02, corrected**: they ARE GX display lists - 562 `0x9B` strips (`GX_DRAW_TRIANGLE_STRIP` with vertex format 3) and 3,396 vertices in one character file, 8-byte vertices of four BE `u16` (position, normal == position, 0, texcoord), 1,046 positions as BE `f32` triples scoring 0.036 on triangle locality.  `gxscan` misses them because its walk is **greedy**: a spurious 1,397-vertex chain at offset 254 covers 35 KB and buries them, 5 candidate starts against 1,453 with the skip off.  Disabling it yields 43 meshes / 4,063 triangles from a file that gives 0 today, but scoring costs 30-46 s on 136 KB, so the salvage pass needs a library benchmark before it ships  **2026-09-03**: the RenderWare native reader (`formats/rw_native.py`) does **not** transfer - containment fails per strip run (7 groups / 415 vertices against the file's 562 strips / 3,396 vertices, because a `gcr` group is hundreds of tiny strips) and there is **no unit-length normal array** at `f32`, `s16/32768`, `s16/16384`, `s8/64` or `s8/128` anywhere in the file |
| Image carving beyond `.hff` | 2 | screening the 190 dead discs' biggest data file for **PNG with an `IEND` terminator** found only FutureTactics' `files.pak` (388 in 16 MB, now handled by `ft_pak`) and Nickelodeon Party Blast's `f9078e7e.wad` (27).  So carving does **not** generalise widely - worth recording so it is not re-tried.  The apparent JPEG hits (525 in a speech file, 521 in a texture pack) are `ff d8 ff ex` matching inside dense data and were not checked by decoding | |
| FutureTactics member codec | 1 | the `ft_pak` container ships and its 2,403 uncompressed members decode, but **3,055 are compressed** - every `.DFF`, `.AN2`, `.ANM`, `.XML` and `.FNT` sampled.  A compressed member opens `u32 unpacked size` then a second word, and the codec is private: zlib in three window modes, gzip, refpack, prs, yaz0, yay0, lzo, avlz, lzr and jade_lzo all fail.  A per-item-bitmask sweep is also ruled out: the stream opens with **36 literal bytes uninterrupted** and the best any variant reproduces is 3 of them.  The byte before them is a **parameter, not a control byte** - across 28 packed members it only takes values 0xE2-0xE8, ten `.XML` share 0xE8 with an identical literal run, and `.CUT` members sharing the same two literal bytes carry four different values.  Layout: `u32 unpacked size | u8 parameter | data from +5`.  **A complete test vector is in the note** - a member whose plaintext is known because it is XML.  Whether the `.DFF` are RenderWare underneath is unknown; the extension is the only evidence | see [formats/futuretactics-pak.md](formats/futuretactics-pak.md) |
| Climax `.bad` inner container | 3 (ATV: Quad Power Racing 2, Hot Wheels World Race, The Italian Job) | **the codec is cracked** - ring-buffer LZSS, 4096 ring, flag byte low bit first, `position = lo | ((hi & 0xf0) << 4)` absolute in the ring, `length = (hi & 0x0f) + 3`, zero fill (`gcrip/plugins/climax_bad.py`).  Hot Wheels decodes to 100% printable text and ATV header to clean big-endian words.  **Correction 2026-09-02: "the whole game on each disc is now reachable" does not hold for ATV.** Its 98.8 MB stream was also being silently truncated at the flat `1<<28` cap (output was exactly 268,435,466 = cap + one match); the limit now scales with the input.  And the payload does not decode cleanly: `mass di` x6 and `ass dis` x5 but `tribution` x0, and zero occurrences of distribution/engine/suspension/texture/vertex in 268 MB, while structure survives (`BOG 1.01` x114, `ROM 1.26` x51, `CUBAN` x23) - so literals are right and longer matches are not.  Ring init (0x20 vs 0x00) ruled out; five match encodings tested but **inconclusive**, the window used held no text.  Decoding the whole stream settles it: the input is consumed **exactly** (98,812,344 of 98,812,344, 100.0000%%) and stops on its own at 274,073,929 - but **that is not evidence of anything** - the walk runs until `i >= n` so it always ends on the last byte, and decoding from a deliberately WRONG start consumes 32.69%% against the correct start 32.69%% for the same output budget.  Two versions of this row cited consumption as proof (first of lengths, then of framing); both were wrong and it should not be cited again.  The oracle that does work is the **name chain**: the header declares 643 parts, so a correct decode holds a long run of back-to-back NUL-terminated identifiers, and the shipped decode longest run is **5** (`MIT`, `UGR`, `SEP`, `QCN`, `OAL` - noise).  Sixteen operand packings swept against it score 2-13, best being the shipped one - but **that oracle is not grounded either** (part-name occurrences are spaced irregularly, 5968/3975/1026, so there may be no packed table and a short chain may be correct), so the sweep is a weak negative.  What IS verified: the stream start decodes exactly - flag `ff` then eight literals spelling `CUBAN 1.`, then five more giving `02\0\0@` - reproducing the container magic, which validates offset, flag polarity and the literal path together.  Also, the old cap was dropping the last 5,638,473 bytes.  **But exact consumption cannot vindicate the match position**: `pos` only reads the ring, so a wrong value consumes identical input.  The tail is 100%% printable and meaningless (`pttept opt peoaws`), which also means **"decodes to 100%% printable text" is a weak oracle** - it passes on garbage - and the Hot Wheels validation needs re-checking against something stronger.  **Both nibble splits fail** (shipped and swapped): each consumes 100.0000%% of the input, giving 274,073,929 and 292,237,044 bytes, and neither tail is English nor contains `distribution` or `Copyright` once in ~280 MB.  **Parked** rather than trying a seventh variant: three oracles have now proved worthless here (printable text passes on gibberish; exact consumption is true by construction for every variant; repeated part names may be legitimate).  What is needed is a **known-plaintext pair** as on Tiger Woods.  The container reads: `CUBAN 1.02` with 643 at +0x28 and versioned sub-blocks.  What is left is the container inside: the payload carries 643 part names (`frwheelcentre`, `rlmudguard`, `GEN_quadmud_01`) but the geometry is **not GX display lists** - `gxscan` finds 10 meshes in 12.7 MB of ATV and none at all in the other two.  Needs the directory and the vertex record | see [formats/climax-bad.md](formats/climax-bad.md) |
| Jimmy Neutron: Attack of the Twonkies `.pak` | 1 - **stale, see below** | **Avatar is done** - a `.rad` is a pack inside a pack whose `.rcb` leaves are zlib, and the `g4rc` objects inside are CMPR textures with the dimensions packed into bits 0-7 and 10-17 of the word at +16 (`plugins/thq_g4rc.py`, 486 textures from three archives).  Twonkies shares the `pack` magic and 23 archives / 1,013 MB, but its leaves are not `g4rc` and yield nothing | see [formats/thq-g4rc.md](formats/thq-g4rc.md) |  **Corrected 2026-09-01**: this disc is not dry.  It exports **1,938 models and 649,407 triangles** today, through its 2,007 `.rws` and 2,215 `.anm` - the note's premise, that the `.pak` leaves yield nothing, was about the wrong files.  What the `.pak` hold is a separate question and a much smaller one.
| Spawn / Scorpion King `PHM` **index runs** | 2 | **The vertex record is cracked** (`plugins/phm.py`): 20 bytes of `s16` - uv, position, normal/4096, then -1,-1 - pinned by unit-length normals on 1,987 of 1,987 vertices, two constant columns, and the array ending where the next section starts.  `SPAWN.PHM` gives 1,987 vertices and 3,488 triangles with materials named from the file.  **The strip-seam worry was unfounded**: every index reading scores the same, there is no triple structure (63.2% within vs 64.2% across), and splitting at the jumps *lowers* agreement (0.824 vs 0.832) while halving the triangles.  The mesh is simply smooth-shaded - a triangle's three vertex normals agree with each other at only 0.771 - so 0.832 against the averaged normal is the ceiling, and the reader is at it.  The header table is also still unread; the reader finds its arrays by arithmetic instead | see [formats/spawn-toc-wad.md](formats/spawn-toc-wad.md) |
| Gun `.ngc` | 1 | **The "hashed" premise was wrong** (2026-09-01): the names are ordinary once read whole - `af_intro_text.apk.ngc`, `gun_bannericon_01.img.ngc` - and sort into **1,233 `.apk` + 1,233 `.mpk` pairing exactly 1:1** (the `.ord`/`.orp` shape, and the first thing to test), 166 `.shd`, 158 `.img`, 119 `.pak`.  Nothing claims any of the 2,918: content-sniffing them all with `is_model`/`is_img`/`is_tex` matches none, and `is_img` rejects the 158 `.img.ngc` because it wants a first word of 2 where Gun has 0x04200000 - a newer generation, as with American Wasteland.  `.img` header is 32 bytes with what look like log2 dimensions at +10/+11, unconfirmed | see [formats/gun-ngc.md](formats/gun-ngc.md) | **Tested 2026-09-02 and the `.ord`/`.orp` analogy is disproved**: **918 of the 1,233 `.mpk` are exactly 32 bytes of `AB` fill** (MSVC uninitialised heap), so they are placeholders, not a second half; only 315 carry content (191.7 MB) and they are named for levels (`z_fort`, `z_hunt`, `z_steamboat2`) - **`.mpk` is a map pack**.  The `04 20 00 00` header is shared by `.img.ngc` and `.mpk.ngc` and now reads: payload at +16, header size 32 at +20, next-image offset at +24 (`0xffffffff` last), with **payload + 32 == file length on 5 of 5** and `map_compass` proving the chain (8,224 + 8,192 = 16,416).  Format 14 is CMPR (128x128 -> 8,192 exactly); **format 6 does not reconcile** - 1.5, 0.875 and 3.0 bytes per pixel on three files - and is not settled.  `gxscan` on the 2.4 MB `z_hunt.mpk.ngc` finds 3 meshes / 168 triangles, so the scanner is not the way in **2026-09-03**: the map pack is mapped - a 1 MB table of **32-byte records** ending in an RGBA `80 80 80 ff` (31,924 of them; per-primitive descriptors), then **385 KB of floats at stride 24** (~16,000 vertices), then high-entropy blocks.  The salvage scanner still finds only 168 triangles, so the indices are not GX lists.  Then: the 32-byte rows after a descriptor are **big-endian `u16` index pairs** - (626, 7), (522, 282) - an indexed vertex stream with no display-list opcode, 253,416 pairs across the file, runs terminated by zeros rather than counted.  Next: how a pair addresses the stride-24 float array |
| Casper `.hff` geometry | 1 | the `hff` container ships and carves `PNG`, but Casper's 144 MB holds none.  Its bulk reads as `f32` unit vectors - triples like (0.652, -0.139, -0.898) - and the text file at the head names `.obd` and `.lvl` paths, presumably its members.  TONKA and Aquaman, the other two `.hff` discs, gave 1,897 and 2,800 textures | see [formats/hff-carving.md](formats/hff-carving.md) |
| AFS inner formats | 6 (Bleach, Digimon World 4, One Piece x3, Sonic Riders) | surveyed 2026-08-30; **most AFS is `ADX` audio or MPEG - settled, do not re-check the big ones**.  **Auto Modellista and Capcom vs SNK 2 are now done**: their members hold Sony `TIM2` behind an ascending offset table, and 25 of 28 pictures decode (`gcrip/plugins/tim2.py`, see [formats/sony-tim2.md](formats/sony-tim2.md)).  The note's claim that CvS2's `afs02` "holds TIM2 textures" overstated it - only 2 of its 518 members are TIM2; the bulk open `00 00 00 10`.  Still open: Bleach `chr`/`scenario`/`com`/`stg` (2,238 members, all `16 00 00 00`, asset names at +76 such as `ich_t001`).  **2026-09-01: the recurring word is a typed record header** - `u16 type, u16 0x1c02`.  **2026-09-02 the per-type theory is disproved**: in `chr.afs` member0000 the markers sit at 8, 20, 36 and 48, all four carrying the SAME type 0x0037, yet the gaps are 12, 16, 12 - so record length is not a function of type and shaping headers per type will not produce a walk.  Neither `at + 12 + size`, `at + 8 + size` nor a fixed stride reproduces those positions; whatever selects the length is in the record own fields.  A type-0 record carries ~47 KB that reads as `I8` at width 256 (11.7-13.2 against a shuffled copy, noise ~1) but factors into no clean texture, so it is a lead and is deliberately not shipped and Digimon World 4 `area.afs` (1,382 members).  `gxscan` finds no display lists in either | see [formats/afs-inner-formats.md](formats/afs-inner-formats.md) |
| `.arc` (cluster 2) | 3 (Cabela's x3) - Over the Hedge, Shark Tale and The Sims now ship; **The Sims 2 / Pets models and textures read 2026-09-03**, the five older Edge of Reality discs need their `Datasets` opened | **Cabela's is DONE (2026-09-02) - the dead-end verdict was wrong.**  It rested on one inflated block, and `data.arc` is not homogeneous: its first blocks are navigation data stamped `PathGen 3.2`, its middle is Lua, and **its tail is `MULA`, a named texture archive**.  `plugins/cabelas_arc.py` keeps only the `MULA` blocks and `plugins/mula.py` decodes them; payload tiling is exact on 2 of 2 whole blocks and `32 + palette + pixel bytes == size` holds on 200 of 200 textures, 282 decoded from the sample.  See [formats/cabelas-mula.md](formats/cabelas-mula.md).  Superseded: (**re-checked 2026-08-31** with the fixed RenderWare sniff: the six `WORLD` / `TEXDICT` chunks it appears to contain are false positives of 27-127 bytes that all raise `world without struct`; the conclusion holds): a chain of raw zlib streams at 0x800-aligned offsets, ~2 MB each; `generic` already inflates the first.  Not shipped as a container - gxscan finds nothing in an inflated block and none of gcrip's magics appear, so it would cost ~600 MB of inflation per disc for no output.  **Over the Hedge, Shark Tale and The Sims are done** - the container ships (`plugins/edge_arc.py`), 1,913 members.  The directory was never inside `datasets.arc`: it is the sibling `index.ind`, read through `NEEDS_SIBLING`.  The earlier note below was looking in the wrong file, which is why its record table had no ascending column - it was not an offset table.  See [formats/edge-of-reality-arc.md](formats/edge-of-reality-arc.md).  *(superseded: the archive-internal directory hunt)* | see [formats/cluster2-arc.md](formats/cluster2-arc.md) |  **Evolution Snowboarding is now done** - its 29 `.arc` are Konami `KCEO ARCDT` and ship (`plugins/kceo_arc.py`), 155 of 155 entries across four archives fitting and named; members are `BPXB`, which is the next step.  **Cabela's re-confirmed dead 2026-09-01** on a stronger test than before: the earlier note ran gxscan on one inflated block, and running it on the whole 21.6 MB concatenation still finds nothing.
| `res` `node` scene graph | 3 (Samurai Jack, Lemony Snicket, Digimon Rumble Arena 2) | `rdms` meshes ship (93,000 of them, 7.4 million triangles) but each comes out in its own space; the `node` sections are what would place them in a level, and `surf` textures are not matched to the meshes that use them.  **2026-09-01: `indx` is cracked** - a name directory with self-relative name and section offsets, 7 of 7 entries resolving to a section whose tag matches and to a full asset path - so nodes and textures now pair by name (`fx_hud_target` beside `target_texture.tif`), and **`node_links` now reads which meshes each node draws** - all 7 `rdms` on Lemony Snicket referenced exactly once by 3 nodes, in a 52-byte record - so meshes are grouped and named by object.  **The transform is still missing**: the record's six floats are a min/max box but it is 0.3 units wide and off centre while its mesh spans +-39 symmetric about the origin, so it is not the mesh's bounds nor any scale of them | see [formats/res-rdms-meshes.md](formats/res-rdms-meshes.md) |
| Hunter `AGM` / `AGD` materials | 1 | `AGG` meshes ship (781,658 triangles) and carry their material **names**, and the `LJAM` archives hold 3,865 `TPL` beside them, but the text that maps one to the other (`MatAssignment` / `MaterialDatabase`, 3,465 files) is not read, so the meshes come out untextured | see [formats/high-voltage-ljam.md](formats/high-voltage-ljam.md) |
| `bin`/`dat` tail | many | **surveyed** - and it is inner-format-bound, not container-bound.  431 of 629 dumped discs produce no triangle-bearing model, and of 158 large bin/dat files on them (audio and video excluded by the manifest's own `kind`) 114 are claimed by no specific container - but the magics **do not cluster**, so there is no single format here to attack.  Closed as audio: `SCHl` (EA, 516 MB over Knockout Kings 2003 and Quidditch World Cup) and `FJF\0` (Sonic Mega Collection's ADX).  **New 3-disc cluster**: magic `a4 0d 6d 71`, header naming its toolchain `Created/Modified using Kashmir` plus an author string, on City Racer (52 `.dat`), Speed Challenge: Jacques Villeneuve (33) and Taxi 3 (10).  It is a **property-driven scene graph**: entities are an 8-byte type id then a NUL-terminated name, with the id appearing earlier on its own (a type table, then instances) - `GhostPoint`, `StartPoint00`, and on Taxi 3 the property names as well (`AnimatedObject_SoundSource`, `WaveName`, `MinDistance`, `UseDoppler`, `Draw_Sphere`).  Geometry is not reachable yet: entropy by sixths 7.23/1.59/7.45/6.81/6.19/7.25 and `gxscan` finds nothing on City Racer, two meshes on Taxi 3 - container and payload both.  **Tomb Raider: Legend's `bigfile.dat` is now open** - it was a sorted hash table after all, with 16-byte records behind it (see [formats/cd-bigfile.md](formats/cd-bigfile.md)); 617 of 617 sampled members read exactly, and its payloads are surveyed: a `00 00 7c/7d xx` family is 48 of 91 sampled members and carries `f32` fields (16.0, 29.0, 1380.0) beside a count - the geometry candidate; `00 00 00 0e` is 26 and is **itself a container, now mapped**: a 24-byte header whose second word is the record count, then that many 20-byte records each beginning `0xffffffff` - verified on 60 of 60 such members; `!WAR` and a `00 00 6d xx` family make up the rest.  **Not GX**: `gxscan` finds 3 meshes and 206 triangles over all 91, so it needs its own mesh reader | see [formats/bin-dat-tail.md](formats/bin-dat-tail.md) |

## What the 191 empty discs actually hold (measured 2026-09-01)

Re-measured after this session's fixes took the library to 700,199 models.  For every disc that
still produces nothing, the largest file that is not audio, video or code **by extension or by
path**:

| ext | discs | | ext | discs |
|---|---|---|---|---|
| `bin` | 15 | | `blt` | 4 |
| `dat` | 15 | | `afs` | 4 |
| `arc` | 6 | | `pac`, `rom`, `sr`, `pck`, `mst` | 3 each |
| `viv`, `fpk`, `pak`, `ngc` | 4 each | | | |

**Only 4 of the 191 are genuinely dry** - From Russia With Love, Cubic Lode Runner, Space
Raiders and Tower of Druaga.  The other 187 all have something substantial, so the tail is not
padded with hopeless discs.

But it does not cluster.  The biggest group is 15 discs, and after `bin`/`dat` it is a long tail
of threes and fours - the same conclusion the 2026-08-30 survey reached from the other
direction, now confirmed on the post-fix library.  **There is no one format left that unlocks a
large number of discs**; the rest is per-engine work.

### Two filters are needed, and the first one alone lies

`h4m` and `bik` are video and `sab` is audio, but the manifest's own `kind` does not mark them,
so a census trusting `kind` reports 13 discs whose "biggest file" is an FMV.

Filtering by extension too is still not enough, because **the biggest remaining file is often
media by its path**: Tiger Woods' `Data/Movies/intro.ngc`, Gun's `streams/streamsn.wad`,
Zapper's `packages/Music/music.gcp`, Muppets' `BVoice.BLT`, Freestyle Street Soccer's
`Sound/InGame/Shouts/German/shouts.wad`.  An extension-only census put `wad` at 6 discs and
`gcp` at 4; with the path filter both drop out of the table entirely.  Anyone repeating this
needs both.

**That census finding is now the rip's own scan order** (2026-09-01).  The fallback scanner is
budgeted per disc (`GCRIP_GX_DISC_BUDGET`, 900 s) and used to spend it biggest-first, which put
those very files at the front of the queue.  `gcrip/rip.py` now sorts media last whatever its
size (`_looks_like_media`), and archives a real container plugin already walks last as well
(`_claimed_by_container`) - the latter because Tiger Woods 2003's 273 `SHOC` `.hog` are 2-5 MB
each, contain no display lists at all when scanned whole, and have their members expanded and
routed anyway, so they were burning the entire budget before the 35 `.skg` that do hold
geometry were reached.  Fallback containers are excluded from that test: `plugins/generic.py`
claims every file there is.

Measured across the 635 discs with a manifest, the ten biggest files - what the old order fed
the scanner first - are **entirely media on 165 discs (26%)**, and eight or more of ten on 313
(49%).  On a quarter of the library the whole per-disc budget was spent before anything that
could hold a triangle was opened.

**Validated on Tiger Woods 2003 at the default budget: 0 models before, 35 models and 113,135
triangles after, 0 failed, 941 s** - and its 100 MB `intro.ngc` sorted 381st of 381.  Wave 21
re-rips the 201 discs where at least eight of the ten biggest files are media *and* the disc
reports zero triangles.

## Oracles, identities and determinism are now enforced, not remembered (2026-09-02)

Three of the five improvements from the retrospective, beyond the claimed-empty outcome below.

**Identities are executable** (`gcrip/identities.py`).  The arithmetic each format note quotes -
"200 of 200", "exact on 17 of 17" - is declared as `IDENTITIES` on the module and run in the
suite.  Checked against real cached members: Cabela's blocks tile at 412,520 and 147,312 to the
byte, 192/192 and 90/90 images reconcile, all four Terminal Reality files report 3 hold 0 failed.
Each test also proves the identity *fails* on damaged data, because one that cannot fail is not
evidence.

**Oracles are graded** (`gcrip/oracles.py`).  Eleven entries, each with the evidence attached.
Two are marked **discredited** and say exactly how they failed: *printable text* (a wrong Climax
decode is 100% printable and meaningless) and *input fully consumed* (true for every variant by
construction - a deliberately wrong start consumed 32.69% against the right start's 32.69%).
Three more are **weak** with their limits stated.  "We tried that" is only useful with the
reason.

**Determinism is a test** (`tests/test_determinism.py`).  No module in `gcrip/formats` may read
the clock, because a reader decides what a file contains and two runs must agree - that is the
`find_toc` bug generalised.  `plugins/gx.py` is allowlisted **by name and with its reason**: its
budget is a genuine time limit on a speculative scan.  The consequence is recorded rather than
hidden - **gx can find different meshes on different runs** - and it is tolerable only because
it names nothing the manifest depends on, which is exactly what `find_toc` did.

## "Claimed but empty" is now a recorded outcome (2026-09-02)

The structural fix for every silent-drop bug this session found one plugin at a time.

`_run_plugins` deleted the record when a plugin returned no scenes - *"not this plugin's file
after all"*.  True for a **fallback**, which probes everything it is offered.  False for an
ordinary plugin, whose `detect()` said it recognised the format: returning nothing is a fact,
and deleting the record made *silently read as empty* indistinguishable from *nobody claimed
it*.

`ModelResult.empty` now records it, and the batch row carries `claimed_empty` and
`empty_examples` beside `failed` and `fail_examples`.  It is **not** counted as a failure - a
skeleton-only EAGL object legitimately has no mesh - so the three outcomes are distinct:
exported, failed, claimed-empty.  The same split runs inside `eagl.extract`: barren **with**
warnings raises, barren **without** returns empty.

This is what makes the next census able to see the class at all.  Note that rows written before
this change have no `claimed_empty` field, including everything wave 21 produced - it binds its
plugins at import.

## A failure list under-counts a silent bug (2026-09-02)

Worth writing down because it nearly cost this session a result.  The re-rip queue was built
from recorded failures, which is the obvious thing to do and is wrong for any defect that
returns nothing instead of raising.

The EAGL display-list bug is exactly that shape: `_decode_packet` hit a `return None` and the
disc reported a healthy zero.  FIFA 2003 only appeared in the queue because it *also* had a
sibling-lookup error; every other EA sports disc failed silently and was invisible.  Ten of
twenty-seven were queued on failure counts; all twenty-seven needed re-ripping.

So when a fix removes a silent `return None`, the discs to re-run are **every disc the plugin
touches**, not the ones with rows in the failure table.

And the class is now closed off rather than fixed once.  An audit of every reader that takes a
warning list found seven functions with empty returns; `eagl._decode_packet` (5 returns, 2
warnings) was the worst, and `ttyd_map._packed_mesh` and `feporr_gs._skin` had one each.  All
now explain themselves, and `tests/test_material_index_contract.py::test_readers_explain_every_drop`
fails the build if a reader gains an unexplained empty return.  Two exemptions are allowed and
both are visible in the source: a function declared `-> None`, and a return whose own line is
commented `legitimate` - because some absences really are not failures, and warning about those
would just be noise.

## The state of the tail (measured 2026-08-30)

223 discs still produce neither a model nor a texture.  For each one, the largest file that
gcrip's own classifier calls `unknown`, `archive`, `texture` or `model` was read and offered to
every registered plugin.  What claims it:

| claimed by | discs |
|---|---|
| `generic` only (the fallback container) | 116 |
| nothing at all | 39 |
| `generic` and `gx` (the display-list scanner) | 35 |
| `afs` | 7 |
| `vc_dat` | 5 |
| `ea` (BIG / VIV) | 4 |
| `blitz`, `frd_pak` | 3 each |
| `fpk` | 2 |
| `u8`, `feporr` | 1 each |
| no such file over 256 KB | 2 |

**There is no large shared cluster left.**  151 of 223 fall to a fallback or to nothing, which
means a bespoke per-game format - so from here each crack is worth roughly one disc, not five.
The multi-disc work that remains is where a container already opens but its members are unread:
`afs` (7 discs, and [afs-inner-formats.md](formats/afs-inner-formats.md) says which archives are
worth opening) and EA `BIG` (4, mostly audio inside).

### Two things this measurement got wrong first time, and how

**A first pass filtered "media" by file extension and picked audio on many discs.**  It chose
`voice.all`, `voices.all`, `Prologue.vid`, `music.zsd`, `mkg_bondgirls.vp6` and four `.hps`
files as discs' "biggest non-media file".  Filtering on the `kind` field gcrip's own classifier
already wrote into every `disc_manifest.json` is both more honest and less work; it moved the
`generic`+`gx` bucket from 59 discs to 35.  **Do not hand-roll a media extension list when the
manifest has already classified every file.**

**The first pass concluded that improving `gxscan` was "the only change that would move dozens
of discs at once".  That is wrong.**  Instrumenting the scanner on six of those discs showed it
finds only 8 to 24 candidate display lists per 2 MB and that **`best_mesh` returns None on every
single one** - 119 of 119.  Nothing is being rejected by the acceptance thresholds, so tuning
them would change nothing: there are no GX display lists with findable vertex arrays in these
files, and several of the files are not geometry at all.  The scanner is not the lever.

## Cluster 1's `.rws` are audio - the premise was wrong (2026-09-01)

`.rws` was the top of the backlog's ROI list across six discs.  On Asterix & Obelix XXL (631
files), Madagascar (31) and Piglet's BIG GAME (620) every one is **streamed audio**: a single
`0x080D` chunk wrapping a `0x080E` table and a `0x080F` block of 40,960 bytes - 20 disc sectors
- of DSP-ADPCM at entropy 7.04-7.19.  Frogger: Ancient Shadow and Burnout 2 confirm it from the
other side, their `.rws` being `sound/` and `music/`.

`renderware.py` declines them correctly; widening its sniff would decode sound.  **The 4-to-13
second rip time on those discs was the signal** - there was nothing for a model plugin to walk.

The geometry is in a different container on each disc, from four studios that merely licensed
RenderWare: Asterix 108 `.KGC` (174 MB total; **measured 2026-09-02** - no RenderWare chunks and no offset table, so it is a serialised structure to walk from byte 0.  A full `gxscan` of the 15.9 MB `LVL02.KGC` finds **4 meshes and 376 triangles in 192 s**, so the geometry is *not* display lists and the fallback scanner will never be the answer here.  What the file does have is a record stream: 2,034 occurrences of a `00 00 00 06` prologue whose next big-endian word is a type - `0x6` 484, `0x1106` 224, `0x5` 212, `0x48` 206, `0x2` 178, `0x1` 132 - and **62 unique asset names in 24-byte NUL-padded fields**, `it_pier_tirb_b01`, `no_vege_sapin_s01`, `co_boucl_bois_g01`.  Five of 34 sampled records put the name exactly 24 bytes after the prologue, so the record layout varies by type and that grammar is the work), Madagascar 16 `.gcn` (**cracked**), Piglet one 232 MB `PIGGCN.pkd` (**CRACKED** - `plugins/piglet_pkd.py`: a zlib chain covering all 232,370,273 bytes in 10,328 blocks, padded to 16 with assets spanning them, holding 936 CLUMP / 404 TEXDICT / 66 WORLD / 4,891 animations.  **The reader is the remaining gap**: renderware.py claims all 1,001 geometry assets and returns a scene for 68, 27,478 triangles.  Diagnosed - the clumps put GEOMETRY directly under CLUMP with no GEOMETRYLIST and declare numAtomics 0, both now handled, but most geometry carries the `rpGEOMETRYNATIVE` flag with no vertex arrays and **no NATIVEDATA extension inside the geometry chunk**, so the native data lives elsewhere - **ruled out**: not a NATIVEDATA extension (the geometry chunks hold only STRUCT and MATLIST) and not the 533 `0x1E` chunks (600-1,400 bytes each, 0.5 MB against a 425 MB archive).  It is a **raw block inside the clump**: the biggest clumps are 2.8 MB of which 2.85 MB is an unchunked tail after STRUCT, FRAMELIST and one 0x11010 plugin chunk, at entropy 7.37, opening on an image-like byte ramp, with no GX display lists in it - **DISPROVED 2026-09-02**: scanning the 2,215,106-byte tail of the biggest clump for a chained opcode at each stride gives **87 `0x98` strips and 32,096 vertices at stride 8**, three times the next stride, with 8-byte vertices of four BE `u16` - the same shape as Free Radical's `gcr`.  `gxscan` misses them because its walk is greedy.  **Both readers now ship** (2026-09-03): `renderware.py` reads 120 of 146 sampled clumps (107,040 triangles) once its chunk walk tolerates a declared size that overshoots the next header and `rwgc` reads the Piglet native header; `rw_native.py` reads the groups outside any GEOMETRY chunk (182,771).  289,811 triangles from the 40 MB slice.  **Layout found for the first group**: lists at 77..37,624 (4 strips, indices exactly 0..3,251), positions `f32` x3 BE at 37,645 (locality 0.0241), normals `f32` x3 BE at 76,685 (**unit length to 4.15e-08**).  What is left is the rule that finds the next group's lists.  See [formats/piglet-native-geometry.md](formats/piglet-native-geometry.md)), Frogger one 198 MB `gamedata.bin` (**directory solved** - an `hfs
` archive: span, count and data offset at +4/+8/+12, then 8-byte entries of `u32 sector|0x01000000, u32 size` whose sectors x 2048 land on 8 of 8 members.  Members are `PRS1` with a 12-byte header, and the payload is **not Sega PRS** - `gcrip.formats.prs` fails at every offset with *back-reference before start*.  The codec is the remaining work; see [formats/frogger-hfs.md](formats/frogger-hfs.md)).

**Madagascar's `.gcn` is now CRACKED** (`plugins/tfb_gcn.py`, 114,936 triangles from `title.gcn`).  It was where to start: entropy 1.61, two RenderWare-stamped chunks then a
node tree that names its own types in ASCII - `rwID_TEXDICTIONARY`, `TD_LEVEL FOLDER` - and
carries the original build paths.  See [formats/rws-is-audio.md](formats/rws-is-audio.md).

## Neko `.GCN` - four discs, one shared format, all at zero (2026-09-01)

Not Madagascar's `.gcn`, which is cracked; a different format that happens to share the
extension.  Cocoto Funfair (42 files), Cocoto Platform Jumper (41), Cocoto Kart Racer (16) and
Charlie's Angels (13) all produce **nothing**, and their level files agree on two things:

* the first `u32` is **big-endian and equals the file size minus 8** - `0x003f875a` against
  4,163,426 bytes, `0x002a7516` against 2,782,494 - exact on all four;
* the word at +8 is `0x000000ef` on every one.

2.7 to 4.4 MB a level.  A shared header across four dead discs is a good place to start.

### Alien Hominid has no 3D (2026-09-01)

Its 45 `.pak` are ZIP files that `plugins/zip.py` already opens, and their members are 560
`RSND` sounds, 9 `SWF6` Flash blobs, 3 `PIXL` bitmaps and a `GLYP` font over 12 archives
sampled.  The game began as Flash and the port carries the Flash content across, so a level's
art is **vector shapes, not meshes**.  There is nothing here for a 3D ripper - the same
conclusion as Mega Man X Collection in the same cluster, by a different route.  See
[formats/alien-hominid.md](formats/alien-hominid.md).

## Dead ends - confirmed, do not re-probe

| thing | why |
|---|---|
| `.rws` | RenderWare **audio**, chunk 0x080d.  Not geometry.  **Re-checked 2026-08-31** after the version-stamp bug was found in the same sniff that had classified it: sampling five discs, every chunk is 0x080d or 0x0809, both audio - no CLUMP, WORLD or TEXDICT.  The conclusion survived the tool being fixed |
| `.fsb` | FMOD sound banks - 5 discs |
| most AFS archives | ADX audio and MPEG video.  R - Racing, Soul Calibur II, Viewtiful Joe 2 and Sonic Riders have nothing else in theirs |
| `.mpq` (WWE x3) | video packs |
| Mega Man X Collection | emulated 2D games - there is no 3D geometry on the disc |
| Alien Hominid | the 45 `.pak` are ZIPs gcrip already opens, and their **1,948 members are 1,896 `RSND` sound records, 33 `SWF6` Flash movies, 11 `PIXL` textures, 7 `GLYP` font atlases and one `PDAG`**.  It is a Flash game: the artwork is vector data inside the SWFs, not textures.  The 11 `PIXL` do decode - 128x128 `CMPR`, pixels at +96, and the word at +48 is the data end so the size identifies the format exactly - but eleven font-ish textures is not worth a plugin |
| TMNT world materials | genuinely untextured in the source data |

## Neversoft `pass table not found` - a THUG-only signature (2026-09-01)

Three Tony Hawk discs fail on it, and one produces nothing at all:

| disc | models | exported | failed | triangles |
|---|---|---|---|---|
| Tony Hawk's American Wasteland | 99 | **0** | 99 | 0 |
| Tony Hawk's Underground 2 | 6,121 | 1,805 | 2,507 | **0** |
| Tony Hawk's Underground | 5,596 | 1,232 | 1,352 | 935,074 |

`_pass_table` locates the 32-byte pass records by a **literal byte signature** - `00 01 00 00
00 00 00 00` at +24 and three zero bytes at +21 - fitted to THUG, whose models do parse (935k
triangles).  American Wasteland and Underground 2 are a later engine generation and match it
nowhere, so the search runs off the end of every model.

This is a format gap, not a bug: the fix is to learn what a pass record looks like on the newer
engine, which needs the discs.  Recorded here rather than guessed at - loosening the signature
until something matches is exactly how a wrong reading gets shipped.

## The remaining 13,556 failures, and one more fixed (2026-09-01)

After this session's fixes took the library from 103,130 recorded failures to 13,556, grouping
the first `fail_examples` entry of every disc leaves a short list:

| kind | discs | failed | |
|---|---|---|---|
| `xmdl / IndexError` | 1 | 6,273 | Home Run King - the single biggest item left |
| `neversoft / NeversoftError` | 3 | 3,958 | recorded above as a format gap, needs the newer pass record |
| `eagl / EaglError` | 12 | 1,302 | what the `.orl` fix did not reach |
| `mdgc / IndexError` | 1 | 947 | |
| `gx / KeyError` | 8 | **502** | **fixed** |
| `hsd / RecursionError` | 8 | 228 | |
| `skx / IndexError` | 1 | 193 | |

### `gx / KeyError` - the walk and the fetch disagreed about who opened a container

`manifest._walk_plugin_container` **skips the fallback plugins** for anything under a container
an ordinary plugin opened - the rule that stopped RE4's `.das` members exploding into 25,000
pseudo-files.  `_Source._expanded` in `rip.py` knew nothing about those roots and simply took
the first plugin that claimed, so at fetch time a different plugin could name the members and
the one being asked for was not in the dict.  The model then died with a bare `KeyError` on its
own path.

The signature is unmistakable once seen: `gg0002: gx: KeyError: '.../crypt3.lvl/g0057'` on
Rayman Arena - the model being fetched is `gg0002`, two levels down, and the path that is
missing is its parent.

The fetch now keeps searching when a plugin's expansion does not contain the member being asked
for: a plugin that does not produce it is not the plugin that produced it.  If none does, the
`KeyError` is raised as before rather than some other plugin's bytes being returned.

## The export contract, and the census that found it broken (2026-09-01)

`Primitive.material` is an **index into `scene.materials`**, and `Primitive.indices` is **flat**,
three entries a triangle.  Neither is visible from a format reader, so a parser can be right in
every detail and the plugin still export nothing.  Three plugins had it wrong at once:

| plugin | discs | meshes lost | mistake |
|---|---|---|---|
| `res` | 3 (Digimon Rumble Arena 2, Lemony Snicket, Samurai Jack) | **62,640** | `material=-1` with `scene.materials` left empty |
| `wart_bmsh` | 2 (Animaniacs, Looney Tunes) | 13,967 | material passed as a name; `(M,3)` indices |
| `ea_obg` | 1 (Tiger Woods 06) | 665 | material passed as a name |
| `xmdl` | 1 (Home Run King) | **6,273** | `material=-1` into an index - the largest single failure count in the library |
| `mdgc` | 1 (Superman: SoA) | 947 | same |
| `skx` | 1 (Darkened Skye) | 193 | same |
| `eagl` / `EaglError` | 8 | 32 | **fixed 2026-09-02**: "section table outside the file (missing .orp?)" was misleading - the other half was on the disc all along.  NBA Live splits the pair across **two containers in the same directory**, the `.ord` in `anim/body/xanims.viv/` and its `.orl` in `anim/body/xsyms.viv/`, and the lookup only searched the `.ord`'s own folder.  All 26 `.ord` on that disc have a sibling.  `_sibling` now falls back to a cached basename index, widening by exactly one directory level.  **Verified on the real disc**, and the result is narrower than it looks: the lookup does find the 1,424-byte `.orl` and the join gives a valid little-endian ELF (`7f 45 4c 46 01 01`), but `extract` then returns **0 scenes** - `xmcpbnch` lives in `xanims.viv` and its `.orl` is a symbol table (`.data`, `.shstrtab`, `.strtab`), so it is an *animation* object with no `__Model` in it.  So this removes 32 spurious errors; it does not by itself add models.  **FIFA 2003 measured (2026-09-02)**: its 933 `dplyrgeo.big` pairs share stems *inside one container* and already worked; only **22** `.ord` (in `static.big` and `pstatic.big`, whose `.orl` sit in `ngccache1/2.big`) need the cross-container lookup - and since every `.big` lives in `files/data`, **all 22 are reachable one level up and 0 remain missing**.  Unlike NBA Live's animation objects these carry `__model__` names, so they may yield real geometry.  **And 22 is not 994**: measured 2026-09-02, **926 of the 994 sit in `dplyrgeo.big`** and those rows are **stale** - re-run today the pair is found and nothing raises across 40 sampled `.ord`.  What happens instead is worse: `eagl.parse` returns **models=0, skeleton=0 with no warnings**, so 933 named `Player____model*` objects are read as empty and the report says nothing.  The joined blob does not read as a plain ELF32 either way round - the usual little-endian offsets give shoff=11920, shnum=6, shentsize=40, and 11920 + 6*40 = 12160 against a 31,556-byte file, while every section name resolves to 'ELF' with size 0.  **Answered the same day**: the tail's leading `u32` is an **offset, not a length** - 7,840 against a 27,232-byte `.ord`, so the tail belongs *inside* the object.  Overlaid there the table resolves (`.data`, `.shstrtab` at exactly 7,840, `.strtab`, `.symtab`, `.rel.data`) and `prefix + len - 4 == shoff + shnum*shentsize` on 12/12 pairs.  Where the prefix equals the `.ord` length an overlay is the same bytes as appending, which is why the length reading worked everywhere else.  `join` now overlays and validates with `_table_reads` (names must resolve) instead of `_table_fits` (arithmetic only, which passed on the broken join).  **But the correction matters more than the fix**: these objects are not lost meshes.  Their 60 symbols are `__MATRIX4 *:::EAGLAnimationBuffer` and `__Bone:::Player____model*.<joint>` - they are skeletons, so `models=0` was always the right answer.  **But `static.big` / `pstatic.big` were a different story**: a third defect had `_decode_packet` take `streams[-1]` as the display list when FIFA puts a one-entry `__EAGL::TAR` texture pointer *after* it - a 1-byte "display list" that failed the opcode check and returned `None` silently.  Choosing by opcode instead of position gives **14 of 22 objects and 10,567 triangles** where there were 0: `Player__HiBody4` 4,977, `Player__MedBody` 1,299, `Player__LowBody` 669.  Three stacked defects - sibling lookup, prefix-as-length join, display-list choice - all had to go before a triangle came out.  **Across all six EAGL containers on the disc the old rule gives 0 of 89 objects and the new one 81 of 89, 44,927 triangles** (old rule simulated faithfully, same bounds and opcode test applied inline).  No regression where the list is last: the search runs from the end.  **A fourth defect, found by the new warnings themselves**: a packet can bind two matrices (`gpModelViewMatrix` then `gpViewMatrix`) and the stream loop stopped at the second tag, so 32 packets collected zero streams.  Skipping the run of matrix tags takes the disc to **85 of 89 objects, 45,647 triangles**.  A fifth and sixth followed from the next warning: a vertex can carry **one** matrix byte (FIFA's shadows use five-byte records `2d 00 00 00 00`), and the attribute offset `f0` was derived from the stride rather than from the matrix-byte count actually chosen, so the indices were read a byte early.  **The disc finishes at 89 of 89 objects and 46,251 triangles**, from 0.  A seventh: the skeleton **magic was a tag** - `_SKEL_MAGIC` is `c0da 01fe c0da` and FIFA's is `c616 01fe c616`, the same shape with a different `u16`, confirmed by the bone count that follows being 51 against exactly 51 `__Bone` symbols.  Checking the shape gives the disc **11 skinned scenes, largest 51 joints**, where it had none, and still rejects the one header (`0743 0050 c3d4`) that really is not a skeleton.  Remaining: five index complaints and one missing display list, no lost geometry.  **Do these generalise?  Checked on Fight Night Round 2: no.**  Its 247 pairs join and read (121 symbols, 76 `__Bone`, 275 shader refs) and still give 0 objects - because that generation has **no display list in the packet**: three streams of equal count, all floats, none opening on a GX opcode.  A different reading is needed, and the groundwork is done: the **first stream is positions** and reads cleanly as 125 big-endian f32 triples, 100%% finite, bbox `[-7.82, 40.86, -5.33]..[7.72, 50.39, 7.44]`, and the array is **stored twice** (identical for exactly 1500 = 125x12 bytes, then diverging).  What is missing is topology - no display list, no index stream, so the primitives live outside the packet.  One more silence was fixed on the way: `extract` attached warnings to a Scene, so an object producing no Scene discarded every diagnostic - 247 objects with no explanation - and a barren object now raises with a summary |
| `PermissionError` / `NotADirectoryError` on export | 2 | 6 | **fixed 2026-09-02**: a container named `pl01.bin` expands into a *directory* of that name, and the glTF buffer for a model called `pl01` wants the same path - writing a file where a directory sits is a `PermissionError` on Windows and killed the whole export.  The buffer now falls back to `<name>_buf.bin` and the glTF's `uri` names the file actually written.  The `NotADirectoryError` (a colon in `noa_warn:en.gc`) is a **stale row** - `_rel_out_path` already sanitises it, verified |
| `ea` / `MemoryError` | 4 (Madden NFL 2002, NFS Carbon, NHL 06, NASCAR Thunder 2003) | 5 | **fixed 2026-09-02**: a texture header claiming 65536x65536 was believed all the way into numpy - a (8192, 8, 8192, 8, 4) array, 16 GiB - and a `MemoryError` is not something a plugin catches as "not my format", so one bad texture could take a disc's rip with it.  `gx_texture.decode` now raises `ValueError` outside 1..4096 and over 4096x4096; GX hardware tops at 1024x1024 so nothing real is refused |
| `gx` / `KeyError` | 8 | 36 | **fixed 2026-09-02**: `generic.find_toc` stopped on a 0.15-second deadline, so `generic.expand` was non-deterministic - the manifest named a container's members and a later fetch produced a different set, and the model died on a bare `KeyError` on its own path.  Every recorded example was a `gNNNN` name, generic's own scheme.  The stop is now a work cap (`TOC_MAX_WORK`, in (base, stride) pairs), a pure function of the bytes; the full search is 2,048 pairs against a 4,096 cap so nothing is cut, and it runs in 31-47 ms against the old 150 ms |
| `hsd` | 8 (Disney Sports: Skateboarding, One Piece Treasure Battle, Dragon Drive, Rave Master, Kururin Squash, Pokemon Channel, bobobo-bo bo-bobo, Virtua Quest) | 228 | `RecursionError` - the parser guarded cycles but not depth, so one absurd `child` chain killed the whole file.  `MAX_JOBJ_DEPTH` truncates that branch and `Jobj.walk` is now iterative |

The `res` one is worth understanding rather than just fixing.  `export()` tolerates a `-1`
material; the **separate `thumbnail()` pass** indexes `material_colors` by it, and `[][-1]`
raises for the whole model.  Two attempts to reproduce it called `export(thumbnail=False)` and
passed cleanly.  And because `thumbnail()` returns early on a model with no triangles, it hit
**only the meshes that had geometry** - exactly the ones worth having.

**The technique that found all three**: `batch_results.jsonl` records a `fail_examples` list per
disc, and grouping the first example of every disc by plugin and exception sorts 103,130
recorded failures into a dozen kinds in one pass.  Worth re-running after any batch.

`ripcore.gltf.thumbnail` now falls back to grey for a material it cannot resolve, because a
thumbnail is a convenience and must not be able to fail an export.

## Cross-cutting traps worth re-reading before writing any plugin

1. **`detect` and `is_container` get 64 bytes.**  `gcrip.classify.SNIFF_BYTES`.  A check that
   reads past byte 64 returns False for every real file, silently.  This has bitten three times
   (`pod`, `tr_pkg`, `dds_pack`) and once dormantly (`billy_lnd`, which cost Billy Hatcher its
   79 terrain files).  Detect on the magic, validate in `expand`/`extract`.
2. **A container needs a no-op `detect`/`extract` pair** or `all_plugins()` never registers it.
   `afs` and `lpac` were dead this way - 31 discs of AFS archives were never expanded.
3. **Normal agreement cannot search for a layout.**  On a near-planar point set every face
   normal agrees and the metric saturates above 0.98.  Use it to confirm a layout you already
   have; add a non-degeneracy guard when searching.
4. **Matching magic is not matching layout.**  High Voltage's TPL carries Nintendo's exact
   magic and a different header.
5. **`gcrip dump` is one single-threaded process - use `--shard i/n`.**  A single worker used
   **1% of a 64-core machine** with the disk at 0%; six shards over one `--out` took it to 20%.
   The run is resumable (finished discs are skipped from `batch_results.jsonl`), so switching a
   running pass to shards costs nothing.  Do not go wide enough to thrash the single spindle that
   holds both the ISOs and the dump.
6. **A disc queued for a pass has no dump directory.**  Pass 7 deletes each game's folder before
   re-ripping it, so `disc_manifest.json` vanishes mid-run and any tooling that reads offsets from
   the dump breaks.  Read the ISO directly, or keep a local sample, for anything on the pass list.
7. **Measure from the right offset.**  Blitz format 21 looked like an unknown codec at 0.39
   bytes per pixel purely because the pixel data was measured from 0x1000 instead of from each
   descriptor.
8. **An index array can address more than one vertex array.**  Darkened Skye's 16-byte triangle carries
   two `u16` triples - one into the positions, one into the uvs.  Reading the first triple against the
   wrong array parsed 157 of 255 models and looked like a coverage problem rather than a layout one,
   because the uv array is usually the larger of the two so most indices happened to fit.
9. **A float array in [0,1] on a textured model is uvs, not normalised geometry.**  Assuming the latter
   cost a pass on Darkened Skye and produced the wrong conclusion that the format had no vertex array.
10. **An array offset can be relative to its own header word.**  `res` `rdms` stores five array
    offsets in a row and each is measured from where it sits, so any single base makes the first
    array right and every later one wrong by four bytes more than the last.  That is what "consistently one element short" meant.
11. **A wrong palette position can still draw the picture.**  Acclaim's textures keep the palette
    after the pixels; reading it first gives a jersey with legible lettering and colour noise
    elsewhere, which reads as a palette-*format* problem and sends you looking in the wrong place.
12. **A "size" field beside a count is not automatically a stride.**  `ASB_TEXTURE` stores the first
    image's size at +28; on the files where every image is the same size the two readings agree,
    which is exactly why the mistake survives - it cost 219 of 288 files on one disc.
13. **A length field beside a size field is often the *stored* length.**  Free Radical's entries
    carry the unpacked size and the packed one; on the archives that store their members plainly
    the two agree, so reading the wrong one works everywhere until it silently walks a compressed
    archive off the end of its data region.
14. **An empty member is not a wrong reading.**  Disqualifying a whole table because one entry has
    zero size threw away a fifth of Future Perfect's archives.
15. **Bytes divided by pixels is not bits per pixel when mips are stored.**  Free Radical's textures
    keep the whole mip chain, so a `CMPR` image reads as 8 bits a pixel and points convincingly at
    `I8`, `IA4` or a palette that does not exist.  A full chain is four thirds of the top level -
    divide that out first, and the ratio then identifies the format instead of hiding it.
16. **An extension is not a format, and a header read out of a member you have not confirmed is
    uncompressed tells you nothing.**  FutureTactics' 1,207 `.DFF` were reported as RenderWare
    models on the strength of the name; their "chunk headers" were packed bytes, and every one of
    them has the archive's compressed flag set.  Check the flag before reading the header.
17. **A container plugin that claims an archive and yields nothing used to shadow the next one
    that would open it.**  Both `rip.py` and `manifest.py` broke out of the container loop on the
    first plugin whose `is_container` said yes, whatever `expand` then returned.  `feporr` claims
    every `.pak` with a `pack` magic - including THQ's, which it cannot read - and sorts sixth
    against `thq_pack`'s thirtieth, so Avatar: The Last Airbender lost all nine of its archives
    (699 MB).  Both loops now skip a plugin that produced no members; `tests/test_container_shadowing.py` pins it.

| Harry Potter: Goblet of Fire | 1 | **not a `.hog` disc**: eight files, four of them EA `BIGF` totalling 956 MB, which `plugins/ea` already claims.  `data.big` holds 153 members, 152 of them `.str` RenderWare streams stamped `0x1802FFFF` (RW 3.6) with EA's own chunk ids (`0x071C` names, `0x0716` build paths).  The three smallest members carry no stock geometry chunks and no native groups, but so are the two **largest** members (7.3 MB and 7.2 MB), which are gameplay scripts - `CharmConfigObject`, `RicochetShot`, `BubotuberPusShot`.  A `0x98` strip scan on them gives 261 runs and 6,016 vertices and it is **noise**: the four index columns agree on 1-2% where a real group agrees on 100%.  **All 153 members' type tables have now been read** (1.2 MB of heads): the vocabulary is `cModelBehaviour` (88 members), `cLightModulatorBehaviour`, `TriggerBox`, `PhysicsWorldCollision`, `StaticSceneProp`, `NavigationMesh` - a level and entity database that *references* models.  Zero `rwID_` names in the first 96 KB of any member (14.8 MB searched).  Untested: `music.big` and the 277 MB `gof_f.elf` | see [formats/harry-potter-gof.md](formats/harry-potter-gof.md) |

| Frogger `PRS1` codec | 2 (Ancient Shadow, The Rescue) | **closed 2026-09-03** - Okumura LZSS with absolute ring positions, read out of the DOL (`gcrip/formats/prs1.py`); members are RenderWare 3.6 streams with CLUMPs and PI texture dictionaries; 186 models / 111k triangles from the first 8 MB.  [formats/frogger-hfs.md](formats/frogger-hfs.md) | re-rip both discs (wave 33) |
