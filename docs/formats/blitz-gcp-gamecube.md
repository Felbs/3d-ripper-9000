# Blitz Games .gcp packs (2026-08-29, container only)

Discs: Pac-Man World 3, Bratz Rock Angelz / Forever Diamondz, Bad Boys Miami Takedown, Cubix
Showdown, Fairly OddParents Shadow Showdown, Frogger Ancient Shadow, Chicken Little (+more) -
9 library discs on Blitz's engine (BlitzTech). Implemented: `gcrip/plugins/blitz.py` (container).

- `AllPaks.gcp` (335 MB on PMW3) = header (`u32 hash, u32 0x800 data start, u32 0, u32 count
  0x152, ...`) then ~90 uncompressed packages at 0x800-aligned offsets (entropy 3-5.5).
  `Music/*.gcp` share the header shape (`hash, 0x20, 0, count, 16-byte entries`) and hold
  compressed audio (entropy 7.4+), no packages.
- Package = `01 69 07` + build stamp string (`20/09/2005 at 15:32:48 by AJohnson`) then a
  type-tagged object stream: entity classes (`compoundfunctions`, `sectorpackages`, `sector`,
  `WorldSector`, `dynamic_light`, `refpoint`, `PropAttachment`, `<noentclass>`), tags 01/03/07,
  length-prefixed strings. Geometry lives inside "sector" packages as raw GX display lists:
  gxscan on a 9.4 MB sector package found 15 meshes / 13.7k tris (some garbage, bbox +-32768)
  in 171 s. Real serialisation format not decoded - the container split lets the gx fallback
  scan each package within budget; a proper parser is the next step for this family.

## Dig 2026-08-29 evening (what the pack really is)

`AllPaks.gcp` is an ARCHIVE of the per-level `.gcp` packs, not a flat pack: the header numbers
are 0x800-sector units, and `word[10] * 0x800` lands exactly on the name table (PMW3:
`0x27f86 * 0x800 = 0x13fc3000`, 338 NUL-terminated names such as `spectral_realm_3_sector01.gcp`,
`2dmazelevel_world.gcp`).  A 32-byte entry table follows at `word[4] * 0x800 = 0x13fc5000`:
`u32 hash | u32 hash2 | u32 size (0x800-aligned) | u32 sector | 16 zero bytes`.  Neither
`sector * 0x800` nor `size` as an offset lands on a package stamp, so one field is still
misread (maybe the sector is relative to a data base, or the pair is (offset, size) in a
different unit) - that is the next thing to settle for this family.

The object stream itself tokenises cleanly: `0x00` end, `0x01` u8, `0x03` u16, `0x05` u32,
`0x06` f32 (LITTLE-endian), `0x07` NUL-terminated string; a 9.4 MB package walks to 43k u8,
25k f32, 10k u32 and 5.4k strings.  It is the world / entity tree (placements, `simulation_object`,
`cpropblinker`, `refpoint`, mesh NAMES like `m_srx_oct_blinkplat`), not geometry: searching the
packages for GX signatures finds only false positives in high-entropy regions, so the meshes
live in the member `.gcp` files that the entry table addresses.  Entropy across a package
alternates 4-5 (token stream) and 7.2-7.7 (textures / compressed blobs).

## Archive directory CRACKED (2026-08-29 night)

`gcrip/formats/blitz_gcp.py` + `plugins/blitz.py` now split `AllPaks.gcp` into its named
members.  Header (big-endian): `u32 hash | u32 data start (0x800) | u32 | u32 member count |
u32 entry-table sector | u32 x5 | u32 name-table sector | u32 name-table size`; every number
that addresses the file is a 0x800 SECTOR index.  Entries are 32 bytes: `u32 sector | u32
hash | u32 size (bytes) | u32 index | 16 zero bytes`.  Pac-Man World 3: 338 names, 337
members covering 335,298,283 of 335,316,992 bytes (99.99%), and 334 of 337 members end
exactly where the next begins.  Names are per-level packs (`spectral_realm_3_sector01.gcp`,
`s_ancient_temple.gcp`, `resident.gcp`, `frontend.gcp`, `lipsync_*.gcp`): 150 sector packs,
90 `_fet`/`_fetm`, 27 world, 15 lipsync, 56 other.  A member repeats the header shape with
data start 0x20, and 307 of them are packs in their own right; those that carry Blitz's
package stamp (`01 69 07` + `dd/mm/yyyy at hh:mm:ss by <user>`) split further into packages.

