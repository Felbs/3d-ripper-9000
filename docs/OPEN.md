# Open formats - what is left to crack

Live list, updated as work happens.  Ordered by return: discs affected first, then how close it
is to falling.  A format only leaves this list when it ships and a real disc yields models or
textures through the plugin chain.

Companion to [FORMATS.md](FORMATS.md), which lists what already works.

## Close - one focused session each

| format | discs | state | what is blocking |
|---|---|---|---|
| EA content on Tiger Woods 2003 / 2004 / 2005 | 6 | **Correction (2026-09-01): not resolved, and not audio-only.**  `hole.hog` on 2004 Disc 1 declares `ter` terrain (3,922,304 B), `txf` textures (1,471,392), `tgd` (1,675,700) and `gras` (617,136) in its `SHDR` chunks - the same resources `ea_obg`/`ea_txg` already rip on 06.  They are dropped because the payload inflates to 48-62% of the declared size, so only 57 members / 5,204 B of a 4.9 MB archive survive; the chunk walk itself covers 100%.  Reading the surviving members as the whole contents is what produced the old "audio and configuration" reading.  There are **six** Tiger Woods disc entries, not three (1,213 `.hog`).  The `ter` payload is **`OBG ` behind an LZ stream** - `OBG ` and the start of its `ARRA` tag are plainly visible 70 bytes into the first data chunk, between `88`-prefixed control bytes - so identifying that codec is the whole remaining job, and gcrip already reads `OBG ` and `TXG ` once decompressed.  Not zlib, and no `10 fb` refpack header at the stream start.  See [formats/tigerwoods-hog-budget.md](formats/tigerwoods-hog-budget.md).  Superseded detail:  The walk covers 99.998% of `hole.hog` and its members are `SONO` audio, `sfx `/`Rdat` audio and 100-byte `tACT` camera config - 723 `Cact` come to 0.05 MB.  The textures are the **41 `.fxg` (116 MB, `Data/Char/CharStrm/CharTex/24alltex.fxg`)**, raw tiled pixels with no header; what blocks them is that the dimension index is not a sibling - look in the 169 `.gcb` or the `.dol`.  2003's 35 `.skg` (21.7 MB) are the character-geometry candidate.  See [formats/tiger-woods-hog-contents.md](formats/tiger-woods-hog-contents.md).  Also open: 61 of 89 `OBG` members produce no scene, having no finite position array or too few triangles | |
| Kalisto `TotemTech` `.dgc` | 3 (Jimmy Neutron: Boy Genius, SpongeBob ROTFD, Spirits and Spells) | 383 files, 525 MB.  79-byte ASCII banner then a structured head and a compressed body - entropy by eighths 3.98, 5.14, 7.26, 7.81, 7.85, 7.44, 6.80, 6.50 - and **no name table anywhere**.  A block at 2,048 reads as fields (`u32 1`, then 640 and 512, plausibly dimensions); raw-looking RGB triples sit near the end.  Container and codec both, so a two-stage dive.  The other `.dgc` discs are **different engines**: Asobo Studio (Ratatouille, 320 files) and `MDGC0200` (Superman: Shadow of Apokolips, 255) | see [formats/dgc-adb-survey.md](formats/dgc-adb-survey.md) |
| `.adb` | 11 | **low value, do not size it by file count.**  14 large `Sounds.adb` on the Acclaim discs (200-660 MB, ascending `u32` offset table, no recognised magic in the first member) whose discs are already served by `asb_tex`; and 411 tiny ones elsewhere - Shadow the Hedgehog's 364 total 0.1 MB, about 300 bytes each | see [formats/dgc-adb-survey.md](formats/dgc-adb-survey.md) |
| Blitz `common_*` format 17 encoding (and 19) | **1 texture, not 9 discs - demoted** | **format 17's size is now known - 16 bits per pixel** - so the walk steps over it instead of stopping (`gcrip/formats/blitz_tex.py`).  Proved by where the data ends: at exactly `160 + w*h*2` the bytes become plausible f32, and over 40 textures the fraction of sane f32 at each boundary is 0.09 at 4 bpp and 0.06 at 8 bpp against 0.61 at 16 bpp.  The encoding is still open and **the three GX 16-bit codes are ruled out**: a smoothness test that identifies both known formats with an order of magnitude to spare (format 15 `RGBA8` 0.87 vs 22; format 21 `CMPR` 2.66 vs 60) gives format 17 no such drop - `IA8` 29, `RGB565` 44, `RGB5A3` 47.  Tile-seam and channel-correlation tests were tried and discarded for failing their own controls.  **Measured 2026-09-01: format 17 is one descriptor in 1,057** across 570 packs of the two discs whose texture packs ship as top-level files plus a recursive walk of PMW3's `AllPaks`, and format 19 is absent - so cracking it gains one 64x64 texture, not nine discs' worth.  Also rejected: it is **not** a linear/untiled 16-bit image, which is worse than tiled in all three codes | see [formats/blitz-gcp-gamecube.md](formats/blitz-gcp-gamecube.md) |
| Terminal Reality `_dfm` | 3 (BloodRayne, Blowout, RoadKill) | 28 rigid parts, one bone index each; 46 geometry records of 36 bytes; 20-byte vertex by size arithmetic; `HVSI` skeleton reads with a correct anatomical parent tree | the vertex field layout.  Normal-agreement search is useless here - every high-scoring fit is planar-degenerate - and both bounding-box tests come back empty.  The bone-local explanation for that is **still untested**: it needs bind transforms, and `HERO.SKL`'s bone records are not fixed-layout (the numeric fields do not line up beneath the names), so that has to be settled first.  Separately, `.SKL` is now known to be **99% animation** - 32 named clips from +1052 on a 30-byte name stride, payload from +2016 |
| FSTA `GKA` / `GGG` | 3 (Billy & Mandy, Kids Next Door, Charlie and the Chocolate Factory) | **not compressed** - body entropy 5.28 (`GGG`) and 6.82 (`GKA`) against 7.73 for `GMS`.  Magic is `ISVH` (`HVSI` reversed) but the fields are big-endian: the `u32` at +12 is the exact file size on both | what they hold.  Neither shows f32 runs, so any geometry is quantised.  Note the models are in `GMS`, which is compressed - these may be animation or collision |

