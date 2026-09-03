# Free Radical `P4CK` / `P5CK` / `P8CK` - TimeSplitters 2, Future Perfect, Second Sight

Three discs, **637 archives, 2.7 GB**, and all three reported zero models and zero textures.
Everything on them is inside these archives.

`gcrip/formats/frd_pak.py` + `gcrip/plugins/frd_pak.py`.  Little-endian throughout.

## Two header meanings, told apart by arithmetic

    +0   char magic[4]   "P4CK", "P5CK" or "P8CK"
    +4   u32 a
    +8   u32 b
    +12  u32 c

**Sized**, when `a + b + c == len(file)`: `a` bytes of data (this header included), then `b`
bytes of table, then `c` bytes of names.

**Counted**, when `a + b * 12 == len(file)`: `a` is the table *offset*, `b` an entry *count*
and `c` the name-block offset, and each entry is `u32 name offset (from the name block), u32
size, u32 data offset` - size and offset in the opposite order to the other layout.

The magic does not say which; `P8CK` files appear in both.  Both tests are exact and neither
holds on the other's files, so nothing has to be guessed.

## Three entry shapes in the sized layout

    named    16 bytes:  u32 name offset, u32 data offset, u32 size, u32 stored
    hashed   16 bytes:  u32 name hash,   u32 data offset, u32 size, u32 stored
    inline   60 bytes:  char name[48],   u32 data offset, u32 size, u32 stored

Again nothing declares the shape, so the reader tries all three and keeps the one that
reconciles: the table size has to divide by the stride, every member has to fit inside the data
region, and the members have to tile it.  On `igcs_06.pak` the 16-byte hashed reading runs from
byte 32 to 794,304 - the data size exactly - which is what picks it over a 60-byte reading that
also divides.

## The three things that cost time

**A name offset is measured from the start of the table, not the name block.**  On `lv60.pak`
the five offsets are 80, 111, 146, 170 and 196 against a table of 80 bytes; subtracting the
table size lands each one exactly on a string.  Read as name-block offsets they are all 80
bytes late, which produces plausible garbage rather than an error.

**The fourth word is the stored length and the third is the length after unpacking.**  Where it
is zero the member is stored as-is and the two agree - which is most files, so the mistake
survives.  Where it is not, reading the third word as the stored length walks the archive off
the end of its data region, and the symptom is a fifth of Future Perfect's archives failing a
range check for no visible reason.

**An empty member is not a wrong reading.**  The cutscene archives are full of zero-size
entries; disqualifying a shape because one member is empty throws away the whole archive.

## Compression, and the names hidden in it

Members whose stored length differs are **gzip**, and the gzip header carries `FNAME` - the
real file name, `prop_all_gcas.war`, `str_ts_pgs.bs`.  That is the only place the hashed
archives keep a name at all, so unpacking is what gives them back.

## Result

Sampling 50 archives a disc across the size range:

| disc | archives sampled | parsed | members | bytes out |
|---|---|---|---|---|
| TimeSplitters 2 | 49 of 69 | 49 | 18,378 | 275 MB from 276 MB in |
| TimeSplitters: Future Perfect | 50 of 339 | 50 | 4,106 | 81 MB from 62 MB in |
| Second Sight | 50 of 229 | 50 | 2,055 | 54 MB from 54 MB in |

**24,539 members**, and Future Perfect's output exceeds its input because most of it is packed.
The members are `gct` (12,974 in the sample), `gcr` (2,467), `war` animation, `dsp` audio and
`bs` scripts.

## `gct` textures - partly cracked

`gcrip/formats/frd_gct.py` + `gcrip/plugins/frd_gct.py`.  Big-endian, 32 bytes:

    +0   u32 width
    +4   u32 height
    +8   u32 width again
    +12  u32 height again
    +16  u16 mip levels | u16 format
    +20  12 bytes

