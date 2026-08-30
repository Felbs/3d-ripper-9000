# Open formats - what is left to crack

Live list, updated as work happens.  Ordered by return: discs affected first, then how close it
is to falling.  A format only leaves this list when it ships and a real disc yields models or
textures through the plugin chain.

Companion to [FORMATS.md](FORMATS.md), which lists what already works.

## Close - one focused session each

| format | discs | state | what is blocking |
|---|---|---|---|
| `res` `rdms` meshes | 3 (Samurai Jack, Lemony Snicket, Digimon Rumble Arena 2) | **GX display list**, one `98` strip, vertices of five big-endian `u16` attribute indices at stride 10 (the 5th is always 0); stride 9 gives garbage so 10 is certain.  The five offsets at +64 are relative to **0x54**, and the last one lands exactly on the section end on every section.  The four arrays are, in order, **s16 position triples, s8 normals, RGBA colours, s16 uv pairs** - confirmed by content across three sections | the arrays are consistently **one element short** of what the index columns need (max 13 against 10 positions, max 15 against 15 uvs, max 7 against 7 colours), so the block boundaries are not exactly where the offsets imply.  Mesh coherence is inconsistent as a result (span/edge 2.2, 80, 412 on three sections).  Sibling `surf` textures already ship |
| Blitz `common_*` formats 17 and 19 | up to 9 | descriptor chain and formats 15 (`RGBA8`) / 21 (`CMPR`) ship | what codes 17 and 19 encode - 10 and 1 of a 60-pack sample |
| Terminal Reality `_dfm` | 3 (BloodRayne, Blowout, RoadKill) | 28 rigid parts, one bone index each; 46 geometry records of 36 bytes; 20-byte vertex by size arithmetic; `HVSI` skeleton reads with a correct anatomical parent tree | the vertex field layout.  Normal-agreement search is useless here - every high-scoring fit is planar-degenerate.  Needs an anchor that is not normals |
| FSTA `GKA` / `GGG` | 2 (Billy & Mandy, Kids Next Door) | **not compressed** - body entropy 5.28 (`GGG`) and 6.82 (`GKA`) against 7.73 for `GMS`.  Magic is `ISVH` (`HVSI` reversed) but the fields are big-endian: the `u32` at +12 is the exact file size on both | what they hold.  Neither shows f32 runs, so any geometry is quantised.  Note the models are in `GMS`, which is compressed - these may be animation or collision |

## Mapped but blocked on a codec

| format | discs | state |
|---|---|---|
| `.hog` WART3.00 | 7 (Harry Potter x2, Looney Tunes, Animaniacs, Tiger Woods x3) | directory walks by tiling; every member compressed with a private LZ.  Four standard LZSS variants fail within a few bytes |
| High Voltage `GMS` | 2 (Billy & Mandy, Kids Next Door) | header readable, size field exact; **payload entropy 7.73 behind a 2.39 header** - compressed, and not zlib / Yaz0 / Yay0 |

Both need bit-level reverse engineering of a private codec before any geometry exists to parse.
Worth saying plainly: there is no mesh layout to hunt in either until the codec falls.

## Mapped, needs a session

| format | discs | state |
|---|---|---|
| TotemTech `.dgc` | 3 (Spirits & Spells, Jimmy Neutron, SpongeBob) | face-run scanning yields ~200-450 meshes/disc but merged levels are wrong; **the file has no directory at all** - nothing anywhere references the verified vertex array.  Exact extraction needs sequential parsing of the whole serialized stream from byte 0 |
| Asobo `.dgc` (Ratatouille) | 1 | **Asobo Studio "Internal Cross Technology"**.  Container mapped: 24-byte big-endian directory at 0x120 (`type | uncompressed | stored | block size | hash`), payload back to back, and **raw when uncompressed == stored and block size is 0** - 16 of 55 records, 29% of the archive, needs no codec.  Uniform 150/160 KB chunks mean it is a **paged virtual file system**, so cracking the codec yields an address space, not files - the name-to-page directory is a second problem.  See [formats/asobo-ict-dgc.md](formats/asobo-ict-dgc.md) |
| Bleach GC | 1 | `chr.afs` / `scenario.afs` / `com.afs` / `stg.afs`, members open `16 00 00 00`; untagged structured records |
| Gotcha Force, Gundam vs Z, Auto Modellista, Capcom vs SNK 2 | 4 | data AFS identified per disc; inner formats untouched |
| `.arc` single-zlib | 6 (Cabela's x3, Evolution Snowboarding, Mega Man X CM, Over the Hedge) | inflates to FUN Labs' own formats (`FSBF`, `GCT `, `FMBF`, `FABF`); gxscan finds nothing in the big blocks |
| `.jam` `JAM2` / `LJAM` | 2 (Charlie and the Chocolate Factory, Hunter: The Reckoning) | separate formats from `FSTA`; untouched |
| `bin`/`dat` tail | many | cluster 10, never started |

## Dead ends - confirmed, do not re-probe

| thing | why |
|---|---|
| `.rws` | RenderWare **audio**, chunk 0x080d.  Not geometry |
| `.wad` (Neversoft) | audio; Gun's real data is 2,918 hashed `.ngc` files with no common magic |
| `.fsb` | FMOD sound banks - 5 discs |
| most AFS archives | ADX audio and MPEG video.  R - Racing, Soul Calibur II, Viewtiful Joe 2 and Sonic Riders have nothing else in theirs |
| `.mpq` (WWE x3) | video packs |
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
