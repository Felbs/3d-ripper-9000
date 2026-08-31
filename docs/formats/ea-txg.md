# EA `TXG` texture groups - Tiger Woods PGA Tour

The `txf` members of the `SHOC` archives ([ea-shoc-hog.md](ea-shoc-hog.md)), 39.8 MB across
the four discs.  `gcrip/formats/ea_txg.py` + `gcrip/plugins/ea_txg.py`.

    TXG   char magic[4] "TXG " | u8 version[4]
    HEAD  8 bytes
    TXHE  the texture headers, 88 bytes each
    CLHE  colour-table headers   (empty on every group found)
    TXDA  the pixels
    CLDA  colour-table data      (empty on every group found)

**The size field excludes the eight-byte header - the opposite of the `SHOC` archive holding
it**, where it includes it.  Read it the SHOC way and the walk stops on the first chunk; read
it this way and it lands exactly on the member's last byte.  Two conventions one layer apart
in the same file is the kind of thing only arithmetic catches.

`CLHE` and `CLDA` are empty everywhere, so nothing here is palette-indexed - which matches the
formats that turn up: `CMPR`, `RGB5A3`, `I8` and `I4`, none of which needs a table.

A header is 88 bytes:

    +0   char name[16]   NUL padded - "tbmulch", "tbcp1", "tbfw1" (turf, cart path, fairway)
    +16  four mip entries of 12 bytes: u32 offset into TXDA, u16, u16 0xffff, u32 1
    +64  u16 width | u16 height
    +72  u8 GX format

Confirmed by arithmetic, not by the pictures looking right: **the gap from mip 0 to mip 1
equals `encoded_size(format, width, height)` on 128 of a group's 146 textures**, and the
texture count times 88 is exactly the `TXHE` chunk's length.  The other 18 carry a single
level, so their second entry is not another offset and the gap means nothing.

**2,073 textures decode, 100% of those found** - `CMPR` 2,235, `RGB5A3` 286, `I8` 63, `I4` 62
over a wider sample; dimensions 64x64, 128x128, 128x64, 32x32, 256x256, 64x32.

## `FILL` was ending the SHOC walk mid-archive

`FILL` is usually an ordinary sized chunk, but it is **also used as a bare four-byte pad**, and
there the next four bytes are another tag rather than a size.  Reading that one as a sized
chunk takes the next tag's letters as its length: the walk stopped **958,460 bytes into a
3.5 MB file** on Tiger Woods 2005 and reported success, because everything up to that point
parsed.

The rule is conditional - a `FILL` whose next four bytes are a known tag is a pad, otherwise it
is a sized chunk.  Treating *every* `FILL` as four bytes is equally wrong and takes Tiger Woods
06 from 11 of 12 archives landing exactly to none.  Both directions are pinned by tests.

    lands exactly on the last byte, 12 archives a disc
    before:  2003  0/12   2004  0/12   2005  4/12   06  11/12
    after:   2003 12/12   2004 12/12   2005 12/12   06  12/12

**This corrects the earlier claim that "120 of 120 sampled archives parse".**  They did parse -
`members()` returned a list and no error - but on three of the four discs it returned two to
four members an archive instead of about forty-eight.  Members found over twenty archives a
disc: 2003 **60 -> 953**, 2004 **90 -> 984**, 2005 **111 -> 1,364**.  *An archive that parses
is not an archive that was read.*
