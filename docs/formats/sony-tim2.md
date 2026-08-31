# Sony `TIM2` textures - Capcom's GameCube ports keep them from the PS2

`gcrip/formats/tim2.py` + `gcrip/plugins/tim2.py`.  Found inside AFS members on **Auto
Modellista** (`afs00`, `afs01_gu`, `afs02`) and **Capcom vs SNK 2 EO** (`afs02`).  Little-endian:

    +0   char magic[4]     "TIM2"
    +4   u8   version
    +5   u8   format        1 -> the file header is padded to 128 bytes, 0 -> 16
    +6   u16  pictures
    ...  each picture header:
         u32 total size | u32 clut bytes | u32 image bytes | u16 header bytes
         u16 clut colours | u8 picture format | u8 mip levels | u8 clut type
         u8 image type | u16 width | u16 height

**The header checks itself twice**: `image + clut + header == total`, and `total` plus the
16- or 128-byte file header equals the member's own length.  Both hold on every picture found,
which is what makes scanning for a four-byte ASCII magic safe here.

## Two things that had to be measured rather than assumed

* **The pixels keep the PS2's linear layout** - they are not re-tiled for GX.  Reading the
  index plane as an 8x4 or 4x4 GX tile scrambles it, and the roughness says so: **28.6 linear
  against 50.2 and 47.5** for the two tilings.
* **The CLUT's entry width comes from the byte count, not from the clut type.**  Three widths
  occur - 4 bytes (RGBA), 3 (RGB), and 2 (PS2 `A1B5G5R5`, red in the low five bits).  Taking
  the width from the type word would have decoded only the 4-byte ones; measuring it lifted the
  yield from 16 pictures to 25.

The 256-entry CLUTs are stored **CSM1**, which swaps the middle two groups of eight inside every
block of 32.  That is applied because the format says so and the numbers agree, not because the
numbers alone would prove it: unswizzling improves image roughness from 19.35 to 16.72 on Auto
Modellista and 47.57 to 46.87 on Capcom vs SNK 2 - both in the right direction, neither
dramatic.  PS2 alpha runs 0-128, so it is doubled and clamped.

## Reaching them: an offset table the sniff cannot see through

Most are not AFS members themselves.  A member is an **ascending `u32` offset table closed by
`0xffffffff`**, each entry pointing at a `TIM2`.  The first entry is very often **exactly 64** -
so on the 64 bytes `classify` sniffs, the magic it points at is one byte out of reach, and a
detector that insisted on seeing it claims nothing.  Detection therefore tests the table's
*shape* and `expand` does the real check, keeping only slices that land on the magic.

The same 64-byte horizon bites in a second way: the walk's bound `value < len(data)` is correct
on a whole blob and wrong on a sniff, where every entry after the first points past the end.
It is now passed in only when the whole blob is in hand.

## Yield

**25 of 28 pictures decode** - Auto Modellista 23 (nine 64x64, eight 256x256, four 128x128, two
32x32), Capcom vs SNK 2 two 256x256.  The three that decline carry an eight-byte CLUT stride
that no documented format explains; guessing at those would produce plausible nonsense.

TIM2 is Sony's, not Capcom's, so this decoder should pay off on any other PS2 port in the
library that kept its textures unconverted.
