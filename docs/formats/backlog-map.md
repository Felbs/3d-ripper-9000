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

### `.pod` POD3 - CRACKED (BloodRayne, 4x4 Evo 2, Blowout, RoadKill)

Solved: the index offset the earlier probe could not find is stored at header **0x108**, is
unaligned, and points at the END of the file; `POD2` (4x4 Evo 2) instead keeps the index inline
at 0x60.  Entries are 20 bytes in both versions.  Full write-up in
[terminal-reality-pod.md](terminal-reality-pod.md); 38 archives, 19,678 members, offsets tile
exactly (1241/1241 on `TRUCK.pod`).  The models (`.BST` / `.BQS`) and textures (`.TEX`) inside
are the next step.

### TotemTech `.dgc` - third pass, still heuristic

Ruled out this pass: the file carries **no directory**.  Nothing anywhere in
`LEVEL07a.DGC` stores the offset of the verified vertex array (searched big- and
little-endian, absolute and relative to the banner and to the `GeomDesc` marker), so there is
no table to parse.  The `GeomDesc` lead was also weaker than it looked: only **1 of the 26**
markers is followed by binary, the other 25 are ordinary text property dumps
(`GeomDesc  = "" 

	Son  = ...`), so the markers do not enumerate meshes.  The one binary
marker is followed by `00 06 00 00 00 00 01 3a` and then the floats, and 0x13a = 314 is not the
mesh's vertex count (1922), so that word is not a count either.

That leaves sequential parsing of the whole serialized stream from byte 0 as the only exact
route - a much bigger job than scanning, and the reason the plugin is still held back rather
than shipped with heuristic pairing.

### `res` `surf` textures - CRACKED (2026-08-30)

`gcrip/formats/res_surf.py`, wired into `gcrip/plugins/res.py`.  Layout:

    +0   u32 0
    +4   u32 id
    +8   u8  format      2 = GX C4 (4 bpp), 3 = GX C8 (8 bpp)
    +11  u8  mip levels
    +12  u16 width       big-endian
    +14  u16 height      big-endian
    +32  palette, RGB565, two bytes an entry
    ...  mip chain, level 0 first

Nothing states the palette length; it is what remains once the mip chain is subtracted:
`palette = size - 32 - chain(w, h, format, levels)`.

**Two things had to be right before that arithmetic worked, and both were wrong at first:**

1. the **levels byte at +11**.  Sections with 8 levels are the majority; treating everything as
   a single level left 300+ of 552 sections unexplained, which is what made the earlier attempt
   look hopeless (44 of 345 fitting);
2. **GX tile padding**.  A mip level is not `w * h * bpp / 8` - it is padded to whole tiles, so
   a 1x1 level still costs 32 bytes.  Without that the leftover "palette" came out at 139, 341,
   203 bytes - odd numbers, impossible for two-byte entries.  With it they collapse onto 32, 64,
   96, 128, 192, 256: **387 of 552 sections land exactly on a standard palette size** and only
   20 fail to resolve.

The palette is **RGB565, not RGB5A3** - both decode `cave_armor.res` to the same three armour
plates, but RGB5A3 renders them nearly black where RGB565 gives red and gold.

Result: **532 of 553 surf sections decode** on Samurai Jack (37 flat masks), sizes 128x128
(204), 64x64 (168), 128x64 (65), 512x128 (21), 256x64 (16), 32x32 (15).  End to end through the
container chain: Samurai Jack 120 textures, Lemony Snicket 59, Digimon Rumble Arena 2 2, from
the 60 smallest `.res` on each - all three discs previously reported zero.

`rdms` (the mesh side, 4,415 in six Lemony Snicket files) is still undecoded.

### `res` `rdms` meshes - it is a GX display list (2026-08-30)

Header (big-endian `u32`), on Samurai Jack / Lemony Snicket:

    w1  block count (5)
    w3  offset of the display list (0x54)
    w4  vertex count (40, 688 on a bigger section)
    w7..w13   floats - a bounding box and a transform row
    +64 five block offsets; the last block runs to the end of the section

The region at `w3` opens `02 01 01 00 ...` then **`98 00 3d`** - the GX triangle-strip opcode
with a 61-vertex count.  So `rdms` is a display list, not a bare index array.

**Vertices are 10 bytes: five big-endian `u16` attribute indices.**  Confirmed two ways - the
recurring `00 07 00 07` pair sits at a constant offset within a 10-byte grid, and the first
records read (0,0,0,0,0), (1,0,0,1,0), (2,0,0,2,0), (3,0,0,3,0), which is what the start of a
strip over a fresh array looks like.

Over the 572 bytes available that gives **57 records**, with per-column maxima
`[13, 7, 7, 15, 0]` against block sizes `[60, 28, 28, 60, 84]`.  Column 0 lines up exactly:
max 13 means 14 elements, and the 84-byte block is 14 x 6 bytes - **s16 position triples**.

Settled since:

* **stride 10 is certain** - stride 9 yields column maxima like 65,281 while stride 10 yields
  13, 7, 7, 15, 0.  The fifth `u16` is always zero;
* **the five offsets at +64 are relative to 0x54**, not to the section start.  With that base the
  last offset lands exactly on the section end on every section tested, which is the check;
* **the four arrays are, in order, s16 position triples, s8 normals, RGBA colours and s16 uv
  pairs** - read straight off the content at those offsets on three different sections
  (`00 14 ff b9 00 65` positions, `20 e7 3a` normals, `3e 3e 3e ff` colours, `02 f4 ff 07` uvs).

Still wrong: the arrays come out **one element short** of what the index columns need - column 0
reaches 13 against 10 positions, column 3 reaches 15 against 15 uvs, column 2 reaches 7 against
7 colours.  Every column is over by exactly one, so the boundaries are not quite where the
offsets imply; building the mesh anyway gives inconsistent coherence (span/edge 2.2, 80 and 412
on three sections, where a real mesh is tens).

Do not ship until that reconciles - a one-element error shifts every index and silently produces
plausible-looking rubbish.