## Mapped but blocked on a codec

| format | discs | state |
|---|---|---|
| Pokemon XD `FSYS` models | 1 (XD) | **Colosseum is done** (1,332 textures) and **XD's wrapper is now known**: `size, payload bytes, relocation count, 1`, payload at +32, then `count` u32 relocations - holds on 296 of 1,132 members.  Their payloads are `f32` model data behind that relocation table, not images, so this is a geometry job; the other 836 members are uncharacterised | see [formats/fsys.md](formats/fsys.md) |
| Visual Concepts `DAT` | **5** (NBA 2K2, NBA 2K3, NFL 2K3, NCAA Basketball 2K3, NCAA Football 2K3) | **the largest cluster left, and the codec is now most of the way down.**  The container ships (`gcrip/plugins/vc_dat.py`), all five discs tile exactly, 9,380 named members.  The `.IFF` payload is **not bit-packed**: it is a flag byte then eight items, LSB first, 0 = a one-byte literal and 1 = a three-byte match with `distance = ((b1 & 0x3f) << 8 | b2) + 1` and `length = b0 + 3`.  Verified against known plaintext - **58 of the 1,916 `.IFF` are stored uncompressed** (`PLAYERS` 10.2 MB, `LOADM` 4.5 MB, `CHWG` 3.5 MB, `AOSTREET` 1.2 MB) and give the exact output template.  4CCs are **byte-reversed** (`RTXT` is `TXTR`, `YALP` is `PLAY`), and a `u32` at +21 equals `declared - 16` on 38 of 45 members, so there is an oracle inside every member.  **971 textures already ship** from the 58 members stored uncompressed (`plugins/vc_iff.py`).  **The match rule is still open and is wider than it looked**: nine members hit the identical triple `01 c0 1b` at the identical position with one unknown each and need different lengths, which proves the `control == 0` rule is wrong too, not just the unknown one.  `b1` is a two-bit control (its low six bits are zero in every match ever seen).  The raw `BUILD*.DAT` supply the full plaintext to check a longer trace against | see [formats/visual-concepts-dat.md](formats/visual-concepts-dat.md) |
| High Voltage `GMS` | 3 (Billy & Mandy, Kids Next Door, Charlie and the Chocolate Factory) | header readable, size field exact; **payload entropy 7.73 behind a 2.39 header** - compressed, and not zlib / Yaz0 / Yay0.  Charlie's `JAM2` archives add **1,097 more `GMS`, 1,115 `GKA` and 1,204 `GGG`**, a third independent corpus to work the codec against |

Both need bit-level reverse engineering of a private codec before any geometry exists to parse.
Worth saying plainly: there is no mesh layout to hunt in either until the codec falls.

## Mapped, needs a session

