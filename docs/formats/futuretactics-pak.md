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

## Bit 31 of the size is a flag

3,055 of the 5,458 entries have it set.  Read as a plain size those members land two gigabytes
past the end of a 143 MB file, which looks like a **broken table** rather than a flag - a first
pass duly threw them out as "out of range" and kept 2,403 of 5,458, losing 56% of the archive
without anything looking wrong.  What gave it away is that the bad sizes were all just over
`0x80000000`, by amounts that were themselves plausible file sizes.

Masked to its low 31 bits, every one of the 5,458 entries lands inside the file, the members
tile with gaps of nought to three bytes, and none overlaps.

## What is inside

| kind | count | gcrip reads it |
|---|---|---|
| `.DFF` | 1,207 | RenderWare models |
| `.DDS` | 1,052 | yes |
| `.AN2` | 818 | no |
| `.ANM` | 797 | no |
| `.BMP` | 708 | yes |
| `.PNG` | 637 | yes, since this session |
| `.DAT` / `.CUT` | 159 | no |

**5,451 members, 150.6 of 150.9 MB**, and four of the seven kinds already have readers - the
`.DFF` are RenderWare geometry, which is what makes this disc worth opening rather than just
another texture haul.
