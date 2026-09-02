# Gun (Neversoft) - `.ngc` reconnaissance (2026-09-01)

Cluster 4's last disc.  It produces **0 models and 0 failures** - nothing claims its files at
all, which is why there is no error to chase.

## The files are not hashed

`docs/OPEN.md` recorded "2,928 hashed `.ngc` files; a 120-file magic sample gives no dominant
header".  Both halves are misleading.  The names are perfectly ordinary once the whole name is
read rather than the last extension - `af_intro_text.apk.ngc`, `gun_bannericon_01.img.ngc`,
`af_intro_cam0.apk.ngc` - and they sort into six kinds:

| sub-extension | files | MB |
|---|---|---|
| `.apk.ngc` | **1,233** | 136.8 |
| `.mpk.ngc` | **1,233** | 191.7 |
| `.shd.ngc` | 166 | 0.6 |
| `.img.ngc` | 158 | 16.8 |
| `.pak.ngc` | 119 | 31.9 |
| `.fnt` / `.qb` / `.nav` | 9 | 1.0 |

**`.apk` and `.mpk` pair exactly, 1,233 to 1,233**, and share their stems.  That is the same
shape as EA's `.ord`/`.orp` pair, where reading only one half of it cost twelve discs every
model they had, so it is the first thing to test here.

## Why nothing claims them

`plugins/neversoft.py` routes `.img.ngc`, `.tex.ngc`, `.mdl.ngc` and `.scn.ngc`, so the 158
`.img.ngc` **are** offered to it - and `nv.is_img` rejects every one, because it requires the
first word to be `2` and Gun's is `0x04200000`.  Content-sniffing all 2,918 files with
`is_model`, `is_img` and `is_tex` claims **none of them**.  So this is a newer format
generation, not a routing accident, and the same is true of the models: Gun is 2005, alongside
American Wasteland, and both fail where Underground succeeds.

## What is known about `.img.ngc`

A 32-byte header, all samples sharing the shape::

    04 20 00 00  00 00 00 00  00 00 05 05  00 06 04 04  ...   gun_icon_01,  1,568 bytes
    04 20 00 00  00 00 00 00  00 80 09 09  00 06 04 04  ...   loadscrn,   786,464 bytes

Bytes +10 and +11 look like **log2 of the dimensions** - `05 05` for a 32x32 icon and `09 09`
for a 512x512 screen - but the payload sizes do not both follow from that, and two samples are
not enough to settle it:

* the icon's 1,536 payload bytes are exactly `32*32` plus a 512-byte 256-entry palette, which
  reads as `C8`;
* the load screen's 786,432 are exactly `512*512*3`, which is not a GX format at all, and also
  exactly `1024*768` at one byte a pixel, which is a screen resolution and suspicious for a file
  called `loadscrn`.

Both readings cannot be right and neither is confirmed.  **Recorded as reconnaissance, not
findings** - the next session should pull a dozen `.img.ngc` of different sizes and let the size
arithmetic settle the dimension field before any decoder is written.

## Tested 2026-09-02: the `.apk`/`.mpk` pairing is **not** an `.ord`/`.orp` pair

The note above called that "the first thing to test here".  Tested, and it is wrong.

**918 of the 1,233 `.mpk` are exactly 32 bytes**, and those 32 bytes are `AB AB AB ...` - the
MSVC uninitialised-heap fill.  They are placeholders, not the second half of anything.  Only
**315 carry content**, 191.7 MB of it, and their names say what they are: `z_steamboat2`,
`z_fort`, `z_lveast`, `z_hunt`, `z_steamboat`.  **`.mpk` is a map pack** - only levels have one -
and `.apk` is the per-asset pack.  So the EA analogy fails: an EA `.orp` is never empty, because
it is half of one object.

The `.apk` type word is a Neversoft checksum rather than a magic.  Over 62 sampled files it
takes four values: `0xa7f505c4` (49), `0x745dcd45` (7), `0xdad5e950` (4), `0x2b0a3095` (2).

## The `04 20 00 00` header reads, and it is shared

`z_hunt.mpk.ngc` **opens with the same header as an `.img.ngc`**, so this is one asset header
used across the disc rather than an image format.  Big-endian::

    +0    u32  0x04200000
    +8    u16  ?              0x0080 and 0x2000 on two files, 0 on the rest
    +10   u8   log2 width
    +11   u8   log2 height
    +13   u8   GX texture format
    +16   u32  payload bytes
    +20   u32  header bytes   32 on every sample
    +24   u32  offset of the next image, 0xffffffff at the end

**The identity: `payload + 32 == the file's length`, on 5 of 5 distinct sizes** - 1,536+32=1,568,
3,584+32=3,616, 8,192+32=8,224, 786,432+32=786,464.  The fifth is what proves `+24` is a chain
rather than padding: `map_compass.img.ngc` declares an 8,192-byte payload but is 16,416 bytes,
and its `+24` is 8,224 - exactly where a second image starts, and 8,224 + 8,192 = 16,416, the
file's length.

**Format 14 is CMPR and the dimensions are log2**, confirmed together: the 128x128 maps carry
exactly 8,192 payload bytes, which is 128 x 128 / 2.

**Format 6 does not reconcile and is not settled.**  Under the same reading it implies three
different rates for one code - 1.5 bytes a pixel at 32x32 (1,536), 0.875 at 128x32 (3,584) and
3.0 at 512x512 (786,432).  One of the dimension or format readings is wrong for those files and
guessing which would only bury it; recorded so the next attempt starts from the contradiction.

## The geometry is not display lists

A full `gxscan` of the 2.4 MB `z_hunt.mpk.ngc` finds **3 meshes and 168 triangles** in 23
seconds.  As on Asterix, the fallback scanner is not the route in on this disc.