The doubled width and height are the check that the header is being read at all, and **the mip
count is the high half of the word at +16** - read as one `u32` a three-level format 5 comes out
as "format 196,613", which is what one file in the sample looked like.

The format code is Free Radical's own and does not map one-to-one onto GX:

| code | what it is |
|---|---|
| 2, 3, 4, 10, 13 | `CMPR` |
| 5, 7 | `I8` |
| 6, 8 | `RGB5A3` |
| 0 | `RGBA8` |
| 9, 11, 12 | not identified - under 3% of the sample |

**6,409 of 6,465 textures in the sample decode: 100% on TimeSplitters 2, 98% on Future
Perfect, 99% on Second Sight.**

### How the codes were settled, and the wrong turn on the way

The obvious move is to divide the file length by the pixel count and read the answer as bits
per pixel.  It does not work, because **a file usually holds more than the top level**.  Codes
4 and 10 carry exactly twice the `CMPR` data their size needs, which reads as "8 bits a pixel"
and points at `I8`, `IA4`, or a palette that is not in the file - and `I8` duly draws a
GameCube controller as vertical banding, which looks exactly like an index stream shown as
intensity.  That is a convincing dead end; it cost a round of hunting for palettes that do not
exist.  Taking the first `encoded_size(fmt, w, h)` bytes draws the controller.

Where the mip count is set the whole chain is stored, and *then* the ratio identifies the
format, because a full chain is four thirds of the top level:

| bytes / pixels | top level | format |
|---|---|---|
| 0.67 | 0.5 | `CMPR` |
| 1.33 | 1.0 | `I8` |
| 5.33 | 4.0 | `RGBA8` |

Each was then confirmed by looking: a sky gradient for `RGBA8`, a marble panel and a lens
flare for `I8`, shotgun shells and a GameCube controller for `CMPR`, a mouse pointer and a
rain streak for `RGB5A3`.

## Where the models actually are

`gcr` is used for two unrelated things, which is worth knowing before sampling:

* the `anim_*` and `cs_*` archives hold **animation** - their `.war` members are `ANR1` /
  `ANRS` and their `.gcr` are streams of `f32` rotations (`anim__data__cs__l_cry__F_marine.gcr`
  is 387,904 bytes of them).  Sampling the smallest archives finds only these;
* **`data/chr.pak` (23.5 MB) is the characters**: 1,295 members, **314 `.gcr` and 981 `.gct`**,
  named `ob__chrs__chr128.gcr` and so on.  That is where the geometry is.

## What a character `gcr` looks like

`ob__chrs__chr128.gcr`, 135,964 bytes:

    +0    u32 12
    +4    u32 135,912       the file length less 52
    +8    u32 0
    +12   a table of 16-byte records - twelve zero bytes then a u32 that counts 775, 776, 777
    +176  u16 pairs: 0004 0002, 0004 0001, 0004 0046, 0002 0004, 0002 004c, 0006 0002 ...

**`gxscan` finds one mesh of 36 triangles in it**, which is noise.  The earlier note recorded
"not GX display lists" from a prop; it holds for the characters too, so that avenue is closed
for the whole format rather than for one file type.

A run of 138 `s16` at byte 30,018 reads as regular multiples of 256 - `0 0 0 0`, `0 256 256 0`,
`256 512 512 0`, `512 768 768 0` - which is 1/256 fixed point, so at least one array in here is
quantised coordinates or texture coordinates rather than floats.

## Still open

`gcr` geometry.  Both it and the palette-indexed `gct` are reachable by the rest of the
pipeline under their real names, which is what the container was in the way of; the three
discs export 5,239, 4,526 and 2,809 scenes today but only 38,653, 141 and 2,890 triangles
between them, because almost all of that is textures.


## `gcr` reconnaissance, 2026-09-02

Not solved; recorded so the next attempt starts further along.

