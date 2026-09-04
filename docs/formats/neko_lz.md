# Neko Entertainment LZ and the Cocoto level files

Codec read 2026-09-04 (`gcrip/formats/neko_lz.py`, `gcrip/plugins/neko_lz.py`, `tests/test_neko_lz.py`).

Cocoto Kart Racer, Cocoto Funfair and Cocoto Platform Jumper keep each level as four files the
DOL names by format string - `L%d.GCN` (the world), `L%dGFX.PC` (textures), `L%dTIN.PC`
(small tables) and `L%d.CP2` (placements, uncompressed).  The first three are LZ-packed:

    u32 packed bytes (big-endian, = file size - 8)
    u32 unpacked bytes
    LZSS: flag byte, bits LSB-first; 1 = literal byte; 0 = reference b0 b1 with
          distance (b0 | (b1 & 0xf0) << 4) + 1 and length (b1 & 0xf) + 3;
          a reference reaching before the start of the output copies zeros

The dialect was found by sweeping flag order, literal bit, field packing and minimum length on
a 2,228-byte `TIN.PC`: four variants reproduce the exact unpacked size, one of them gives
structured output (`0a 00 10` records and ascending index runs), and that one unpacks every
`.GCN` and `.pc` on the three discs to its declared size - 3.4-5.9 MB in, 5.6-9.7 MB out.

## What is inside (open)

The unpacked `.GCN` is a single `MWLD` chunk - `u32 3, u32 4, u32 bytes, "MWLD"` - followed by
`00 01 dd 0c, 00 00 09 cf, 00 09 cf 94, 00 00 05 f8, 1, 0` and a long run of records shaped
`20 09 cf 94 01 xx ...` with small ascending numbers.  `gxscan` finds no GX display lists in
6 MB and there are no `f32` runs in either byte order, so the geometry is quantised and the
world is a serialised object tree (possibly bit-packed - the `09 cf 94` words repeat inside
the records).  `GFX.PC` opens straight into CMPR-looking block data with no header, so the
texture directory is in the `.GCN`.  The `.cp2` is readable as is: `u32 100, u32 count, ...`
with names such as `Node_Start_Battle`, `MAP_CORNER`, `TORCHE`.

The DOL is stripped; the loader that formats `%sL%d\L%d.GCN` is the entry point for the
DOL route.
