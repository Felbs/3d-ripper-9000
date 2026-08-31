# `TOC` `.wad` archives and `TIM` textures - Spawn: Armageddon

The disc reported zero models and zero textures.  It is 201 `.wad` files, 435 MB, and the
dead-ends list said they were audio.

**They are not.**  5,919 of the 12,034 members are textures; 142 are sound.

## Why the dead-end note was wrong

It came from sampling four bytes at the start of each file.  That is exactly the trap this
family produces: on The Scorpion King, whose `.wad` open with **their own name** rather than
zeros, a four-byte sample returns `TBLE`, `GMLE`, `MTPP`, `RVAR`, `LEV0` and `MCPA` - which
read like chunk tags and are simply the first four letters of `TBLEV30SFX`, `RVAREA04SFX` and
so on.  **A four-byte sample turns an embedded filename into a fake magic**, in both
directions: it invented tags there, and it hid Spawn's real one, because Spawn's archives open
with sixteen zero bytes and put `TOC` at +16.

## The container

`gcrip/formats/toc_wad.py` + `gcrip/plugins/toc_wad.py`.  Big-endian.

    +0   16 zero bytes
    +16  char magic[4]   "TOC\0"
    +20  u32 table bytes
    +24  u32 entry count
    +28  the table, 32 bytes an entry:
             char name[16]      "SPAWNTPAGE02", "GLOBALSFX", "DBSHOTGUN_A"
             char type[4]       "TIM", "SFX", "PHM", "PAT", "PHA", "SPR", "GAM", "GRP"
             u32 offset
             u32 size
             u32
    ...  the members, 32-byte aligned

`table bytes == count * 32` is the check, and it holds on **all 201 archives**:

    201 of 201 parse -> 12,034 members, 421 of 435 MB
    TIM 5,919 | PHM 2,071 | PAT 2,031 | PHA 1,602 | SFX 142 | SPR 141 | GAM 107 | GRP 12

## The textures

`gcrip/formats/toc_tim.py` + `gcrip/plugins/toc_tim.py`.  The name is Sony's, the contents are
not:

    +0   u32 mip levels          1 or 2
    +4   u16 format              a real GX code - 0x0e is CMPR
    +6   u16 width
    +8   u16 height
    +10  u16 0x0020
    +12  u32 pixel bytes
    +16  the pixels

The format word holds an ordinary GX code, so nothing has to be mapped, and **`pixel bytes ==
encoded_size(format, width, height)`** has to hold.  That is the check rather than "the picture
looks right": a texture that merely decodes into something plausible would still pass the eye,
and this does not.

**All 5,919 decode - 100%, every one `CMPR`.**

## The Scorpion King

Its 200 `.wad` are a different layout: no `TOC`, and only the first 32 bytes parse as an entry.
144 of them are named sound banks (`<name>SFX`), and the other 56 are something else, including
`bonus*.wad` whose first record names a `TIM`.  Left alone rather than forced through this
reader; the leading-sixteen-zeros check in `is_toc_wad` is what keeps them out.
