# GameCube backlog map (measured 2026-08-29 night)

What is actually left, and which clusters are real.  Method: `batch_results.jsonl` gives each
disc's status; each game's local `disc_manifest.json` gives every file with its size and disc
offset; for the open discs I read the first 32 bytes of their three biggest non-audio files
straight from the ISO (18 s for 430 discs) and clustered on the magic.  Extension-based
clustering had been misleading - see the corrections below.

## Status (638 discs)

| state | discs |
|---|---|
| models ripping | 155 |
| textures only | 168 |
| nothing | 262 |
| being re-ripped in passes 6 / 7 | 53 rows pulled, ~95 discs queued |

So **430 discs are open**, and the tail is long: the largest single magic cluster is 15 discs
(and that one is `.ELF`, i.e. code, not data).

## Corrections to the extension-based ranking

- `.rws` (6 discs: Asterix XXL, Burnout 2, CoD Finest Hour, Frogger, Madagascar, Piglet) is
  **RenderWare audio**, chunk 0x080d in `music/`, `AUDIO/`, `Streams/` - not geometry.
- `.wad` (Gun and friends) is **audio** as well (`streams/streamsn.wad`, 583 MB); Gun's data is
  2,918 `.ngc` files - Neversoft asset packs with no common magic (hashed names).
- `.arc` on the Cabela's discs is one 293 MB chain of zero-padded zlib blocks; inflating gives
  FUN Labs' own formats (`FSBF` 576, `GCT ` 249, `FMBF` 99, `FABF` 67, plus script text and
  1.5 MB data blocks).  gxscan finds nothing in the big blocks, so the models need real work.
- `.pak` looked like a 15-disc cluster; only Avatar actually uses the `pack` magic (now read by
  `gcrip/formats/thq_pack.py`), and its members are `rad0` objects - a proprietary section
  format with `.data` segments, no RenderWare inside.

## Real clusters, by magic of the biggest data file

| magic | discs | games | note |
|---|---|---|---|
| `PK..` ZIP | 8 | Alien Hominid, Freedom Fighters, Hitman 2, NFL Blitz 2002 / 2003, Powerpuff Girls, Wallace & Gromit, X-Men Legends | **done**: `gcrip/plugins/zip.py` expands them; X-Men Legends holds 875 `.fb` + 206 `.igb` (Intrinsic Alchemy), Alien Hominid 93 `.brec`, W&G 130 `.ovl` |
| `AFS` | 8 | Auto Modellista, Bleach GC, Digimon World 4, Cyber Formula, Sonic Riders, TMNT, Viewtiful Joe 1 / 2 | container already read; each game's inner format differs |
| `MPQ` | 3 | WWE Day of Reckoning 1 / 2, Wrestlemania XIX | the MPQs are `thp/thppac.mpq` - video packs, low value |
| `TotemTec` | 3 | Jimmy Neutron, Spirits & Spells, SpongeBob: Revenge of the Flying Dutchman | Totem Studios `.DGC` level files |
| `WART3.00` | 3 | Harry Potter: Sorcerer's Stone, Looney Tunes: Back in Action, Animaniacs | KnowWonder `.hog` archives |
| `res.` | 3 | Digimon Rumble Arena 2, Lemony Snicket, Samurai Jack | shared level container |
| `Rar!` | 2 | Dead to Rights, Pac-Man World 2 | RAR (needs an unrar path) |
| `BNDR` | 2 | ESPN Winter Sports, Evolution Skateboarding | Konami `.fbd` |
| `FANG` | 2 | Freaky Flyers (2 discs) | Midway `.mst` |
| `STBLzx` | 2 | Crash Nitro Kart, Jedi Outcast | `assets.gob` bundles |

Everything else is one or two discs per magic - genuinely per-game work.

## What this means for planning

The evening's wins (U8 archives, loose `.dds` / `.tga` / `.tgx` textures, Heavy Iron RWTX
naming, EBO `.gsh` binding, Blitz archive directory) all came from formats we already had that
were being **mis-detected**, not from new engines.  That seam is now largely worked out: what
remains is per-engine reverse engineering, roughly one evening per format with no guarantee,
and the discs-per-format ratio is 1-3 for most of the tail.  Expanding a container is cheap and
worth doing (it feeds the structure scanner named blobs), but it does not by itself produce
models: the Wallace & Gromit overlays, for instance, expand cleanly and yield 36 triangles.

## Cluster probes (overnight run)

### `.hog` WART3.00 (Harry Potter: Sorcerer's Stone, Looney Tunes: Back in Action, Animaniacs)

Header: `char "WART3.00" | u32 header size (0x28) | u32 total | u32 count | u32`, then 24-byte
entries from 0x18: `u32 offset | u32 compressed size | u32 uncompressed size | u32 name hash |
u32 name-table offset | u32 flags`.  Offsets are relative to the end of the entry table and the
first ten entries tile exactly (`offset[i] + csize[i] == offset[i+1]`), but the count word
(267 in `hfstart.hog`) overruns the file, so the table length still has to be derived by
walking the tiling.  Every member is compressed and the codec is NOT zlib / raw deflate:
decompressed text shows up as literal runs interleaved with control bytes (`3_Burr..ow`,
`ROULET..TE:`), i.e. an LZ77 with a private token layout - the four standard LZSS variants
(MSB / LSB flag order, literal = 0 / 1, 12-bit or 8+4-bit offsets) all fail within a few
bytes.  Cracking this is bit-level work on the token encoding.

### `.pod` POD3 (BloodRayne, 4x4 Evo 2, Blowout, RoadKill)

Little-endian: `char "POD3" | u32 checksum | char comment[80] | u32 file count | u32 |
u32 | u32`, file data from 0x108, and near the end a name table whose entries share suffixes
(`WORLD\EN_TEST.TXT`, then `T.TXT`, `TXT`, `XT` - the shorter names point into the tail of
the longer ones).  The entry table sits between the data and the names, but it is not simply
`names_start - count * entry_size` for entry sizes 20 / 24 / 28 / 32, so the dictionary offset
must come from a header field that has not been identified yet.  Blowout ships 7 PODs
(GCBSET 52 MB, GCBSOUND 51, GCBPKG 46, GCBART 8, COMMON 7, GCBMODEL 3, LANGUAGE 18 KB).