The header is **big-endian**, and the note's "s16 triples that read as coordinates" were being
read the wrong way round.

    +0    u32 12
    +4    u32 file length less 52
    +8    u32 0
    +12   a table of 16-byte records - twelve zero bytes then a u32
    +156  u32 0xFFFFFFFF, ending the table

On `ob__chrs__chr128.gcr` that table holds **nine consecutive values, 775 to 783**.  `chr.pak`
carries 981 `.gct`, so these are texture ids, not offsets - a material table naming its images
by index into the archive.

Deeper in, at byte 30,032, are **8-byte vertex records of four little-endian `u16`**:

    (0, 0, 1, 1), (0, 1, 2, 2), (0, 2, 3, 3), (0, 3, 4, 4), (0, 4, 5, 5),
    (0, 1, 6, 6), (0, 2, 7, 7), (0, 5, 8, 8), (0, 0, 9, 9), (0, 1, 0, 0)

The third column increments, so it is a position index and the array is ten vertices long; the
second ranges over six values and is a texture-coordinate index.  **The note's reading of this
region as "s16 multiples of 256 - 0 256 256 0, 256 512 512 0" was the same bytes big-endian**;
little-endian they are small indices, which is what they are.

So a `gcr` is a scene bundle of many small indexed primitives, each with its own vertex table
addressing shared position, normal and texture-coordinate arrays - not one mesh with one index
buffer, which is why whole-file statistics and `gxscan` both find nothing.  What is still needed
is the record that heads each primitive and names the arrays it indexes.


## `gcr` **is** GX display lists - and why the scanner cannot see them (2026-09-02)

The note above says "**Not GX display lists** - `gxscan` finds nothing in any of them".  That is
wrong twice over: they are GX display lists, and the scanner's silence is a defect in the
scanner, not evidence about the format.

`ob__chrs__chr128.gcr` holds **562 primitives, opcode `0x9B`** - `GX_DRAW_TRIANGLE_STRIP` with
vertex format 3 - and 3,396 vertices, chained with zero padding between them, 21% of the file.
A vertex is **8 bytes, four big-endian `u16`**:

| column | meaning | range |
|---|---|---|
| 0 | position index | 0 .. 1045 |
| 1 | normal index - **equal to column 0 on 100% of vertices** | 0 .. 1045 |
| 2 | always 0 | - |
| 3 | texture-coordinate index | 0 .. 467 |

So the file holds **1,046 positions and 468 texture coordinates**, and the positions are
**big-endian `f32` triples**: read at offset ~31,240 the strips score **0.036** on triangle
locality (perimeter against the mesh's own diagonal), where a real surface is under 0.05 and the
rest of the field is flat, and the values are ordinary coordinates - `(0.058, 1.658, 0.069)`.

### The scanner defect

`gxscan._Blob` marks offset 29,922 as a header correctly - it masks the opcode with `0xF8`, so
`0x9B` reads as `0x98` - and `_chain` walks three primitives from there at stride 8.
`candidate_lists` never asks, because the walk is **greedy**: an accepted chain sets
`skip_to` to its end and every start inside is skipped.  A spurious chain at offset **254**,
stride 25, 1,397 vertices, covers 35 KB and buries the lot.  The file yields **5 candidate
starts** where disabling the skip yields **1,453**, and the real chain is only in the second set.

Measured, with the skip disabled and the rejected chains re-walked: the same file gives
**43 meshes and 4,063 triangles** where it gives 0 today.

**Not shipped, deliberately.**  Enumeration is cheap (0.08 s here, 0.66 s on a 388 KB file) but
scoring those candidates costs **30 to 46 seconds on 136 KB**, and `plugins/gx.py` spends a
whole-disc budget across every file it scans.  A salvage pass that only runs when the first pass
came back empty is the right shape - it cannot make a successful scan slower - but which
candidates to score, and how many, needs a benchmark over the library rather than one file.
Capping it at 32 or 128 groups in offset order drops the yield back to one mesh, because the
real lists sit behind the spurious span, so the cap has to be smarter than a prefix.
