# Acclaim `TBLOCKTEX` / `ASB_TEXTURE` - All-Star Baseball 2002, 2003, 2004

All three discs reported **zero models and zero textures**.  Every texture on them is in `.tex`
files - 1,570 files, 611 MB - in two containers that share one image header.

`gcrip/formats/asb_tex.py` + `gcrip/plugins/asb_tex.py`.

## The image header

The block headers are big-endian and the image headers inside them are little-endian.

    +0   u32 x 2                    GameCube RAM addresses, always 544 apart
    +8   u32 pixel bytes            little-endian
    +12  u32 palette bytes          little-endian
    +16  u16 width | u16 height     little-endian, repeated at +20
    +24  u32 x 2
    +32  the pixels, then the palette

**Nothing in the header names a GX format, and nothing has to.**  The palette size and the bits
per pixel determine it, and the arithmetic then has to agree exactly:

| palette bytes | bits per pixel | format |
|---|---|---|
| 512 | 8 | `C8` |
| 32 | 4 | `C4` |
| 0 | 4 | `CMPR` |
| 0 | 32 | `RGBA8` |

That is the check as well as the decision: `encoded_size(format, width, height)` has to
reproduce the stored pixel byte count, and where it comes up short the extra bytes are a mip
chain.

## The three things that cost time

**The palette comes after the pixels.**  Reading it first *still decodes* - the tiling is right
and the shapes come through - so a Padres jersey arrives with legible "PADRES" lettering and
colour noise across the rest of the cloth.  That reads like a palette-format problem, and it is
not; chasing `RGB565` versus `RGB5A3` there is wasted effort.  Moving the palette to the end
gives a clean jersey immediately.

**The two containers use different palette formats.**  `TBLOCKTEX` palettes are `RGB5A3`;
`ASB_TEXTURE` palettes are `RGB565`.  Nothing in either header says so, and the wrong choice
gives a recognisable picture in wrong colours - a player's face in green and magenta - rather
than noise, so it has to be checked against something known rather than assumed.

**The size at +28 of `ASB_TEXTURE` is the first image's, not a stride.**  On the player-face
files every image is 64x64 and the two readings agree, which is exactly why the mistake
survives; `ASBUI.tex` mixes sizes and a fixed stride walks off the end after one image.
Stepping by each image's own header takes All-Star Baseball 2002 from 68 files to **287 of
288**.

## Containers

    TBLOCKTEX_30_BE\0              (2003, 2004)
    +16  u32 image count           big-endian
    +40  image table, 36 bytes:  char name[32], u32 offset (big-endian)

    ASB_TEXTURE\0                  (2002)
    +16  u32 image count           big-endian
    +24  u32 total pixel bytes
    +28  u32 bytes in the FIRST image
    +36  char name[32] * count, then the images back to back

There is also a single `TBLOCKTEX_30_LE` file on 2004 and one 36-byte `ASB_TEXTURE` stub with
no images at all.

## Result

| disc | `.tex` files | parsed | images decoded |
|---|---|---|---|
| All-Star Baseball 2002 | 288 | 287 | 3,844 |
| All-Star Baseball 2003 | 516 | 515 | 17,307 |
| All-Star Baseball 2004 | 766 | 724 | 21,252 |

**42,403 textures** from three discs that produced nothing at all.  Every image the reader
accepts also decodes - the format decision and the size check are the same test, so a
mis-identified image is rejected rather than drawn wrong.

## Still open

The geometry is beside them and untouched: `.GDF` (194 files, 111 MB on 2003) and `.SKN`
(50 files) both open with a 20-byte NUL-padded name and a big-endian count, then records that
carry 16-byte material and texture names (`two_tone_bat`, `bat`, `bat_shadow`) - so the meshes
name the textures this reader now produces.
