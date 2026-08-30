# Open formats - what is left to crack

Live list, updated as work happens.  Ordered by return: discs affected first, then how close it
is to falling.  A format only leaves this list when it ships and a real disc yields models or
textures through the plugin chain.

Companion to [FORMATS.md](FORMATS.md), which lists what already works.

## Close - one focused session each

| format | discs | state | what is blocking |
|---|---|---|---|
| `res` `rdms` meshes | 3 (Samurai Jack, Lemony Snicket, Digimon Rumble Arena 2) | **it is a GX display list** - `98` strip opcode at the offset in w3, vertices of five big-endian `u16` attribute indices (10 bytes); column 0 indexes the 84-byte block as s16 position triples (14 x 6) | the strip count says 61 but only 57 records fit before the first block, and column 3 wants 16 elements from a 60-byte block.  Sibling `surf` textures already ship |
| Blitz `common_*` formats 17 and 19 | up to 9 | descriptor chain and formats 15 (`RGBA8`) / 21 (`CMPR`) ship | what codes 17 and 19 encode - 10 and 1 of a 60-pack sample |
| Terminal Reality `_dfm` | 3 (BloodRayne, Blowout, RoadKill) | 28 rigid parts, one bone index each; 46 geometry records of 36 bytes; 20-byte vertex by size arithmetic; `HVSI` skeleton reads with a correct anatomical parent tree | the vertex field layout.  Normal-agreement search is useless here - every high-scoring fit is planar-degenerate.  Needs an anchor that is not normals |
| FSTA `GKA` / `GGG` | 2 (Billy & Mandy, Kids Next Door) | archive and textures ship; these open `ISVH` | not yet entropy-checked - may or may not be compressed like `GMS` |

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
| Ratatouille `.dgc` | 1 | 320 files, opens with a version string `v1.06.63.01 - As...`; untouched |
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
5. **Measure from the right offset.**  Blitz format 21 looked like an unknown codec at 0.39
   bytes per pixel purely because the pixel data was measured from 0x1000 instead of from each
   descriptor.