| format | discs | state |
|---|---|---|
| TotemTech `.dgc` | 3 (Spirits & Spells, Jimmy Neutron, SpongeBob) | face-run scanning yields ~200-450 meshes/disc but merged levels are wrong; **the file has no directory at all** - nothing anywhere references the verified vertex array.  Exact extraction needs sequential parsing of the whole serialized stream from byte 0 |
| Asobo `.dgc` (Ratatouille) | 1 | **Asobo Studio "Internal Cross Technology"**.  Container mapped: 24-byte big-endian directory at 0x120 (`type | uncompressed | stored | block size | hash`), payload back to back, and **raw when uncompressed == stored and block size is 0** - 16 of 55 records, 29% of the archive, needs no codec.  Uniform 150/160 KB chunks mean it is a **paged virtual file system**, so cracking the codec yields an address space, not files - the name-to-page directory is a second problem.  See [formats/asobo-ict-dgc.md](formats/asobo-ict-dgc.md) |
| Darkened Skye `.skg` skeletons | 1 | `SKX` models ship (255 of 255, 135,749 triangles) and their skinning records give a joint index and weight per influence, but the positions are in **joint space** and there is no skeleton in the `SKX`.  The 17 `.skg` files open `\0GKS` and name a model, so the bone transforms are almost certainly there.  Until they are bound the exporter takes the first influence, which is coherent but not exact on multi-joint models | see [formats/darkened-skye.md](formats/darkened-skye.md) |
| Acclaim `.GDF` / `.SKN` meshes | 3 (All-Star Baseball 2002, 2003, 2004) | the textures ship (42,403).  **Header read**: `char name[20]`, then counts at +20/+24/+28/+32 (+20 materials, +28 meshes), `u32` attribute-block size at +36 and a trailing-block size at +40; **the attribute block starts at `len(file) - attr - trailing`**, which is exact on every sample.  Material names are 32-byte slots from +44, then one 44-byte record a mesh: `char name[16]`, flags, material index, material count, **vertex count**, a `f32` radius, an attribute code and the mesh's **byte offset into the attribute block**.  Vertex strides seen: **32** (`f32` position, `f32` normal, `f32` uv), **24** (`f32` position, a packed `u32` normal, `f32` uv) and **12** (position only) - each confirmed by `count * stride` filling the mesh's span.  Blocked on the **index data**: `StickBat.GDF` ends in ordinary GX display lists (`0x98`, three `u16` indices a corner) but `brewers.GDF` has none at any stride and its trailing block is a `C8` texture with an `RGB5A3` palette, so the two files index their vertices differently and the second scheme is unread | see [formats/acclaim-asb-textures.md](formats/acclaim-asb-textures.md) |
| Free Radical `gcr` meshes | 3 (TimeSplitters 2, Future Perfect, Second Sight) | 2,467 in a 149-archive sample.  **Not GX display lists** - `gxscan` finds nothing in any of them.  The header is three or four big-endian offsets (`12, 7372, 29312, 7456` on a prop) that divide the file into a geometry region, a small block, an **embedded `CMPR` texture region** and a trailer.  The geometry region opens with 64-byte groups of repeated words (`00 00 04 12`, `00 00 80 3b`, `30 2e 40 00`, four of each) that look like register state, and `s16` triples that read as coordinates start after them.  Three `gct` codes (9, 11, 12) are also unidentified, together under 3% of the textures | see [formats/free-radical-pck.md](formats/free-radical-pck.md) |
| Image carving beyond `.hff` | 2 | screening the 190 dead discs' biggest data file for **PNG with an `IEND` terminator** found only FutureTactics' `files.pak` (388 in 16 MB, now handled by `ft_pak`) and Nickelodeon Party Blast's `f9078e7e.wad` (27).  So carving does **not** generalise widely - worth recording so it is not re-tried.  The apparent JPEG hits (525 in a speech file, 521 in a texture pack) are `ff d8 ff ex` matching inside dense data and were not checked by decoding | |
| FutureTactics member codec | 1 | the `ft_pak` container ships and its 2,403 uncompressed members decode, but **3,055 are compressed** - every `.DFF`, `.AN2`, `.ANM`, `.XML` and `.FNT` sampled.  A compressed member opens `u32 unpacked size` then a second word, and the codec is private: zlib in three window modes, gzip, refpack, prs, yaz0, yay0, lzo, avlz, lzr and jade_lzo all fail.  A per-item-bitmask sweep is also ruled out: the stream opens with **36 literal bytes uninterrupted** and the best any variant reproduces is 3 of them.  The byte before them is a **parameter, not a control byte** - across 28 packed members it only takes values 0xE2-0xE8, ten `.XML` share 0xE8 with an identical literal run, and `.CUT` members sharing the same two literal bytes carry four different values.  Layout: `u32 unpacked size | u8 parameter | data from +5`.  **A complete test vector is in the note** - a member whose plaintext is known because it is XML.  Whether the `.DFF` are RenderWare underneath is unknown; the extension is the only evidence | see [formats/futuretactics-pak.md](formats/futuretactics-pak.md) |
| Climax `.bad` inner container | 3 (ATV: Quad Power Racing 2, Hot Wheels World Race, The Italian Job) | **the codec is cracked** - ring-buffer LZSS, 4096 ring, flag byte low bit first, `position = lo | ((hi & 0xf0) << 4)` absolute in the ring, `length = (hi & 0x0f) + 3`, zero fill (`gcrip/plugins/climax_bad.py`).  Hot Wheels decodes to 100% printable text and ATV's header to clean big-endian words.  The whole game on each disc is now reachable.  What is left is the container inside: the payload carries 643 part names (`frwheelcentre`, `rlmudguard`, `GEN_quadmud_01`) but the geometry is **not GX display lists** - `gxscan` finds 10 meshes in 12.7 MB of ATV and none at all in the other two.  Needs the directory and the vertex record | see [formats/climax-bad.md](formats/climax-bad.md) |
| Jimmy Neutron: Attack of the Twonkies `.pak` | 1 - **stale, see below** | **Avatar is done** - a `.rad` is a pack inside a pack whose `.rcb` leaves are zlib, and the `g4rc` objects inside are CMPR textures with the dimensions packed into bits 0-7 and 10-17 of the word at +16 (`plugins/thq_g4rc.py`, 486 textures from three archives).  Twonkies shares the `pack` magic and 23 archives / 1,013 MB, but its leaves are not `g4rc` and yield nothing | see [formats/thq-g4rc.md](formats/thq-g4rc.md) |  **Corrected 2026-09-01**: this disc is not dry.  It exports **1,938 models and 649,407 triangles** today, through its 2,007 `.rws` and 2,215 `.anm` - the note's premise, that the `.pak` leaves yield nothing, was about the wrong files.  What the `.pak` hold is a separate question and a much smaller one.
| Spawn / Scorpion King `PHM` **index runs** | 2 | **The vertex record is cracked** (`plugins/phm.py`): 20 bytes of `s16` - uv, position, normal/4096, then -1,-1 - pinned by unit-length normals on 1,987 of 1,987 vertices, two constant columns, and the array ending where the next section starts.  `SPAWN.PHM` gives 1,987 vertices and 3,488 triangles with materials named from the file.  **The strip-seam worry was unfounded**: every index reading scores the same, there is no triple structure (63.2% within vs 64.2% across), and splitting at the jumps *lowers* agreement (0.824 vs 0.832) while halving the triangles.  The mesh is simply smooth-shaded - a triangle's three vertex normals agree with each other at only 0.771 - so 0.832 against the averaged normal is the ceiling, and the reader is at it.  The header table is also still unread; the reader finds its arrays by arithmetic instead | see [formats/spawn-toc-wad.md](formats/spawn-toc-wad.md) |
| Gun `.ngc` | 1 | **The "hashed" premise was wrong** (2026-09-01): the names are ordinary once read whole - `af_intro_text.apk.ngc`, `gun_bannericon_01.img.ngc` - and sort into **1,233 `.apk` + 1,233 `.mpk` pairing exactly 1:1** (the `.ord`/`.orp` shape, and the first thing to test), 166 `.shd`, 158 `.img`, 119 `.pak`.  Nothing claims any of the 2,918: content-sniffing them all with `is_model`/`is_img`/`is_tex` matches none, and `is_img` rejects the 158 `.img.ngc` because it wants a first word of 2 where Gun has 0x04200000 - a newer generation, as with American Wasteland.  `.img` header is 32 bytes with what look like log2 dimensions at +10/+11, unconfirmed | see [formats/gun-ngc.md](formats/gun-ngc.md) |
| Casper `.hff` geometry | 1 | the `hff` container ships and carves `PNG`, but Casper's 144 MB holds none.  Its bulk reads as `f32` unit vectors - triples like (0.652, -0.139, -0.898) - and the text file at the head names `.obd` and `.lvl` paths, presumably its members.  TONKA and Aquaman, the other two `.hff` discs, gave 1,897 and 2,800 textures | see [formats/hff-carving.md](formats/hff-carving.md) |
| AFS inner formats | 6 (Bleach, Digimon World 4, One Piece x3, Sonic Riders) | surveyed 2026-08-30; **most AFS is `ADX` audio or MPEG - settled, do not re-check the big ones**.  **Auto Modellista and Capcom vs SNK 2 are now done**: their members hold Sony `TIM2` behind an ascending offset table, and 25 of 28 pictures decode (`gcrip/plugins/tim2.py`, see [formats/sony-tim2.md](formats/sony-tim2.md)).  The note's claim that CvS2's `afs02` "holds TIM2 textures" overstated it - only 2 of its 518 members are TIM2; the bulk open `00 00 00 10`.  Still open: Bleach `chr`/`scenario`/`com`/`stg` (2,238 members, all `16 00 00 00`, asset names at +76 such as `ich_t001`).  **2026-09-01: the recurring word is a typed record header** - `u16 type, u16 0x1c02` - and the large records chain exactly on `at + 12 + size`; a flat walk still fails on the first record, so the per-type header shape is what is needed next.  A type-0 record carries ~47 KB that reads as `I8` at width 256 (11.7-13.2 against a shuffled copy, noise ~1) but factors into no clean texture, so it is a lead and is deliberately not shipped and Digimon World 4 `area.afs` (1,382 members).  `gxscan` finds no display lists in either | see [formats/afs-inner-formats.md](formats/afs-inner-formats.md) |
| `.arc` (cluster 2) | 3 (Cabela's x3) - Over the Hedge, Shark Tale and The Sims now ship | **Cabela's** (**re-checked 2026-08-31** with the fixed RenderWare sniff: the six `WORLD` / `TEXDICT` chunks it appears to contain are false positives of 27-127 bytes that all raise `world without struct`; the conclusion holds): a chain of raw zlib streams at 0x800-aligned offsets, ~2 MB each; `generic` already inflates the first.  Not shipped as a container - gxscan finds nothing in an inflated block and none of gcrip's magics appear, so it would cost ~600 MB of inflation per disc for no output.  **Over the Hedge, Shark Tale and The Sims are done** - the container ships (`plugins/edge_arc.py`), 1,913 members.  The directory was never inside `datasets.arc`: it is the sibling `index.ind`, read through `NEEDS_SIBLING`.  The earlier note below was looking in the wrong file, which is why its record table had no ascending column - it was not an offset table.  See [formats/edge-of-reality-arc.md](formats/edge-of-reality-arc.md).  *(superseded: the archive-internal directory hunt)* | see [formats/cluster2-arc.md](formats/cluster2-arc.md) |  **Evolution Snowboarding is now done** - its 29 `.arc` are Konami `KCEO ARCDT` and ship (`plugins/kceo_arc.py`), 155 of 155 entries across four archives fitting and named; members are `BPXB`, which is the next step.  **Cabela's re-confirmed dead 2026-09-01** on a stronger test than before: the earlier note ran gxscan on one inflated block, and running it on the whole 21.6 MB concatenation still finds nothing.
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
RenderWare: Asterix 108 `.KGC` (~16 MB each; **recon done** - no RenderWare chunks and no offset table, so it is a serialised structure to walk from byte 0), Madagascar 16 `.gcn` (**cracked**), Piglet one 232 MB `PIGGCN.pkd` (**CRACKED** - `plugins/piglet_pkd.py`: a zlib chain covering all 232,370,273 bytes in 10,328 blocks, padded to 16 with assets spanning them, holding 936 CLUMP / 404 TEXDICT / 66 WORLD / 4,891 animations.  **The reader is the remaining gap**: renderware.py claims all 1,001 geometry assets and returns a scene for 68, 27,478 triangles.  Diagnosed - the clumps put GEOMETRY directly under CLUMP with no GEOMETRYLIST and declare numAtomics 0, both now handled, but most geometry carries the `rpGEOMETRYNATIVE` flag with no vertex arrays and **no NATIVEDATA extension inside the geometry chunk**, so the native data lives elsewhere - **ruled out**: not a NATIVEDATA extension (the geometry chunks hold only STRUCT and MATLIST) and not the 533 `0x1E` chunks (600-1,400 bytes each, 0.5 MB against a 425 MB archive).  It is a **raw block inside the clump**: the biggest clumps are 2.8 MB of which 2.85 MB is an unchunked tail after STRUCT, FRAMELIST and one 0x11010 plugin chunk, at entropy 7.37, opening on an image-like byte ramp, with no GX display lists in it), Frogger one 198 MB `gamedata.bin` (**directory solved** - an `hfs
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
