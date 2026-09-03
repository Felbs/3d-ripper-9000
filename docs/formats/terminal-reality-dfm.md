# Terminal Reality `_dfm` header and part table (2026-09-02)

Terminal Reality ``_dfm`` meshes - the header and part table.

Cluster 6.  The geometry itself is still unread; what this settles is the part table, and with
it **the per-part bounding box that the vertex work was missing**.  ``docs/OPEN.md`` recorded
that "both bounding-box tests come back empty" and that every normal-agreement fit was
planar-degenerate.  There is a box per part, sitting in plain sight in the table.

Little-endian::

    +0    u32   version        2 on every sample
    +8    u32   part count
    +12   u32   bone count     equal to the paired `.SKL`'s
    +24   char  skeleton file name, NUL then `BAADF00D` fill
    +104  count x { char name[30]; u32 bone; f32 box[6] }   stride 58

As in the skeletons (:mod:`gcrip.formats.tr_skl`), short names are padded with ``BAADF00D``
rather than zeroes, which is what made these records look variable-length.

Three checks agree across two meshes of very different sizes - 59 parts in ``soldier.dfm`` and
23 in ``mentor.dfm``:

* **every name decodes**, 59 of 59 and 23 of 23 - ``binoculars2``, ``canteen``, ``gasmask``,
  ``Lbladehilt``;
* **every bone index is inside the skeleton**, 59 of 59 and 23 of 23;
* **every box has `min <= max` on all three axes**, 59 of 59 and 23 of 23.  Six floats in a row
  satisfying that on every record is not something a wrong stride produces.

And the mesh names its skeleton twice over: the string at +24 is ``SOLDIER_DEFAULT.SKL``, and
the bone count at +12 is 82, exactly what that file holds (68 and ``MENTOR.SKL`` for the other).

**What is still open** is the geometry, which follows a material table - the first record after
the parts carries ``1.0, 1.0, 32.0`` and the texture name ``SOLDIER.TIF``.  The tail is only
9.9% plausible ``f32``, so the vertices are quantised, which agrees with the 20-byte vertex the
size arithmetic implied.  The boxes here are what a candidate layout should now be tested
against: decode a part's vertices, scale, and they must land inside that part's box.

## The parts name the bones they hang off

Resolving each part's bone index through the paired `.SKL` gives a result that reads like
English, which is the strongest check of the pair together:

| part | bone |
|---|---|
| `binoculars2` | `Bip01 L Hand` |
| `waist` | `Bip01 Spine` |
| `chest-open` | `Bip01 Spine2` |
| `holster` | `Bip01 foldedblade` |
| `pouch1` | `Bip01 SheathR` |

Binoculars in the left hand and a waist on the spine are not what a mis-read table produces.
All 59 and all 23 bone references resolve inside their skeletons.


## What the boxes are *not*, measured

The obvious first use of a per-part box is to look for the vertices that produced it.  That
fails, and the failure is informative: **the box extremes do not appear verbatim in the
geometry**.  Packing each of the six floats and searching the tail finds only **42 of 354** on
`soldier.dfm` and **14 of 138** on `mentor.dfm`, about a tenth - which is the rate you would get
from coincidence on float-dense data, not from a real hit.

So the boxes are not the min and max of stored `f32` vertices.  Combined with the tail being
only 9.9% plausible `f32`, the reading that fits is that **the vertices are quantised and the
box is the dequantisation range** - `position = box_min + (raw / FULL) * (box_max - box_min)` or
some variant - which is the usual reason a format stores a tight box per part at all.

That also explains why the crude form of the oracle does not discriminate.  Scanning the tail
for `f32` triples inside the *union* of all boxes scores 0.40 to 0.43 for **every** stride tried
(12, 16, 20, 24, 28, 32, 36 at every word offset), because on data of this shape four words in
ten land in that range by chance.  The union box is useless; the per-part box is the test, and
using it needs the part-to-vertex mapping first.

The 36-byte records are **not** per-part 3x3 transforms, which was worth ruling out since the
skinning wants bind matrices: read as nine floats from the first plausible offsets the rows are
not unit length (0.42, 0.53, 0.61) and two of them share components.

## Correction: the box oracle I proposed is vacuous (2026-09-02)

This note said twice that the per-part boxes were "the oracle the vertex search lacked".  They
are not, and the reason is structural rather than a matter of tuning.

**If positions are quantised, dequantising them into the box guarantees they land inside it** -
`box_min + raw/FULL * (box_max - box_min)` cannot produce an outside value whatever the stride,
byte order or offset is.  The test can only discriminate for a layout that stores absolute
floats, and `_dfm` does not: measured, the tail holds just **two float runs totalling 571 words,
1.9% of it**.

