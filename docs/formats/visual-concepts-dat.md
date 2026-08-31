# Visual Concepts `DAT` - NBA 2K2/2K3, NFL 2K3, NCAA Basketball/Football 2K3

**Five discs, 5.5 GB, and each one is a single file.** These discs have nine files apiece:
`sys/boot.bin`, `sys/bi2.bin`, `sys/fst.bin`, the executable, and one `files/game.dat` holding
the entire game - 827 MB on NBA 2K3, 1,346 MB on NFL 2K3.  All five report zero models and
zero textures because nothing opens that file.

Found by a magic census over the `.dat` and `.bin` files of every disc still producing nothing:
it is by some distance the largest single cluster left.

## What is mapped

Big-endian.

    +0   char magic[4]   "DAT\1" (NBA 2K3, NFL 2K3) or "DAT\0" (NBA 2K2, NCAA Football 2K3)
    +4   u32 entry count            66,995 on NBA 2K3, 69,366 on NFL 2K3
    +8   u32 16
    +12  u32 entry count + 29
    +28  u32 25
    +32  the entry table, 24 bytes an entry

An entry is six big-endian `u32`::

    +0   uncompressed size          1,968 then 32,928, 33,344, 30,816, 32,640 ...
    +4   a counter that falls by 15 an entry   47,245, 47,223, 47,208, 47,193 ...
    +8   name hash                  no names are stored anywhere
    +12  0x01000000 when compressed, 0 on the first entry
    +16  0
    +20  offset, cumulative         0, 13,328, 26,464, 38,688, 52,224 ...

The offset column is the useful one: its differences are the **stored** sizes - 13,328, 13,136,
12,224, 13,536 - against uncompressed sizes around 32,000, so the members are packed at roughly
2.5:1.

## What is blocking it

**The codec.**  The payload is high-entropy from the first byte and none of the decoders gcrip
already has touches it - zlib in all three window modes, gzip, `refpack`, `prs`, `yaz0`,
`yay0`, `lzo`, `avlz` and `lzr` all fail on the first three members from either candidate data
base.  It is a private LZ, in the same position as [`.hog`](backlog-map.md) and High Voltage's
`GMS`.

The data base itself is not confirmed either: `32 + count * 24` and `32 + (count + 29) * 24`
are both plausible and both give high-entropy members, which is exactly what a compressed
archive looks like whichever base is right, so the base cannot be settled until something
decompresses.

## Worth knowing before starting

* There are **no names** - only hashes - so even with the codec, members come out numbered.
  Sorting them by content (a `TPL`-alike magic, a mesh header) will matter more than usual.
* 66,995 entries in one file means a decoder has to be fast; a per-member Python loop over
  827 MB is not going to be usable in the rip pass.
* The first entry has the compression flag clear, so it is the natural test case for the codec:
  1,968 bytes that should be readable as they are, once the data base is known.
