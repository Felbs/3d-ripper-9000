# Open formats - what is left to crack

Live list, updated as work happens.  Ordered by return: discs affected first, then how close it
is to falling.  A format only leaves this list when it ships and a real disc yields models or
textures through the plugin chain.

Companion to [FORMATS.md](FORMATS.md), which lists what already works.

## Close - one focused session each

| format | discs | state | what is blocking |
|---|---|---|---|
| EA `OBG ` terrain and `TXG ` textures | 4 (Tiger Woods PGA Tour 2003, 2004, 2005, 06) | **the container ships** (`gcrip/plugins/shoc.py`): 872 archives, 120 of 120 sampled parse, 7,482 members, among them 55.5 MB of `ter` and 39.8 MB of `txfh`.  `ter` opens `OBG ` with an `ARRA` chunk; `txfh` opens `TXG ` with a `HEAD` chunk and carries real texture names (`tbmulch`, `tbcp1`, `tbfw1`).  `gxscan` finds only 2-3 meshes per `ter`, so the terrain primitives are inside `OBG`/`ARRA`, not GX display lists | see [formats/ea-shoc-hog.md](formats/ea-shoc-hog.md) |
| Warthog `.hog` codec | 3 (Animaniacs, Looney Tunes: Back in Action, Harry Potter and the Sorcerer's Stone) | **the container ships** (`gcrip/formats/wart_hog.py`): all 101 archives parse, 165,704 members, among them 29,021 `.bmsh` meshes and 36,156 `.btga` textures - the largest pile of geometry left behind one codec.  A token `0xE0 | n` is a literal run of `(n+1)*4` bytes, verified on four anchors.  Match tokens are **not fixed width**: with the literal runs known, a fixed-width walk must land on the last byte, and over 3,732 streams two bytes lands on 541, three on 493, the best split on 613 - chance, with a long flat overshoot tail rather than a pad.  A sweep of 2-byte match encodings (every shift, five length masks, seven offset masks, offsets and lengths scaled by 2 and 4) decodes none of six known-length members exactly.  Length-extension grammars are **also ruled out**: the same sweep re-run with LZ4/LZO-style extension bytes on both the literal nibble and the length field, and with 16-bit offsets, decodes none of five known-length members.  Test vector: `frontend_cog1.lvl` and `frontend_cog2.lvl`, 199 packed to 386 out, differing in one byte | see [formats/warthog-hog.md](formats/warthog-hog.md) |
| Blitz `common_*` formats 17 and 19 | up to 9 | descriptor chain and formats 15 (`RGBA8`) / 21 (`CMPR`) ship | what codes 17 and 19 encode - 10 and 1 of a 60-pack sample |
| Terminal Reality `_dfm` | 3 (BloodRayne, Blowout, RoadKill) | 28 rigid parts, one bone index each; 46 geometry records of 36 bytes; 20-byte vertex by size arithmetic; `HVSI` skeleton reads with a correct anatomical parent tree | the vertex field layout.  Normal-agreement search is useless here - every high-scoring fit is planar-degenerate.  Needs an anchor that is not normals |
| FSTA `GKA` / `GGG` | 3 (Billy & Mandy, Kids Next Door, Charlie and the Chocolate Factory) | **not compressed** - body entropy 5.28 (`GGG`) and 6.82 (`GKA`) against 7.73 for `GMS`.  Magic is `ISVH` (`HVSI` reversed) but the fields are big-endian: the `u32` at +12 is the exact file size on both | what they hold.  Neither shows f32 runs, so any geometry is quantised.  Note the models are in `GMS`, which is compressed - these may be animation or collision |

## Mapped but blocked on a codec

| format | discs | state |
|---|---|---|
| Visual Concepts `DAT` | **5** (NBA 2K2, NBA 2K3, NFL 2K3, NCAA Basketball 2K3, NCAA Football 2K3) | **the largest cluster left**: each disc is nine files, one of which is a 0.8-1.3 GB `game.dat` holding the whole game.  **the container ships** (`gcrip/plugins/vc_dat.py`) and all five discs tile exactly - 9,380 named members.  What is left is the `.IFF` payload, which is 1,916 of NBA 2K3's 1,968 members.  Blocked on the `.IFF` payload.  It is **byte-aligned** - literal text (`street`, `ADDING`, `.bin`) sits on byte boundaries, which rules out a bit-packed flag stream - with a 16-byte header and short control groups shaped `NN 00 MM`.  A sweep of plain LZSS (both bit polarities, both bit orders, both endiannesses, 11/12/13 offset bits, length +1/+2/+3, literal header 0/8/12/16/20/32 counted into the output) hits the exact length on none of 47 members, as do LZ4 and every decoder gcrip has.  A pair differing in seven bytes (`AH999.IFF`, `ANIMS.IFF`) isolates the control bytes for whoever picks this up | see [formats/visual-concepts-dat.md](formats/visual-concepts-dat.md) |
| `.hog` WART3.00 | 7 (Harry Potter x2, Looney Tunes, Animaniacs, Tiger Woods x3) | directory walks by tiling; every member compressed with a private LZ.  Four standard LZSS variants fail within a few bytes |
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
| Avatar `.rad` objects | 1 | `thq_pack` now opens all nine of Avatar's archives (245 members, 699 of 700 MB) but every member is a `.rad` object (`rad0` + a section table) and nothing reads them.  Jimmy Neutron's version-0 archives are handled and do yield models | |
| Spawn / Scorpion King `PHM` geometry | 2 | both discs' `.wad` open and all 12,018 `TIM` decode.  **`PHM` is the model** (a 4x3 `f32` matrix per bone, and it **names its textures inline** - `SPAWNTPAGE02`, `SPAWNTEYE` - so the models will come out textured), **`PHA` is animation** (`GRAPPLE`, `DIE_B`, `JUMP_`).  Blocked on the vertex format: `gxscan` finds no display lists, there is no `f32` run over 60 values outside the matrix block so the vertices are quantised, and the longest `u16` run - 3,712 values at 22,964 - clusters tightly like fixed-point coordinates rather than indices | see [formats/spawn-toc-wad.md](formats/spawn-toc-wad.md) |
| Gun `.ngc` | 1 | 2,928 hashed `.ngc` files; a 120-file magic sample gives no dominant header (37 x `00 01 00 30`, 35 x `74 5d cd 45`, 14 x `01 08 00 01`, then a long tail) | |
| Casper `.hff` geometry | 1 | the `hff` container ships and carves `PNG`, but Casper's 144 MB holds none.  Its bulk reads as `f32` unit vectors - triples like (0.652, -0.139, -0.898) - and the text file at the head names `.obd` and `.lvl` paths, presumably its members.  TONKA and Aquaman, the other two `.hff` discs, gave 1,897 and 2,800 textures | see [formats/hff-carving.md](formats/hff-carving.md) |
| AFS inner formats | 8 (Bleach, Auto Modellista, Capcom vs SNK 2, Digimon World 4, One Piece x3, Sonic Riders) | surveyed 2026-08-30 by reading each archive's index and the first eight bytes of its members.  **Most AFS is `ADX` audio** (`80 00 .. 03 12 04`) or MPEG - that is settled, do not re-check the big ones.  The archives with non-audio members are: Bleach `chr` / `scenario` / `com` / `stg` (2,238 members, all `16 00 00 00`), Digimon World 4 `area.afs` (1,382), Auto Modellista `afs01_gu` / `afs02`, Capcom vs SNK 2 `afs02` (holds `TIM2` textures) / `afs03`.  **Bleach mapped furthest**: a 12-byte outer header (`u32 22`, `u32 size = len - 12`), the tag `2d 00 02 1c` at fixed offsets 8/20/36/48/66216/99640 in every member regardless of length, and an ASCII asset name at +76 (`ich_1_cut2`).  `gxscan` finds no display lists in any of them | |
| `.arc` (cluster 2) | 4 (Cabela's x3, Over the Hedge) | **Cabela's**: a chain of raw zlib streams at 0x800-aligned offsets, ~2 MB each; `generic` already inflates the first.  Not shipped as a container - gxscan finds nothing in an inflated block and none of gcrip's magics appear, so it would cost ~600 MB of inflation per disc for no output.  **Over the Hedge**: `datasets.arc` (399 MB) is the only untouched data archive; `levels.arc` is entity script data.  Mega Man X Collection is a dead end (emulated 2D games) | see [formats/cluster2-arc.md](formats/cluster2-arc.md) |
| `res` `node` scene graph | 3 (Samurai Jack, Lemony Snicket, Digimon Rumble Arena 2) | `rdms` meshes ship (93,000 of them, 7.4 million triangles) but each comes out in its own space; the `node` sections are what would place them in a level, and `surf` textures are not matched to the meshes that use them | see [formats/res-rdms-meshes.md](formats/res-rdms-meshes.md) |
| Hunter `AGM` / `AGD` materials | 1 | `AGG` meshes ship (781,658 triangles) and carry their material **names**, and the `LJAM` archives hold 3,865 `TPL` beside them, but the text that maps one to the other (`MatAssignment` / `MaterialDatabase`, 3,465 files) is not read, so the meshes come out untextured | see [formats/high-voltage-ljam.md](formats/high-voltage-ljam.md) |
| `bin`/`dat` tail | many | cluster 10, never started |

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

## Dead ends - confirmed, do not re-probe

| thing | why |
|---|---|
| `.rws` | RenderWare **audio**, chunk 0x080d.  Not geometry |
| `.fsb` | FMOD sound banks - 5 discs |
| most AFS archives | ADX audio and MPEG video.  R - Racing, Soul Calibur II, Viewtiful Joe 2 and Sonic Riders have nothing else in theirs |
| `.mpq` (WWE x3) | video packs |
| Mega Man X Collection | emulated 2D games - there is no 3D geometry on the disc |
| Alien Hominid | the 45 `.pak` are ZIPs gcrip already opens, and their **1,948 members are 1,896 `RSND` sound records, 33 `SWF6` Flash movies, 11 `PIXL` textures, 7 `GLYP` font atlases and one `PDAG`**.  It is a Flash game: the artwork is vector data inside the SWFs, not textures.  The 11 `PIXL` do decode - 128x128 `CMPR`, pixels at +96, and the word at +48 is the data end so the size identifies the format exactly - but eleven font-ish textures is not worth a plugin |
| TMNT world materials | genuinely untextured in the source data |

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
