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


### The one thing still missing: where the position array starts

Everything above is exact - the opcode, the stride, the vertex fields, the counts.  A reader
still cannot ship, because **nothing found so far states where the position array begins**, and
the geometric tests are not sharp enough to pin it.

* Triangle locality over 966 plausible offsets takes 2.3 s and puts the minimum at **31,296**
  (0.0318), with the whole band 31,236 to 31,308 inside 0.003 of it.  A one-vertex shift is
  12 bytes, so that band is 50 vertices wide.
* Strip smoothness - the mean dot between adjacent face normals, which settled TotemTech's
  strip-versus-fan question - is **flat at 0.42 to 0.45 across the whole band** and does not
  discriminate.
* There is no declared count: the values 1046, 468, 562 and 3396 appear nowhere in the file as
  a `u32`, and no `u32` anywhere points into the 30,900-31,600 range.
* The texture coordinates are not adjacent to the positions (the block at `P + 1046 * 12` is
  garbage), and searching for 468 `f32` pairs inside a sane UV range matches **5,010 offsets** -
  the file is full of small floats, so that test carries no information here.

**A reader that is fifty vertices out produces a plausible-looking wrong mesh**, which is worse
than producing nothing, so nothing is shipped.  What would settle it: a second character `.gcr`
to test whether the array sits at a fixed distance from the display lists, or the record that
heads each primitive group - the 10-byte entries at 30,113, whose last column runs 40, 112, 184,
208, 276 and is the obvious place for an array pointer, are still unread.


## The RenderWare native reader does not transfer to `gcr` (2026-09-03)

`gcrip/formats/rw_native.py` cracked Piglet's native geometry with two identities - indices
covering exactly `0..N-1`, and a unit-length normal array that anchors the positions.  Both
were tried here and neither carries.

**Containment does not hold per strip run.**  On Piglet a group is a few long strips that
between them use every index; on `gcr` a group is *hundreds of tiny strips*, so chaining breaks
it into runs of a few dozen vertices.  Applying the test per run leaves **7 groups and 415
vertices** out of the 562 strips and 3,396 vertices the file actually has.  Taken globally the
file is close - max index 1,045 over **1,041** distinct - but close is not the identity.

**There is no unit-length normal array.**  Searched over the whole file for 1,046 triples at
`f32`, `s16/32768`, `s16/16384`, `s8/64` and `s8/128`: **none**, at any offset.  Column 1 of the
vertex record equals column 0 on 100% of vertices, so if it is a normal index the array is the
same length as the positions - and no array of that length is unit length in any encoding.

So `gcr` shares the *vertex shape* with RenderWare native geometry - 8-byte vertices of four
big-endian `u16` behind GX strips - and not the array layout.  Whatever anchors its arrays is
something else, and the position search still has nothing to stand on.


## `gcr` characters, read (2026-09-03)

Everything above was looking for the header at the front.  **The header is the last 52
bytes**, and `+4` of the file is its offset (`file length - 52`); `+0` is 12, the offset of
a 16-byte texture-slot table (`u32 gct id, u32[3]`, ended by `0xFFFFFFFF`) whose ids are the
`textures/%04d.gct` members of the same pak.  Found by reading the TS2 `main.dol` (no
symbols): `GXSetArray` is the function that writes `0x08, 0xA0 + attr - 9` to the write-gather
pipe, and its caller at `0x8024a454` - nine calls - is the draw routine.  It takes the header
pointer, reads `u32 records` from it, and walks **0xa0-byte node records that sit just before
the header**:

    +0    u8 kind        0 rigid (its bone is +1), 1 / 2 / 3 skinned pieces
    +1    u8 bone        +2 .. +5 more node bytes, 0xff none
    +0x14 + 4 * lod      -> batch table: 10-byte u16 texture slot, u16 index, u16 first
                            vertex, u16 vertices, u16 flags; ends on flags == 0xFFFF
    +0x24 + 0x14 * lod   u32, ptr positions (f32 x3), ptr uvs (f32 x2; x3 when bit lod of
                            +0x67 is set), ptr colours (RGBA8 or 0), ptr normals (s8 x3, pad)
    +0x60 u16, +0x62 u16, +0x67 u8 uv flags, +0x8c f32 (1.0 / 0.5 / 0.3)
    +0x90 + 4 * lod      -> per batch (u32 display list, u32 bytes); (0, 0) when the batch's
                            triangles live in a neighbour's list

The display lists are the `0x9B` strips the earlier note counted, but the vertex is **9
bytes on the skinned kinds** - `u8 matrix index` then `u16 position, normal, colour, uv` -
and 8 on rigid ones; reading every list as 8 bytes is what made the "1,046 positions" and the
missing normal array.  The normals are `s8 / 64` with a pad byte (stride 4), which is why no
unit-length `f32` or `s16` array was ever found.  The last batch's `first + vertices` is the
position count (263 on `chr128`'s first node, which the display lists index up to 262).

Positions are the bind pose in model space - feet at y = 0, head at 1.86 - so the model
exports T-posed without touching the bones; the 27-bone skeleton (`+4` of the header) and the
per-vertex matrix bytes are read but not applied.  Standard strip parity agrees with the
stored normals on 100% of `chr128`'s 2,716 triangles (mean 0.90).

`gcrip/formats/frd_gcr.py` + `gcrip/plugins/frd_gcr.py`: **all 314 `.gcr` in TS2's
`chr.pak` read, 343,841 triangles**, textured by gct id from the same pak.  Not this
flavour: `bg/level*.gcr` / `ob/tile*.gcr` (two pointers and a float grid at +0) and Future
Perfect / Second Sight's character files (three pointers into a 52-byte block at +0, s16
vertex data) - see OPEN.md.

