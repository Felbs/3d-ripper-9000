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
