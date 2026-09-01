# Where Tiger Woods 2003/2004/2005 keep their content - and where they do not

`docs/OPEN.md` carried this question: Tiger Woods PGA Tour 06 yields `OBG` terrain and `TXG`
textures, and *"the other three discs carry neither in their first twelve archives - their kinds
are `Cact`, `RPNS`, `RLst`, `CAMC`, `tLOD` - so their content is laid out differently and
finding it is the open question."*

**Answer: the `.hog` on those three discs are audio and configuration. The geometry and textures
were never in them.**  This closes the question negatively, which is worth as much as a crack -
it stops the next session re-reading 1.5 GB of archives looking for meshes that are not there.

## The archives parse fine - that was never the problem

`gcrip/formats/shoc.py` reads them correctly.  On 2005's largest, `Data/_SHER/HOLE_12/hole.hog`
(5,873,664 bytes):

    1,435 chunks, covering 5,873,568 of 5,873,664 bytes - 99.998%
    inner tag of each SHOC wrapper:  Rdat x731 (4.61 MB) | SHDR x270 | SDAT x181 (0.51 MB)

So the walk lands on essentially every byte.  The content simply is not model data.

## What the members are

Sampling the eight largest `.hog`/`.gcb` on each disc:

    2005   Cact x723  tACT | RPNS x6 | CAMC x6 | tLOD x1
    2003   Cact x357  tACT | RPNS x8 | RLst x8 | CAMC x4
    2004   Cact x366  tACT | RPNS x8 | RLst x8 | CAMC x6

`Cact` members are 100 bytes each and open with the literal tag `tACT` - camera or actor
configuration.  723 of them come to **0.05 MB**.  In sequence a `hole.hog` reads:

    CTRL 24 | SHDR RPNS | SDAT 44 | SHDR RLst | SDAT 8168 | SDAT 556
    then a long run of SONO chunks, 8192 bytes each   <- audio
    then SHDR 'sfx ' / Rdat pairs, 731 of them        <- audio
    then SHDR 'Cact' / SDAT 140 pairs to the end      <- config

A golf hole's archive is a sound bank with a camera list stapled to it.

## The 4.61 MB of `Rdat` is sound, and it is compressed by something else

Every `Rdat` follows an `SHDR` of kind `'sfx '`, and every one of them fails reconciliation:
the header wants 812 or 452 bytes and the payload is 340 or 264.  The payload is *smaller* than
the declared unpacked size, so it is compressed - but it does not start with a zlib CMF byte, so
`members()` drops it rather than guessing.  **That is the reader behaving correctly**: it
declines what it cannot confirm instead of emitting 731 wrong members.

Every `Rdat` and every `Cact` payload begins with the identical twelve bytes
`c4 fc 12 00 4e 12 40 00 c4 fc 12 00`, which read as little-endian pointers
(`0x0012fcc4`, `0x0040124e`) - a relocation header, consistent with the 40-byte `RAW_PREFIX`
already in the reader.  Cracking it would yield **audio**, so it is not worth doing for a model
ripper.

## Where the textures actually are: `.fxg`

2005 carries 41 `.fxg` totalling **116.0 MB** in `Data/Char/CharStrm/CharTex/`, named
`24alltex.fxg`, `25alltex.fxg` and so on - "all tex".  They are **raw tiled pixel data with no
header at all**: `24alltex.fxg` opens with runs of eight identical bytes drawn from a narrow
range (`0x10`, `0x12`, `0x13`, `0x15`, `0x18`, `0x1c`), which is the shape of intensity or
palette-indexed pixels laid out in GX tiles, not a table of format codes.

The first read of that header looked like a run of EA `SHPG` format codes - the codes cracked
for FIFA 2004 are `0x16`, `0x19`, `0x1e`, the same neighbourhood.  It is not: the values repeat
in runs of eight and continue for the whole file, which is a picture, not an index.

**What blocks it:** no dimensions and no count.  The 27 files in `CharTex` are all `.fxg`, so
the index is not a sibling - it is in one of the 169 `.gcb` or in the `.dol`.  Find that and
116 MB of character textures fall out at once.

`2003` has the same shape in 35 `.skg` (21.7 MB, `30char.skg`) which open
`12 01 37 ff f8 ff 47 01` - plausibly quantised s16 coordinates, i.e. the character geometry.

## Method note: a bad read invented a format bug

The first census of `hole.hog` reported **zero chunks over the whole 5.8 MB file**, which reads
exactly like a walker that bails at byte 0 on an unknown `CTRL` tag - a plausible, specific,
completely wrong diagnosis.  A double read of the same extent came back identical to itself and
parsed 1,435 chunks.  The first read was simply wrong data from the library drive.

This is the `drive-d-misreads` failure showing up as a **fake format finding** rather than as an
obvious error, and it is the second time it has cost a wrong conclusion.  Double-read before
believing any negative result from `D:`.
