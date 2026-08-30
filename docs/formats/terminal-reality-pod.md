# Terminal Reality POD archives (GameCube) - CRACKED

Four discs: BloodRayne, Blowout, RoadKill (`POD3`) and 4x4 Evo 2 (`POD2`).  38 archives,
19,678 members.  Read by `gcrip/formats/pod.py` + `gcrip/plugins/pod.py`.

## Why it looked undocumented

The earlier probe failed because it assumed the index sat at a fixed place.  In `POD3` the
index is at the END of the file and its offset is stored at header 0x108 - an UNALIGNED value
(0x2e97 in Blowout's `LANGUAGE.POD`) that cannot be derived from the file size or from
`names_start - count * entry_size`.  The tail of the file is not the index either: it holds an
audit trail of one record per edit (the developer's user name - `craig` on Blowout - a
timestamp and the path), which is what the earlier "shared suffix name table" probe was
actually looking at.

## Header (little-endian)

    char magic[4]   "POD2" / "POD3"
    u32  checksum
    char comment[80]        "Localized, platform-independent files" / "4x4Evo2 Shipping Trucks"
    u32  file count         0x58
    u32  audit count        0x5c   (POD3)
    u32  revision           0x60   (POD3; 1000)
    u32  priority           0x64   (POD3; 1000)
    char author[80]         0x68   (POD3)
    char copyright[80]      0xb8   (POD3)
    u32  index offset       0x108  (POD3 only)
    u32  index checksum     0x10c
    u32  name table size    0x110

`POD2` stops at 0x60 and puts the index INLINE there, then the name table, then the data.
`POD3` grows the header to 0x120, puts the data first (starting at 0x120) and the index last.

## Index

One 20-byte entry per file, identical in both versions:

    u32 path offset   (relative to the name table, which follows the index)
    u32 size
    u32 offset        (absolute in the file)
    u32 timestamp     (unix, e.g. 0x3f8b1041)
    u32 checksum

Names are NUL-terminated and SHARE SUFFIXES - a shorter name may point into the tail of a
longer one (`WORLD\EN\06_CREW_STARBOARD.TXT` then `XT` at +29) - so they must be dereferenced
by pointer, never walked in sequence.  Backslashes are separators.

## Verification

File data is contiguous, so entry offsets tile exactly, and that is the check to use:

* Blowout `LANGUAGE.POD`: 21/21 entries tile, data ends exactly at the index offset 0x2e97;
* 4x4 Evo 2 `TRUCK.pod`: 1241/1241 tile, 1242/1242 names resolve;
* whole-cluster parse: BloodRayne 12,419 members, RoadKill 5,093, Blowout 2,071,
  4x4 Evo 2 3,930 across its top four archives.

## What is inside (the next step)

Per-game formats, not a shared engine:

* `MODELS/*.BST` (BloodRayne 43, Blowout 11) and `MODELS/*.BQS` + `.BVT` (RoadKill 14 each) -
  the geometry, still open;
* `ART/*.TEX` (BloodRayne 3,785, Blowout 787) - textures, still open;
* `PACKAGE/*.PKG` (per level, 40-280 MB total) - level packages;
* `SOUND/*.GCA` / `.SPD` / `.SPT` / `.LIP` - audio and lipsync, plus `.TIF` loading screens.

Expanding the POD is worth it on its own: it hands the structure scanner named, per-level
blobs instead of one 277 MB file.