Running it anyway confirms the emptiness.  Every candidate scores a longest in-box run of
**exactly 93 consecutive vertices, for every one of the 59 parts alike** - because the part boxes
all sit around the body centre and overlap almost completely, so containment says nothing about
*which* part a vertex belongs to either.

**The repair was no better.**  "A tight box means the raw axis must span 0..65535" sounds
non-vacuous, and every stride from 12 to 32 bytes produced a column spanning exactly that - each
one at offset `stride - 1`, straddling record boundaries.  A few thousand samples of arbitrary
bytes span the full range.

The one oracle proven on quantised geometry in this project - PHM's *index values run 0 to
vertices-1 exactly* - finds **nothing** here: zero candidate windows on `soldier.dfm`, and only
two or three unconvincing ones on `mentor.dfm` (max index 214, 132 distinct of 512).

Both dead oracles are now in `gcrip/oracles.py` graded `DISCREDITED` with these reasons, so the
next attempt does not spend its afternoon rediscovering them.  What is still true and useful is
everything the part table gives: names, bone indices that resolve, and boxes that are real even
if they cannot referee a layout.

## The 20-byte stride, confirmed by the data rather than by arithmetic

With both box oracles dead, the way in is to ask the bytes what their period is instead of
proposing a layout and testing it.

**Byte autocorrelation settles the stride.**  Measuring how often a byte equals the byte `s`
later, over the whole geometry region:

| stride | soldier.dfm | mentor.dfm |
|---|---|---|
| **20** | **0.363** | **0.287** |
| 40 | 0.332 | 0.262 |
| 60 | 0.319 | 0.251 |
| *mean over all strides* | *0.103* | *0.102* |

Twenty, with clean harmonics at forty and sixty.  That is the note's "20-byte vertex by size
arithmetic" arrived at independently, and it is not a coincidence of one file.

**And it is genuinely 20, not a multiple of something smaller.**  Windowed, there are large
regions where stride-20 agreement holds at 0.41-0.43 while stride-12 and stride-4 fall to
**0.004** - so the periodicity is 20-byte and nothing shorter.

### Columns are locally constant, which is why global statistics said nothing

Read as ten `u16` columns over the *whole* region, all ten look identical - full range, about
2,000 distinct values each, nothing constant.  That is because the region is not one array.

Inside a single 20-byte-periodic window (90 records at byte 7,778) the structure appears at
once::

    col  0   constant 510 across all 90 records
    col  8   10 .. 245
    col 16   688 .. 826   (49 distinct)
    col 18   308 .. 516   (38 distinct)
    the rest full-range

A column that holds one value across 90 consecutive records is the classic confirmation that a
stride is right - a wrong stride smears it.

And the same signature turns up elsewhere at a different column: at byte 10,778 the ranges
`688..826` and `308..516` sit at columns 4 and 6 rather than 16 and 18.  **So the tail holds
several arrays whose column meanings differ**, which is exactly why whole-region statistics
washed out and why a single global layout was never going to fit.

What is still unknown is which columns are position, and the scale.  The narrow columns do not
look like box-normalised quantisation - values in the hundreds, not spanning `0..65535` - so the
dequantisation is not the simple box mapping this note assumed twice.

### Segmenting the arrays by their constant field

Sliding a 20-byte-strided window and asking, at each phase, how long a run of records shares the
same leading `u16` locates the arrays without assuming where they start.

The dominant marker is **`0x0400` (1024)**, holding constant across runs of up to **229
records** on `soldier.dfm` and 123 on `mentor.dfm`, at several phases.  A second marker,
`0x01FE` (510), holds for 130.

Inside the 229-record run the columns separate clearly::

    col  4    0 ..  253    78 distinct
    col 12    6 .. 1018    59 distinct
    col 14  343 .. 1008    52 distinct
    col 16  256 ..  768   **5 distinct**
    col  0, 2, 6, 8, 10, 18   full range, 83-104 distinct

**Column 16 taking only five values across 229 records** is an enumerated field, not a
coordinate - the values are `0x0100`, `0x0101`, `0x01FE`, `0x0300`, so the high byte is 1 or 3
and the low byte is 0, 1 or 0xFE.  Columns 12 and 14, narrow and finely divided, are the
plausible quantised coordinates.

That is as far as this goes for now.  The stride is settled, the arrays are separable, and the
columns are characterised - but which columns are position and what the scale is remain open,
and the two obvious ways to decide it are the ones already recorded as discredited.  The next
attempt should look for a **declared count** to match an array length against, since a size
identity is the one oracle in this project that has never misled.


## The geometry is a chain of sub-mesh blocks (2026-09-02)

