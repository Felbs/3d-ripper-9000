# Crystal Dynamics `bigfile.dat` - Tomb Raider: Legend

The whole game in one file, **1,353,598,976 bytes** beside only `bi2.bin` and `fst.bin`, and
the biggest single unclaimed file in the library.  `gcrip/formats/cd_bigfile.py` +
`gcrip/plugins/cd_bigfile.py`.  Big-endian:

    +0              u32 count                     4,314
    +4              u32 hash[count]               sorted, for binary search
    +4 + count*4    record[count], 16 bytes:
                        u32 unpacked size
                        u32 offset, in 2048-byte sectors
                        u32 0xffffffff
                        u32

There are **no names anywhere** - only hashes - so members come out named by their hash.

## Three pieces of arithmetic identify it, and none needs a name

* The hash array is **strictly ascending across all 4,314 entries**, spanning 767,790 to
  4,292,209,041.  That is what a sorted 32-bit hash table looks like and what nothing else in
  a header does; it is also enough to detect the format inside the 64 bytes `classify` sniffs,
  because the count and the first twelve hashes fit there.
* **Every record's third word is `0xffffffff`** - all 4,314 of them, exactly 16 bytes apart.
  That is what fixes the stride, and it is why the record array reads as noise until you find
  it: the sentinel sits in the middle of the record, not at its start.
* **The offset field is the only one that fits.**  Times 2048 its maximum is 1,353,596,928
  against a file of 1,353,598,976 - the last member ends on the archive's final sector.  Read
  as plain bytes, or with either of the other two fields standing in as the offset, nothing
  reaches even halfway.

## The check that confirms the whole reading

A member is a zlib stream when it starts `78 9c` and stored otherwise, and **the record's
unpacked size has to match what comes out**.  It does: of the first 120 records, 42 carry zlib
and all 42 inflate to exactly the declared size.  Over a wider sample of **617 members, all 617
read exactly and none was refused** - 227 MB of payload.

A member that comes out the wrong size returns `None` rather than being passed on short.

## What is inside - surveyed, and not GX

Sampling 91 members across the archive gives three families:

* **`00 00 7c xx` / `00 00 7d xx`** - 48 of the 91, the bulk.  A `u32` that always sits near
  32,000 (`0x7d0a`, `0x7ce4`, `0x7d00`), then `0xffffffff`, then a size-like word, a small
  count, and **`f32` fields** - 16.0 and 1.0 on one, 29.0 and 1.0 on another, 1380.0 and 1.0 on
  a third.  Floats and a count make this the geometry candidate.
* **`00 00 00 0e`** - 26 of the 91.  Opens `14, 119, 14660, 0, 21504, 0` and then runs
  sub-records separated by `0xffffffff`, so it is itself a container.
* **`!WAR`** (3) and a `00 00 6d xx` family (several small ones).

**The geometry is not GX display lists.**  `gxscan` over those 91 members finds 3 meshes and
206 triangles in total, all of them in the `00 00 00 0e` family - nothing at all in the
`7c/7d` bulk.  So Tomb Raider: Legend needs its own mesh reader, and the `7c/7d` family with
its float fields is where to start.

The archive itself is open, which is the part that was blocking: 1.29 GB and 4,314 members are
now reachable where before none of it was.
