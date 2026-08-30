# Darkened Skye - `GCT` textures and the rest of the disc

The disc reported zero models and zero textures.  It holds 4,340 `.gct`, 283 `.gcp`, 55 `.gcx`,
55 `.lev`, 17 `.skg` and 16 `.pak`.

## `GCT` textures - CRACKED

`gcrip/formats/gct.py` + `gcrip/plugins/gct.py`.  A 32-byte big-endian header, then a GX mip
chain:

    +0   u16 magic 0xDEAD
    +2   u16 width
    +4   u16 height
    +6   u8  mip levels minus one
    +7   u8
    +8   u32 0x00CCCCCC   fill
    +12  u32 GX format    ordinary GX codes - 14 CMPR, 5 RGB5A3, 1 I8, 3 IA8, 6 RGBA8
    +32  pixels

**Two fields had to be told apart.**  Byte +6 reads like a format at a glance and is not - it is
the level count less one, and taking it for a format leaves every file unexplained.  The format
is the `u32` at **+12**, and it holds real GX codes, so nothing needs mapping.

The arithmetic is the proof, and it is unusually clean: with levels from +6 and the format from
+12, header plus mip chain accounts for the file size **exactly on all 4,340 files** - 4,340
decoded, none rejected.  It also settles what size alone cannot: `I8` and `C8` are both 8 bits
per pixel, so only the header separates them.

Formats across the disc: CMPR 3,814, RGB5A3 440, I8 69, IA8 16, RGBA8 1.  Only 24 decode flat.

## The rest, mapped for next time

* **`.pak`** (16) - `PAK\0` + version 1 + count, then a table of NUL-terminated names
  (`COIN.SKX`, `CSDIELER.SKX`, `DRAAK.SKX`, `FRUITCEKE.SKX`).  A named archive of `.SKX`, which
  are the model candidates.
* **`.skg`** (17) - opens `\0GKS`, i.e. `SKG` byte-swapped, then a model name (`CSDealer`).
* **`.lev`** (55) - text-tagged level data: `START LOCATION`, `ZONE LIST`.
* Video is `.thp` (Nintendo's own), audio `.adp` / `.gca`.

`.pak` is the obvious next step: it is a plain named archive and the `.SKX` inside it are where
the geometry should be.