The previous section ended by saying the next attempt should look for a **declared count**,
because a size identity is the one oracle here that has never misled.  There is one, and it is
per sub-mesh rather than per file.

After the part table and the material table the file is a flat run of blocks:

    u32 a, b          two small indices - a part or bone pair
    u32 2             constant
    u32 payload       the vertex bytes, plus four
    u32 4             constant
    u32 vertices
    u32 triangles
    u32 bone count    the number the file header already carries, and the .SKL holds
    u32 0
    u32 0x0A000000    constant
    ... vertices ...  `payload - 4` bytes
    ... triangles ... three u16 an entry

Two identities pin it, and neither can pass by accident:

* **the blocks tile.**  `next block == this block + 36 + payload + 6 * triangles`, on
  **106 of 106** blocks in `soldier.dfm` and **47 of 47** in `mentor.dfm`, with the last one
  ending exactly at the end of the file.
* **every triangle indexes its own block, and the largest index is exactly `vertices - 1`** -
  106 of 106 and 47 of 47.  That is the oracle proven on PHM's quantised geometry, the one this
  note recorded as finding *nothing* here.  It finds nothing when it is asked of the whole file,
  because the file is not one array; asked of a block it is exact every time.

| file | blocks | vertices | triangles | 20-byte blocks |
|---|---|---|---|---|
| `soldier.dfm` | 106 | 4,215 | 3,914 | 75 |
| `mentor.dfm` | 47 | 3,241 | 3,760 | 11 |

`payload == vertices * 20 + 4` on 75 of soldier's blocks - **the 20-byte stride the byte
autocorrelation found, now stated by the file itself** - and the wider blocks are what a
variable-length skinning list looks like.

### What the vertex record still is not

Inside a 20-byte record byte 3 is always `0x04`, byte 4 always `0x00` (the note's `0x0400`
marker), byte 15 always `0x44` and bytes 16-17 always `0x01FE` - the 510 marker.  Read as
little-endian `s16` the narrow columns are 1, 2 and 3; read big-endian they are 4, 8 and 9.

**Neither triple is the position.**  Scored by how short a triangle's perimeter is against its
own block's diagonal - a real surface scores near 0.1, and the indices needed for the test are
now known to be right - the best of all 240 column triples across 29 blocks reaches only 0.44,
with the field flat behind it.  Eleven of the twenty bytes carry about forty distinct values
over 130 vertices, which is not what whole `s16` coordinate columns look like.  The reading that
fits is **packed bit fields**, and that is where the next attempt should start.


## The vertex record: the normal is found, the position is not (2026-09-03)

The lesson from Piglet applied here: search for the **normal**, which has an identity, rather
than for the position, which does not.  Over the 20-byte rigid record, every `(offset,
encoding)` was tried for a triple of unit length across the block:

| bytes | encoding | result |
|---|---|---|
| **8-13** | **little-endian `s16` / 32767** | **unit length on 12 of 12 blocks**, worst `|n| - 1` = 6.8e-03 |
| 9-14 | big-endian `s16` / 32767 | the same bytes read one byte over - an alias, not a second hit |

So the record's frame is fixed: bytes 8-13 are the vertex normal.  Around it:

    +0   01 fe          constant
    +2   s16 LE         44 distinct, -705 .. 427
    +4   s16 LE         41 distinct, -255 .. 427
    +6   u8             38 distinct, 25 .. 163
    +7   04             constant
    +8   normal         s16 x3 / 32767
    +14  u8             42 distinct
    +15  44             constant
    +16  02 | 03
    +17  u8             51 distinct
    +18  01 | 02
    +19  u8             38 distinct

**The position is not settled.**  Reading bytes 2-7 as three `s16` and scoring face normals
against the stored vertex normals gives **0.68-0.73** against a shuffled-normal baseline of
0.51: a real signal, but not a decoded mesh, which scores above 0.9.  Sweeping per-axis scales
to maximise that agreement gives *different* optima on different blocks (6.3/5.0 on one,
0.25/0.13 on the next), which says the reading is incomplete rather than merely unscaled.

Two things are now known that were not:

* the ranges do not match the part's bounding box because **the vertices are in bone space**
  - part 0 (`binoculars2`) hangs off `Bip01 L Hand`, and its box is in model space.  That is
  why box containment could never work here, independent of the vacuousness recorded above;
* the index data is a plain triangle list, not strips: adjacent triangles share 2.13 indices,
  which is what a list of a connected mesh does, and reading it as a strip scores no better.

What is left is bytes 2-7 and 14-19 - twelve bytes for a position and, presumably, a texture
coordinate - with a working oracle (the normal agreement) to test any reading against.
