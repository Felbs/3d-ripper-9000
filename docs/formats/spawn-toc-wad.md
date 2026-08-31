# `TOC` `.wad` archives and `TIM` textures - Spawn: Armageddon, The Scorpion King

Two discs, 401 `.wad` files, 747 MB, both reporting zero models and zero textures - and the
dead-ends list said these were audio.

**They are not.**  Of the 20,917 members across the two, **12,018 are textures** and 286 are
sound.

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

**All 5,919 of Spawn's decode - 100%, every one `CMPR`.**

## The Scorpion King - the same records without the table

Its 200 `.wad` carry the identical member types but no central table.  Each record is a 28-byte
wrapper - `char name[16] | char type[4] | u32 size | u32` - and **the next record follows at
`offset + 28 + size`**: the size counts only what comes after the wrapper.  Reading it as the
whole record's length stops the walk after exactly one member on every file, which looks like a
one-member archive rather than a mistake.

    200 of 200 walk -> 8,883 records, 299 of 312 MB
    TIM 6,099 | PHM 1,221 | PHA 754 | PAT 267 | SOB 189 | SFX 144 | GAM 140 | SPR 49

The walk stops a little short of each file's end rather than exactly on it, so the tail is
padding or something unindexed - reported rather than claimed as exact.

Because the variant has no magic at all, a single plausible record is not enough to claim a
file; the reader requires at least two.

### The variant was invisible to the pipeline for a while

`members()` and `expand()` handled the inline records and had tests.  The **plugin** did not:
its `is_container` asked only `is_toc_wad`, which wants Spawn's `TOC` magic at +16, so every
one of The Scorpion King's 200 archives was refused and its **6,099 textures never reached a
scene**.  The disc rebuilt with zero textures and nothing failed - the reader was simply never
called.

The variant has no magic, so it is now recognised from the shape of its first record inside
the 64 bytes `classify` sniffs - a NUL-padded printable name, one of the nine known type tags,
and a plausible size (`looks_inline`).  `members()` still requires two chaining records, so a
loose claim costs an in-memory parse and nothing else.

Measured after the fix, on 25 of the 200 archives: **25 claimed, 1,088 members, 992 `TIM`
decoded**, where before it was nothing at all.

### The palette path only exists on this disc

All 5,919 of Spawn's textures are `CMPR`.  The Scorpion King has 185 `C8`, and a decoder
written against Spawn alone raises `C8 needs a palette` on every one.  The palette is in the
member's tail: those textures carry 560 trailing bytes, a 256-entry `RGB5A3` palette plus the
same 48-byte footer every member has.

**All 6,099 decode** - `CMPR` 5,913, `C8` 185, `RGBA8` 1.

## What the other member types are

Sampled from Spawn's `global.wad`:

* **`PHM` is the model.**  `SPAWN.PHM` is 90 KB opening `u32 0 | u32 1 | u32 64` and then a
  block of `f32` that reads as a 4x3 matrix per bone.  Crucially it **names its textures
  inline** - `SPAWNTPAGE02`, `SPAWNTPAGE01`, `SPAWNTEYE` at about +242, which are exactly the
  `TIM` members decoded above.  So whenever the geometry falls, the models come out textured
  rather than bare; the binding is already in the file.
* **`PHA` is animation.**  `SPAWNANM.PHA` is 2.7 MB and its name table reads `GRAPPLE`,
  `GRAPPLE_WALL`, `DIE_B`, `JUMP_`.
* **`SPR`** is a sprite: an offset table then names like `PARSHELLCS01`.

### What is known about `PHM` geometry

* `gxscan` finds **no display lists** in it, so the primitives are not stored as GX.
* There is **no run of 60 or more plausible `f32`** anywhere in the file beyond the matrix
  block, so the vertices are quantised rather than float.
* The longest run of `u16` under 2048 is 3,712 values at offset 22,964, and they cluster
  tightly (`04ff 04fd 04fe 0502 0500 ...`) - which reads as fixed-point coordinates around a
  centre rather than as an index list, since indices would start low and spread.

That is where the next session should start on these two discs.