Geometry: the members are NOT compressed (entropy 4-5.5 in the data regions) but they carry
no GX FIFO - the `08 a0` / `98 xx` byte pairs that a signature search finds are ordinary data,
and gxscan on the richest member (goen_2_maze16_sector01.gcp, 730 KB) yields one 46-triangle
mesh in 16 s.  So Blitz builds its display lists at run time from its own vertex / index
arrays, and the next step for this family is finding those arrays' headers inside a sector
package (the token stream names the meshes - `m_srx_oct_blinkplat`, `c_srx_oct_blinkplat` -
so a name-to-blob mapping exists somewhere in the member).

## Where the geometry is NOT (2026-08-30 survey)

Surveyed Bratz: Rock Angelz (1,680 loose `.gcp`) and Pac-Man World 3 (one 335 MB `AllPaks.gcp`,
338 members).  The archive reader works on both shapes; what it hands back is the question.

* **Level packs are pure object stream.**  `hub_s3_fetm.gcp` (827 KB) is one stamped package
  (`18/08/2005 at 12:57:38 by rgrant`) whose entropy sits at 4.8 with ~30% printable bytes
  right across the file - `hubsectors`, `sector`, `Hub World Sector`, `portal`.  No geometry.
* **Pac-Man World 3's members are the same.**  `mountains_1_world.gcp` (40 KB, the smallest
  member over 40 KB) is one stamped package with no float arrays either.
* **`common_*` packs are a different shape again** - 1,121 of them on Rock Angelz.  They are
  bare packs (data start 0x20, a count at 0x0c) with **no stamp at all**, so
  `gcrip.plugins.blitz` currently returns nothing for them; they are not compressed (no zlib
  anywhere), and the payload is sparse binary starting around 0x822.  `common_Default Faces
  Sector.gcp` is 1 MB at entropy 4.43, which reads like GX texture data.

## The reason a float scan finds nothing

**The floats are tagged.**  The object stream stores each value behind a type byte
(0x00 end, 0x01 u8, 0x03 u16, 0x05 u32, 0x06 f32 little-endian, 0x07 string), so a f32 in the
stream is `06 xx xx xx xx` - five bytes, not four.  Scanning for contiguous IEEE floats is
structurally blind to it and reports "no float arrays", which is exactly the wrong conclusion.

Searching for runs of `06` + a plausible float instead finds a **408-float run** in
`hub_s3_fetm.gcp` at 0x1a34a, values like (-161, -122, -161), (305, 0, 305), (0, -122, 0),
(-414, 644, -414) - coordinates, though the repeated pattern reads more like corner pairs than
a vertex array.  Pac-Man World 3's member tops out at a 10-float run.

So the object stream is the target, and decoding it is a well-defined job: the tag set is
already known, so a walker can turn a pack into a typed property tree, and the geometry (or the
references to it) will be inside that tree rather than in any raw array.  That, plus finding
out what the stampless `common_*` packs hold, is where the next session on Blitz should start.

## The object stream - CRACKED (`gcrip/formats/blitz_obj.py`)

After the stamp, the rest of a pack is one flat stream of tagged values:

| tag | payload |
|---|---|
| 0x00 | u8 - **not a terminator**, it carries a byte |
| 0x01 | u8 |
| 0x03 | u16 |
| 0x04 | u32 |
| 0x05 | u32 |
| 0x06 | f32, little-endian |
| 0x07 | NUL-terminated string |

**The whole thing turned on 0x00.**  Reading it as a nil marker stops the walk after 163 of
200,327 values - 0.1% into the package - which is exactly why earlier surveys concluded the
packs held nothing.  Giving it its one byte walks **99.7%** of Bratz: Rock Angelz's
`hub_s3_fetm.gcp` and **99.2%** of Pac-Man World 3's `mountains_1_world.gcp`, the rest being
trailing padding.  There is no length field: landing on the end of the package IS the proof
that the grammar is right.

It also explains the blank float scans - an f32 is five bytes here (`06` then the value), so no
two floats are ever adjacent in the file.

## What the level packs actually are

Scene graphs, not geometry.  One level pack yields 3,037 distinct strings: entity classes
(`CFWorldNodeParticleSystem`, `<noentclass>`), portal and sector names, and **asset references
by name** (`0_lightbeams_pinz01`, `sound_fstep_skates`).  The only float arrays are navigation
meshes - the longest run, 408 floats, follows the string `Transworld Navigation Mesh Edge`, and
Pac-Man World 3's member has no runs at all.

So the models are referenced from here but stored elsewhere, and the obvious candidate is the
**1,121 stampless `common_*` packs** on Rock Angelz (bare packs, data start 0x20, count at 0x0c,
uncompressed, sparse binary from ~0x822; `common_Default Faces Sector.gcp` is 1 MB at entropy
4.43, which reads like GX texture data).  `gcrip.plugins.blitz` still returns nothing for those,
and cracking them is the next step for this cluster - the scene graph now gives the asset names
to match against.

## The stampless `common_*` packs are TEXTURE packs (2026-08-30)

