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
  (147 of 150 sampled, and all 166 `.pms` and 150 sampled `.ypc`).  It is **not** a thin
  wrapper around a `YOBJ`, which is the first thing to try and the first thing to rule out.

  `3s01A.pms` (2,688,516 bytes) opens `DUMY`, `u32 16`, sixteen zero bytes, then a **`POF0`**
  chunk at +24 with a `u32` size of 2,688,064.  `POF0` is a pointer-relocation table, and the
  two chunks account for the file exactly: `24 + 8 + 2,688,064 = 2,688,096`, then a second
  `POF0` of 412 bytes runs to the final byte.  Inside the first payload are five more `DUMY`
  chunks (10,252, 60,208, 186,932, 252,772, 330,372), so it nests.

  There is **exactly one `YOBJ`** in the file, at 2,678,040, and it is a 10 KB tail that the
  reader here declines - so the geometry on those discs is not simply `YOBJ` behind a wrapper.
  The relocation tables suggest the offsets inside are meant to be fixed up at load, which
  would explain why a `YOBJ` lifted out on its own does not resolve.  That is where to start.


## XIX's index block, read (2026-09-03)

The block that "opens with a table of eight-byte entries" is a **group table**: an entry a
group, `u8, u8, u16 strips, u32 ptr`, the pointer landing 8 bytes before the group's strips;
a single-group record is one entry pointing at itself.  Each strip is `u32 corners` followed
by that many **10-byte corners**: `u16 vertex index, RGBA8 colour, s16 u, s16 v` (/ 32768).
The earlier attempt produced 97 triangles at 0.451 because it read the entry's count as
corners and the pointer as the data start; read as strips from `ptr + 8`, `0_2.ymg` gives
every one of its 6 records - 6,545 triangles at **0.989** unsigned agreement, with uvs and
vertex colours the X8 variant never had (its strips are bare indices).  The group's leading
bytes (0, 1, 2, ... 16, 26, 65, 68) are material indices into a table not yet tied to the
`.tex` files, so the meshes come out with uvs but no texture bound.