### The levels are the same records (2026-09-03, later)

`bg/level11/level11.gcr` (852 KB, Chicago) has no trailer: `+0` is 0x20 and the texture slots
start there (`u32 gct id, u32 flags, 0, u32`, 62 of them, ended by 0xFFFFFFFF); `+4` points at
a zeroed runtime area at the end of the file, `+8` at a list of 98 seventy-two-byte portal
quads (`u32 2, u32 1, f32 1.0, 0, 0, u32, f32 corner[4][3]`), `+0xc` at entity placements
(`u32 type, u32 id, u32, f32 position[3], ..., f32 yaw`), and +0x14 / +0x18 are -1.  Between
the slots and the portals the geometry is **sector blocks**: a batch table, f32 positions,
f32 uvs, RGBA8 colours, display lists, the (pointer, size) pairs, then the 0xa0 node record -
exactly the character record, kind 0, no normal array, and its word at +0x9c pointing four
bytes before itself, which is what `frd_gcr.level_nodes` scans for (51 sectors here).  The
display lists are `0x99` strips of **6-byte** vertices - position, colour, uv - since a level
is vertex-lit; the general rule the reader now applies is: a matrix byte on kinds 1-3, a
normal index only when the node has a normal array, a second colour index when bit `0x10 <<
lod` of +0x67 is set.  Level 11 comes out in world space (-37..62 x -0.2..10.7 x -46..29),
10,461 triangles at LOD 0 (LOD 1 is 245), with 45 of its 62 textures bound from the pak.
A story pak is 46,437 triangles in all with its props.

### Future Perfect, Second Sight and the array-block characters (2026-09-03, later still)

Future Perfect's paks name their members by hash (`db3b8403_0000`), so nothing there has a
`.gcr` suffix - the plugin detects on the header shapes alone.  Its props and vehicles are
the TS2 node record grown to **0xc0 bytes**: the four LOD array sub-records move to +0
(`u32, ptr positions, ptr uvs, ptr normals, ptr colours` - normals and colours swap against
TS2), kind at +0x3c, batch tables at +0x54, uv flags at +0x6b, pairs at +0xb0.  The trailer
at `+4` carries flags at +0xc: **0x10 positions are `s16 / 1024`** (GX format 5 / 7, frac
10, from the `GXSetVtxAttrFmt` calls at `0x8017e058`), **0x40 normals are indices into a
4096-entry palette of unit vectors at `0x80412740` in the DOL** (`GXSetArray(GX_VA_NRM,
palette, 12)` in the draw routine at `0x80182934`; Second Sight's DOL holds the identical
table, now `gcrip/data/frd_normals.npz`), **0x10000 every vertex leads with a matrix byte**.
A uv pointer with bit 1 set is `s16 / 1024`.  Batch entries are 8 bytes in one of two
orders - `u16 slot, u16 index, u16 first, u8 count, u8 flags` or `u16 slot, u8 count, u8
flags, u16 index, u16 first` - ended by flags 0xFF; a skinned character's `first` jumps
because its nodes share one position array kept after the trailer.  Texture slots at 12
embed a gct (`ptr, hash, 0, 0x10000000`) or name one by hash (`hash, hash, 0, 0` = the
member `HHHHHHHH_NNNN` of some pak).  A node whose LOD 0 is empty draws its LOD 1.

The characters proper (and TS2's `chrinc.pak`) are the **array-block** shape: a header of
pointers (TS2 `slots, block`; FP `slots, nodes, block`), the block `ptr positions, ptr uvs,
ptr normals, [u32 7], ptr groups, ptr node tree, u32 groups, u32 nodes, ...` with the
positions directly behind the header words (`f32 x3 + flag`, `f32 uv`, `f32 normal + pad`
on TS2; `s16 / 1024`, `s16 / 1024`, `s16 / 16384 + pad` on FP / SS), 20- or 24-byte groups
(`[u32] ptr entries, u32 entries, ptr matrix slots, u32 matrices, u32 first`) of 20-byte
entries (`u32 slot, u32 first, u32 count, ptr list, u32 bytes`) whose strips carry `u8
matrix, u16 position, u16 normal, [u16 colour on TS2], u16 uv`.  Positions are model space
(short strip edges, a standing figure), but the strips do not keep one winding: the signed
agreement with the stored normals is 0 while the unsigned is 0.91, so the reader turns each
triangle to face its own normals.

Results: Future Perfect's three sampled prop paks read every model (29 models, 33,250
triangles - props, a jeep, a boat); Second Sight's `csc/front.pak` and `csc/trollc.pak`
read all 19 `.gcr` (20,712 triangles, 91 textures); TS2's `chrinc` character reads at
4,334 triangles textured.  Not done: skinning (the matrix bytes and node trees are read,
no joints are exported) and the FP / SS levels, which have not been looked at.