1,121 of them on Bratz: Rock Angelz, and `gcrip.plugins.blitz` returns nothing for any of them
because they carry no package stamp.  They are GX textures.

How it was pinned down, since two format guesses were wrong first:

* CMPR renders as vertical stripes - wrong;
* the bytes are 2-byte values repeated exactly 16 times, alternating every 32 bytes on a
  64-byte period.  **844 distinct u16 values and 88.5% of the data in runs of exactly 16** is
  not an image in any 16-bit format - but 16 AR pairs followed by 16 GB pairs is precisely a GX
  **RGBA8** 4x4 tile, which is 64 bytes.  Decoding `common_Default Faces Sector.gcp` that way
  gives Bratz doll faces - eyebrows, eyes, lips, two skin tones.

### Header

    0x000  u32 hash
    0x004  u32 data start (0x20)
    0x008  u32 0
    0x00c  u32 count (5, 6, 7 seen)
    ...
    0x820  u32 width
    0x824  u32 height
    0x828  u32 format code      0x0f, 0x11, 0x13, 0x15 seen (Blitz's own, not GX)
    0x1000 pixel data

Verified on three packs: `common_BP Earrings 01 Sector.gcp` is 32x32 with a payload of exactly
4,096 bytes = one 32x32 RGBA8 image; `common_Default Faces Sector.gcp` is 256x256 with
1,048,576 bytes = exactly four of them.

### What is still missing

The header at 0x820 describes only the FIRST texture.  Over a 60-pack sample the payload is an
exact multiple of `width * height * 4` in just **11** cases; the rest hold several textures of
differing sizes (`common_BP Hair_Hat 01 Sector.gcp` says 128x128 but carries 67,584 bytes).
Dimensions seen: 64x64 (27), 128x128 (15), 32x32 (9), 64x128 (5), 16x16, 16x32, 256x64.
Format codes: 21 (49 of 60), 17 (10), 19 (1), 15.

So the remaining work is the per-texture table - almost certainly the `count` at 0x00c with a
record list - and the meaning of the format codes.  Both are one focused session, and the payoff
is the texture set for nine Blitz discs.  Nothing is shipped yet on purpose: a reader that
assumes one texture per pack would mis-size four fifths of them.

### CORRECTION: format 21 is CMPR, and the descriptors are chained

The "0.39 bytes per pixel, likely compressed" note that stood here was **wrong**, and wrong for
one reason: it assumed pixel data starts at 0x1000.  It does not.  Each texture's data starts
**160 bytes (0xa0) after its own descriptor**, and the descriptors are chained:

    0x820  descriptor 0 (160 bytes)
    0x8c0  pixel data 0
           descriptor 1 (160 bytes)
           pixel data 1
           ...

The 160 is not a guess either - it is the `00 00 00 a0` word visible at 0x870 in every pack, and
the gap between the two descriptors in `common_BP Hair_Hat 01 Sector.gcp` is 8,352 bytes =
**8,192 (CMPR for 128x128) + 160** exactly.

Descriptor (seven big-endian u32):

    u32 width | u32 height | u32 format | u32 0x101 | u32 0 | u32 0xff000000 | u32 width*height

| format | encoding |
|---|---|
| 15 | GX `RGBA8` |
| 21 | GX `CMPR` |
| 17, 19 | not yet checked |

Decoded this way `common_BP Hair_Hat 01 Sector.gcp` gives two 128x128 textures, the first of
which is blonde hair.  Nothing is compressed anywhere in these packs.

Lesson: the wrong data offset made a perfectly ordinary format look like an unknown codec.  The
arithmetic that "proved" compression (0.39 bytes per pixel, below CMPR's 0.5) was really just
measuring from the wrong place.

## SHIPPED: `gcrip/formats/blitz_tex.py` + `gcrip/plugins/blitz_tex.py`

Walks the descriptor chain and decodes every texture.  The `width * height` field in each
descriptor is what makes the walk safe - a descriptor either satisfies it or the chain has
ended - so no length or count is needed anywhere.

Measured over a 120-pack sample of Bratz: Rock Angelz: **81 texture packs, 98 textures**, only
one of them flat/suspect.  Formats 21 (95) and 15 (3).  Sizes 64x64 (36), 32x32 (17), 128x128
(17), 16x16 (12), 64x128 (6), 256x256 (4), 512x256 (2), 16x32 (2) - a 512x256 one decodes to a
complete furnished room.

Confirmed on two discs, both of which previously reported **zero** textures and zero models:

* Bratz: Rock Angelz - 18 packs / 21 textures in a 25-pack sample;
* Fairly OddParents: Shadow Showdown - 5 packs / 59 textures in a 25-pack sample.

Not on the others: Bad Boys: Miami Takedown keeps its `.gcp` under `Flare/`, `Text/` and
`Speech/` and has none of these descriptors (a later engine generation), while Pac-Man World 3
and Bratz: Forever Diamondz keep almost everything inside one `AllPaks.gcp`, so their packs
reach this plugin through the container chain rather than as top-level files.

Formats 17 and 19 are still undecoded; the walk stops at one rather than guessing a size it
cannot verify.

## Texture formats 17 and 19

**Format 17 is 16 bits per pixel**, proved by where its data ends rather than by decoding it.
At exactly `160 + width * height * 2` the bytes turn into plausible big-endian f32 - the first
sample gives -7.96, 111.09, -3.49 - and across 40 textures the fraction of sane f32 in the 32
bytes at each candidate boundary is **0.09 at 4 bpp and 0.06 at 8 bpp against 0.61 at 16 bpp**.
(The 32 bpp boundary scores higher still, at 0.81, because by then the walk is well inside the
float data that follows; what matters is the first boundary at which floats begin.)  So the
walk now steps over a format 17 instead of stopping, and one undecodable entry no longer hides
whatever follows it in the chain.

**Which 16-bit encoding it is remains open, and the three GX candidates are ruled out.**  The
test that settles it is smoothness - the mean absolute difference between neighbouring pixels -
and it identifies both known formats with an order of magnitude to spare:

| format | correct code | its smoothness | best wrong code |
|---|---|---|---|
| 15 | `RGBA8` | **0.87** | 22.1 |
| 21 | `CMPR` | **2.66** | 59.7 |

Nothing does that for format 17.  Its best 16-bit candidate is `IA8` at 29, with `RGB565` at 44
and `RGB5A3` at 47 - no order-of-magnitude drop anywhere - so it is a 16-bit layout that is not
one of the three.  `I8` scores better still (18) but is excluded outright by the size.

Two tests were tried and **discarded because they fail their own controls**, which is worth
recording so they are not tried again:

* **Tile-seam continuity** (difference across tile edges over difference inside tiles): on
  format 21, whose answer is known to be `CMPR`, `CMPR` does not even reach the top four.
* **Channel correlation**: every greyscale-derived code scores a perfect 1.000 by construction,
  so it ranks `I8` and `IA8` above the truth on both controls.

Format 19 is only ever 16x16 on this disc and several candidates decode it to a constant image,
which no test can separate.

## How common format 17 actually is (measured 2026-09-01)

**One descriptor in 1,057.**  Counting every entry - not just the decodable ones - across
everything reachable without a large read:

| source | packs | descriptors | 21 | 15 | 17 | 19 |
|---|---|---|---|---|---|---|
| Fairly OddParents: Shadow Showdown | 170 | 734 | 692 | 41 | **1** | 0 |
| Bratz: Rock Angelz | 400 | 319 | 319 | 0 | 0 | 0 |
| Pac-Man World 3 `AllPaks.gcp`, recursed | 426 blobs | 4 | 0 | 4 | 0 | 0 |

Bad Boys: Miami Takedown, Cubix and Frogger: Ancient Shadow contribute **no descriptors at all**
from their small `.gcp` - consistent with the note above that Bad Boys is a later engine
generation.

So cracking format 17 would gain, on the discs where this format ships, **one 64x64 texture**.
The `up to 9 discs` framing in `docs/OPEN.md` was the count of discs on BlitzTech, not the count
that carry this format, and the item is demoted accordingly.  The one sample is cached as
`TrainingWishes.gcp`.

**Where the earlier 40-texture sample might be**: not located.  It is not in any of the above,
and the only reachable place left is Bratz: Forever Diamondz's own `AllPaks.gcp` (223 MB),
which was not expanded here.  Anyone resuming should start there and re-measure before
spending a session on the encoding.

### The census trap that cost two measurements

`blitz_tex.textures()` returns only entries whose format it can decode.  A census built on it
reports format 17 as **absent from every disc**, which is what my first two passes concluded.
`blitz_tex.descriptors()` now returns every entry and is the one to count with.

### Rejected: format 17 is not a linear (untiled) 16-bit image

Worth recording so it is not retried.  Every test in the table above decodes with GX tiling, so
an untiled layout would be scrambled by all of them and would explain the uniformly poor
scores.  It does not: on the 64x64 sample, linear is **worse than tiled in all three codes** -
`IA8` 90.2 against 76.0, `RGB565` 90.5 against 79.7, `RGB5A3` 93.6 against 82.4.

A planar reading - the first `w*h` bytes one 8-bit plane, the rest another - is the only thing
tried that produces anything: the *second* plane scores 31.8 tiled at 8x4, against 115 for the
first and 76-94 for every interleaved reading.  That is still far above a real image and rests
on a single sample, so it is a lead and not a finding.
