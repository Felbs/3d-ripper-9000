# `HFF` data files - Aquaman, Casper, TONKA Rescue Patrol

Three discs, one `.hff` apiece, 144 to 251 MB, and all three produced nothing.  They turned up
as the only multi-disc group among the discs whose largest data file **no plugin claimed at
all**.

## There is no directory

The last four kilobytes of all three are zero.  There is no table at the head either: the file
begins with its first member - a `PNG` on Aquaman, and on the other two a text file opening
`// this file contains the path to the *.obd file`.  So the members have to be **carved**.

## Carving safely

Carving is only sound for formats whose *end* is unambiguous, and that is the whole design of
this reader.  A `PNG` closes with `IEND` followed by its four CRC bytes, so a member's extent
is exact rather than inferred.

The tempting alternative shows why the rule matters.  A first magic census counted "BMP" hits
by looking for `BM`, and reported 303 of them in a 32 MB sample of Aquaman - more than the 207
PNGs.  Two bytes match everywhere; every one of those was noise.  `PNG` and `JPEG` are the only
two image formats here with a terminator, and only `PNG` is actually present in quantity.

## Result

| disc | `.hff` | carved | decoded |
|---|---|---|---|
| Aquaman: Battle for Atlantis | 251 MB | 2,800 | **2,800** |
| TONKA Rescue Patrol | 199 MB | 1,897 | **1,897** |
| Casper | 144 MB | 0 | 0 |

**4,697 textures from two discs that produced nothing**, and every carved member decodes -
which is the check, since a mis-carved PNG fails immediately rather than producing a plausible
wrong image.

Sampling would have got this wrong, and nearly did: four 8 MB windows spread through TONKA's
file found five PNGs, from which the file looked barely worth carving.  Over the whole file it
holds 1,897.  **Where a carve is cheap, carve the whole file rather than extrapolating from
samples.**

## Casper

Casper's `.hff` holds no PNG at all.  Its bulk reads as `f32` unit vectors - triples like
(0.652, -0.139, -0.898) repeating - so the geometry is in there in some other form, with the
leading text file naming `.obd` and `.lvl` paths that are presumably its members.  That is the
next thing to look at on this disc.

## `PNG` itself

gcrip has listed `\x89PNG` among the magics `gcrip/formats/generic.py` recognises since early
on, but had **no PNG decoder** - so a PNG handed out by any container fell through to the
fallback and produced nothing.  `gcrip/formats/png.py` + `gcrip/plugins/png.py` close that,
and it applies well beyond these three discs: FutureTactics' `files.pak`, for one, indexes
members by paths like `FRONTEND\ALIENGICON(1).PNG`.


## The rest of the file is RenderWare (2026-09-03)

`casperGCN.elf` keeps a symbol table, and it is RenderWare 3.0's: `readGeometryNative`,
`WorldBuildMeshAtomicSector`, `SkinGeometryRead`, `GeometryListStreamRead`, `_rxDlVertexFmt`.
Scanning Casper's first 16 MB for little-endian chunk headers with the RW 3 stamps
(`0x0800FFFF`, `0x0C02FFFF`) finds them back to back from 67,584 on: three texture
dictionaries, one world, 40 clumps and 148 bare rasters (type 0x15), 56% of the bytes.  The
`hff` container walks them now - a top-level TEXDICT / CLUMP / WORLD / raster whose size fits
is a member, the next starts at its end, and anything else resyncs 4 bytes on - and the
RenderWare plugin reads them unchanged: Casper's world is 13,650 triangles with 78 textures
bound from the dictionaries beside it; TONKA's middle 12 MB hold 104 clumps (28,301
triangles); Aquaman's head 3 clumps and a world, 34,212 triangles.  Aquaman's textures are
its PNGs, which the streams cannot name, so its models come out untextured for now.
