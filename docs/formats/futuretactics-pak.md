# FutureTactics: The Uprising - `files.pak`

The whole game is one 143 MB `files.pak`, and the disc produced nothing because the archive has
**no magic at all** - it opens with a count and goes straight into names.

## Layout

Little-endian.

    +0   u32 entry count            5,458
    +4   the table, 56 bytes an entry:
             char name[48]          "FRONTEND\ALIENGICON(1).PNG", backslash separated
             u32 offset
             u32 size
    ...  the members, from the end of the table

## Recognising it without a magic

The table's own arithmetic does it, and it fits inside the 64 bytes a plugin's `is_container`
is given: **the first entry's offset is the end of the table**, so

    u32 at 52 == 4 + count * 56

has to hold - 305,652 on this archive, exactly.  That is a stronger claim than any name test,
and it costs nothing.  It is worth preferring this kind of check over "the file is called
`files.pak`" whenever the header offers one.

## Bit 31 of the size means the member is compressed

3,055 of the 5,458 entries have it set.  Read as a plain size those members land two gigabytes
past the end of a 143 MB file, which looks like a **broken table** rather than a flag - a first
pass duly threw them out as "out of range" and kept 2,403 of 5,458, losing 56% of the archive
without anything looking wrong.  What gave it away is that the bad sizes were all just over
`0x80000000`, by amounts that were themselves plausible file sizes.

Masked to its low 31 bits, every one of the 5,458 entries lands inside the file, the members
tile with gaps of nought to three bytes, and none overlaps.

## What is inside, and what actually reads

**5,451 members, 150.6 of 150.9 MB.**  The flag decides what happens to each: an unflagged
member is stored as it is, a flagged one is compressed and comes out packed.

| kind | count | claimed by, walked through the real chain |
|---|---|---|
| `.DFF` | 1,207 | **nothing** - all sampled are compressed |
| `.DDS` | 1,052 | `dds_pack`, 12 of 12 sampled -> textures |
| `.AN2` | 818 | nothing |
| `.ANM` | 797 | nothing |
| `.BMP` | 708 | `bmp`, 12 of 12 -> textures |
| `.PNG` | 637 | `png`, 12 of 12 -> textures |
| `.DAT` / `.CUT` / `.XML` / `.FNT` | ~180 | nothing |

### A claim this note made and had to withdraw

The first version of this note said the archive holds "1,207 RenderWare `.DFF` models" and that
four of the seven kinds already had readers.  Walking the chain instead of assuming showed the
`.DFF` are claimed by **nothing** - and inspecting one explained why: its header read
`type 0x0655, size 4322, version 0x0005fc00`, which is not a RenderWare chunk at all.

That was compressed data.  **Every one of the 223 `.DFF` sampled has bit 31 set**, so the bytes
being read as a chunk header were the packed body plus its 8-byte preamble.  Whether they are
RenderWare underneath is unknown and stays unknown until the codec falls; the extension is the
only evidence, and an extension is not a format.

The lesson is narrow and was already on the cross-cutting list in a different form: a plausible
header read out of a member you have not confirmed is uncompressed tells you nothing.
