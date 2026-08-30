# Free Radical `P4CK` / `P5CK` / `P8CK` - TimeSplitters 2, Future Perfect, Second Sight

Three discs, **637 archives, 2.7 GB**, and all three reported zero models and zero textures.
Everything on them is inside these archives.

`gcrip/formats/frd_pak.py` + `gcrip/plugins/frd_pak.py`.  Little-endian throughout.

## Two header meanings, told apart by arithmetic

    +0   char magic[4]   "P4CK", "P5CK" or "P8CK"
    +4   u32 a
    +8   u32 b
    +12  u32 c

**Sized**, when `a + b + c == len(file)`: `a` bytes of data (this header included), then `b`
bytes of table, then `c` bytes of names.

**Counted**, when `a + b * 12 == len(file)`: `a` is the table *offset*, `b` an entry *count*
and `c` the name-block offset, and each entry is `u32 name offset (from the name block), u32
size, u32 data offset` - size and offset in the opposite order to the other layout.

The magic does not say which; `P8CK` files appear in both.  Both tests are exact and neither
holds on the other's files, so nothing has to be guessed.

## Three entry shapes in the sized layout

    named    16 bytes:  u32 name offset, u32 data offset, u32 size, u32 stored
    hashed   16 bytes:  u32 name hash,   u32 data offset, u32 size, u32 stored
    inline   60 bytes:  char name[48],   u32 data offset, u32 size, u32 stored

Again nothing declares the shape, so the reader tries all three and keeps the one that
reconciles: the table size has to divide by the stride, every member has to fit inside the data
region, and the members have to tile it.  On `igcs_06.pak` the 16-byte hashed reading runs from
byte 32 to 794,304 - the data size exactly - which is what picks it over a 60-byte reading that
also divides.

## The three things that cost time

**A name offset is measured from the start of the table, not the name block.**  On `lv60.pak`
the five offsets are 80, 111, 146, 170 and 196 against a table of 80 bytes; subtracting the
table size lands each one exactly on a string.  Read as name-block offsets they are all 80
bytes late, which produces plausible garbage rather than an error.

**The fourth word is the stored length and the third is the length after unpacking.**  Where it
is zero the member is stored as-is and the two agree - which is most files, so the mistake
survives.  Where it is not, reading the third word as the stored length walks the archive off
the end of its data region, and the symptom is a fifth of Future Perfect's archives failing a
range check for no visible reason.

**An empty member is not a wrong reading.**  The cutscene archives are full of zero-size
entries; disqualifying a shape because one member is empty throws away the whole archive.

## Compression, and the names hidden in it

Members whose stored length differs are **gzip**, and the gzip header carries `FNAME` - the
real file name, `prop_all_gcas.war`, `str_ts_pgs.bs`.  That is the only place the hashed
archives keep a name at all, so unpacking is what gives them back.

## Result

Sampling 50 archives a disc across the size range:

| disc | archives sampled | parsed | members | bytes out |
|---|---|---|---|---|
| TimeSplitters 2 | 49 of 69 | 49 | 18,378 | 275 MB from 276 MB in |
| TimeSplitters: Future Perfect | 50 of 339 | 50 | 4,106 | 81 MB from 62 MB in |
| Second Sight | 50 of 229 | 50 | 2,055 | 54 MB from 54 MB in |

**24,539 members**, and Future Perfect's output exceeds its input because most of it is packed.
The members are `gct` (12,974 in the sample), `gcr` (2,467), `war` animation, `dsp` audio and
`bs` scripts.

## `gct` textures - partly cracked

`gcrip/formats/frd_gct.py` + `gcrip/plugins/frd_gct.py`.  Big-endian, 32 bytes:

    +0   u32 width
    +4   u32 height
    +8   u32 width again
    +12  u32 height again
    +16  u16 mip levels | u16 format
    +20  12 bytes

The doubled width and height are the check that the header is being read at all, and **the mip
count is the high half of the word at +16** - read as one `u32` a three-level format 5 comes out
as "format 196,613", which is what one file in the sample looked like.

The format code is Free Radical's own and does not map one-to-one onto GX:

| code | what it is |
|---|---|
| 2, 3, 4, 10, 13 | `CMPR` |
| 5, 7 | `I8` |
| 6, 8 | `RGB5A3` |
| 0 | `RGBA8` |
| 9, 11, 12 | not identified - under 3% of the sample |

**6,409 of 6,465 textures in the sample decode: 100% on TimeSplitters 2, 98% on Future
Perfect, 99% on Second Sight.**

### How the codes were settled, and the wrong turn on the way

The obvious move is to divide the file length by the pixel count and read the answer as bits
per pixel.  It does not work, because **a file usually holds more than the top level**.  Codes
4 and 10 carry exactly twice the `CMPR` data their size needs, which reads as "8 bits a pixel"
and points at `I8`, `IA4`, or a palette that is not in the file - and `I8` duly draws a
GameCube controller as vertical banding, which looks exactly like an index stream shown as
intensity.  That is a convincing dead end; it cost a round of hunting for palettes that do not
exist.  Taking the first `encoded_size(fmt, w, h)` bytes draws the controller.

Where the mip count is set the whole chain is stored, and *then* the ratio identifies the
format, because a full chain is four thirds of the top level:

| bytes / pixels | top level | format |
|---|---|---|
| 0.67 | 0.5 | `CMPR` |
| 1.33 | 1.0 | `I8` |
| 5.33 | 4.0 | `RGBA8` |

Each was then confirmed by looking: a sky gradient for `RGBA8`, a marble panel and a lens
flare for `I8`, shotgun shells and a GameCube controller for `CMPR`, a mouse pointer and a
rain streak for `RGB5A3`.

## Still open

`gcr` is the geometry and is untouched.  Both it and the palette-indexed `gct` are now
reachable by the rest of the pipeline under their real names, which is what the container was
in the way of.
