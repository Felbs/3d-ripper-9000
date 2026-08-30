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
must come from a header field that has not been identified yet; the 20 bytes at 0x108 are
not a per-file record chain either (the next 20 bytes land inside the text), so the dictionary
is a separate table, not inline.  Blowout ships 7 PODs
(GCBSET 52 MB, GCBSOUND 51, GCBPKG 46, GCBART 8, COMMON 7, GCBMODEL 3, LANGUAGE 18 KB).

### `res` resource files - CRACKED (Digimon Rumble Arena 2, Lemony Snicket, Samurai Jack)

`gcrip/formats/res.py` + `plugins/res.py`.  Big-endian header apart from the version word:
`char "res
" | u16 version (7, little-endian) | u16 | u32 data offset (0x1000) | u32 data
size | u32 | u32 | u32 | u32 directory offset | u32 directory size | u32 tag count` and then
one 8-byte record per tag kind.  The directory sits at the END of the file: `u32 entry count`
followed by 20-byte entries `u32 id | char tag[4] | u32 offset (relative to the data area) |
u32 size | u32 flags`.

Counts over the three discs: Digimon 2,940 `.res`, Lemony Snicket 574, Samurai Jack 290.
Section tags: `rdms` (by far the most - 4,415 in six Lemony Snicket files), `surf`, `gshd`,
`tern`, `sdta`, `node`, `ndbg`, `levl`, plus `wave` / `musc` / `mdat` audio and `strg` /
`indx` text.  On Samurai Jack's `game_outro.res` a `surf` section starts
`00 00 00 00 | 00 22 1b ac | 03 21 01 08 | 00 80 00 80` - the `0080 0080` pair is a 128x128
image size, so `surf` (and `sdta`, same shape) are textures; `node` is 86% plausible floats
(the scene graph), `gshd` 89% (material / shader constants), and `rdms` is the mesh side.
Decoding `surf` (dimensions + GX format) is the next step and should be quick.

### `res` section internals (probe)

A `surf` section is not a bare texture: after `u32 0 | u32 id | u8 flags[4] | u16 width | u16
height` comes a table of increasing u32 offsets whose deltas form a mip chain - 0x3ffc, 0xffc,
0x3fc, 0xfc, 0x3c, 0x1c ... i.e. 16,380 / 4,092 / 1,020 / 252 / 60 bytes, four short of the
exact 128x128, 64x64, 32x32 ... sizes for one byte per pixel.  The base level decodes to only
75 distinct byte values with a mean of 6, so it is index data, and the 264-byte block the
table points at first holds more offsets (`00 0b 0a 1c`, `00 0b 0a 58`, ...) rather than a
palette - so `surf` nests another table and the palette lives elsewhere.  GX decodes (CMPR,
I8, RGB5A3, CI8 with the 0x424 block as a palette) all produce noise, so neither the tiling
nor the palette is settled yet.  `sdta` repeats the same header one byte over.

### `.dgc` = Kalisto TotemTech (Jimmy Neutron, Spirits & Spells, SpongeBob: Revenge of the
Flying Dutchman)

The files open with a 0x4d-byte banner - `TotemTech Data v1.75 (c) 1999-2002 Kalisto
Entertainment - All right reserved` - then zero padding to 0x102 and the payload.  Spirits &
Spells ships 225 `.DGC` (241 MB) beside 291 MB of `.wav`; the small `RTC_*.DGC` files carry
byte-sized data in repeating 16-byte records (`20 d3 ff ff ff ff 00 00`), which reads as
audio / cutscene data rather than geometry - the level `.DGC` (5 MB) is where the models
should be, and is the file to open next for this cluster.

### TotemTech `.dgc` geometry (Kalisto) - partly cracked

The payload is NOT compressed (entropy 4.97; none of gcrip's decoders bite, and none should).
It is structured binary mixed with text property dumps, and the geometry sits in the open:

* vertices - a big-endian `f32 xyz` array (Spirits & Spells `LEVEL07a.DGC` has a 1,922-vertex
  run at 0x103A5C);
* faces - records of `u32 3 | u16 a | u16 b | u16 c` followed by a short, VARIABLE trailer
  (`00 00 00 01 02 00` in the cases seen), so the next record is found by scanning forward for
  the `3` count word;
* a mesh keeps its normals and uv arrays between the positions and the faces, so the faces
  have to be searched for in a window rather than expected immediately after the vertices.

Reading a run and its faces produces a correct model (a lamppost renders cleanly), so the
layout is right.  `gcrip/formats/totem.py` implements the primitives with tests, but there is
NO plugin yet: scanning finds only 8 meshes / 679 triangles across four levels while the files
carry ~36 `Geom` markers each, so mesh discovery is the missing piece - the `Geom` / `GeomDesc`
text markers and the u32 index lists that precede each vertex array are the obvious next lead.

#### TotemTech progress (second pass)

Anchoring on the FACES works far better than anchoring on the vertices: a mesh shows up as a
dense run of `00 00 00 03` count words (Spirits & Spells `LEVEL07a.DGC` has 38 such runs, and
the file carries 26 `GeomDesc` text markers), and each run's vertex array is one of the float
runs before it.  Pairing by "nearest array" recovers 24 of 38 runs; scoring the candidates by
how tightly the referenced vertices hang together (bounding-box span over median edge length)
removes the wild ones.  Yield over eight files per disc: Spirits & Spells 215 meshes / 10.7k
triangles, Jimmy Neutron 418 / 21.5k, SpongeBob 453 / 48.5k.

Still not shipped as a plugin: individual meshes render correctly (a lamppost is exact) but a
merged level still looks wrong, because heuristic pairing mixes arrays.  The fix is the real
header, and it is close: a `u16` vertex count (1922 for the verified mesh) sits 0x56e bytes
before its array, and the array itself is immediately preceded by the text `GeomDesc` followed
by `00 06 00 00 00 00 01 3a`.  Parsing that block - rather than scanning - is the next step,
and it should give exact vertex and face counts per mesh.
