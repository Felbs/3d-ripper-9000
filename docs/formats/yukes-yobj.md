# Yuke's `YOBJ` meshes - the `.ymg` files of the WWE discs

WrestleMania X8 carries 732 of them (31 MB) and WrestleMania XIX 1,464 (28 MB); the two Day of
Reckoning discs have 1,099 and 207, though nearly all of theirs are `DUMY` wrappers rather
than `YOBJ` (see the note).  All four discs produced no models at all.

Big-endian:

    +0    char magic[4]   "YOBJ"
    +12   u32 table offset
    +16   u32

The table holds one record per mesh, but **the record length is not constant** - it drifts by
four bytes between records because the trailing float block varies - so records are found by
the constant word `0x0a000000` that every one contains rather than by a stride.  Relative to
that marker at `m`::

    m-8   u16 vertex count
    m+4   u32 -> positions
    m+8   u32 -> normals
    m+16  u32 -> the index block

**Every offset in this format points eight bytes before its data.**  That is the whole trick:
read the arrays at the offset itself and the first normal comes out with a length of 7.05
instead of 1, while the other eleven are exactly 1 - which reads like an off-by-one in the
count rather than a block header.  At `offset + 8` all of them are unit vectors.

Positions and normals are `count` triples of big-endian `f32`, and `normals - positions ==
count * 12` has to hold.  The index block is a run of `u32 count` followed by that many
`u16` triangle-strip indices, packed with no padding, starting at `C + 16` - the extra
eight bytes past the usual `+8` being a small header the strips follow.

## How well it checks out

The positions and normals are confirmed on both variants and are not in doubt: **981 of 981
records** in X8's `dummy_x8.ymg` and **10,445 of 10,445** normals in XIX's `0_2.ymg` come
out unit length at `+8`, which no wrong layout does.

On X8 the index lists read too - 8,104 meshes, 125,428 vertices and 47,090 triangles from ten
files, with an unsigned normal agreement of **0.983 and 98% of meshes above 0.9**.  Winding is
inconsistent as it is in Terminal Reality's `_smf` and A2M's `.gc`, so triangles are flipped
to agree with their own stored normals and the figure quoted is the unsigned one taken before
the flip.

**XIX's index block is laid out differently** and is not read here: it opens with a table of
eight-byte entries (`u16`, `u16`, `u32` pointer) rather than going straight into strips.
A reader for that was tried and produced 97 triangles at 0.451 agreement while also cutting
X8 from 8,104 meshes to 5,480, so it is left out and the files are declined instead of being
turned into rubbish.

## Results

| disc | sampled | meshes | vertices | triangles | unsigned agreement |
|---|---|---|---|---|---|
| WrestleMania X8 | 10 of 732 | 8,104 | 125,428 | 47,090 | 0.983 (98% > 0.9) |
| WrestleMania XIX | 10 of 1,464 | declined | - | - | - |
| WWE Day of Reckoning | 10 of 1,099 | declined | - | - | - |

Ten files of 732 on X8, so the disc total will be far larger.

## Still open

* **XIX's index block**, described above - the geometry arrays read perfectly there, only
  the primitive lists do not.
* **`DUMY`**, which is what nearly every `.ymg` on the two Day of Reckoning discs is
  (147 of 150 sampled, and all 166 `.pms` and 150 sampled `.ypc`).  It is presumably a
  wrapper around a `YOBJ`; those discs also carry `.mpc` files with no readable magic.
