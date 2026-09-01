# Yuke's `.tex` texture directories - WWE Day of Reckoning 1 and 2, WrestleMania XIX and X8 - CRACKED

Four discs holding **8,652 `.tex` files and 381 MB** between them, and all four reported
almost nothing: 14, 76, 9 and 623 textures.  Nothing opened the `.tex`, so every TPL inside
was invisible.

Read by `gcrip/formats/yukes_tex.py` + `gcrip/plugins/yukes_tex.py`.

| disc | `.tex` files | MB |
|---|---|---|
| WWE Day of Reckoning | 5,338 | 162 |
| WrestleMania XIX | 1,783 | 100 |
| WWE Day of Reckoning 2 | 520 | 47 |
| WrestleMania X8 | 1,011 | 72 |

## How it was found

By censusing the 151 discs that produce **textures but no meshes** and grouping them by the
magic of their largest non-audio file. That put three of the four WWE discs together on `MPQ\0`, which
sent the first look at their `.mpq` archives - and those turned out to be mostly THP video and
YDSP audio. The extension census of the discs themselves is what pointed at `.tex`.

The `.mpq` container is worth recording even so, because it is trivially readable and holds the
`LOADTIPS` TPLs and a 356-member `entpac`: big-endian `MPQ\0`, `u32 align (2048)`,
`u32 table offset (16)`, `u32 count`, then `count + 1` ascending absolute offsets. **All eight
archives on Day of Reckoning tile exactly** (last offset == file size).

## The format

Little-endian.

    +0    u32 count            30
    +4    u32 0x100
    +8    u32 0
    +12   u32 16               where the table starts
    +16   the table, 32 bytes an entry:
              char name[16]    "tooth", "blood", "c036_hand", "cos_sode", "eye"
              char type[4]     "tpl"
              u32 size
              u32 offset
              u32 0

Detection is the first entry's type tag at +32, inside the 64 bytes `classify` sniffs.

## The one trap: the size comes before the offset

Reading them the other way round produces numbers that all look reasonable - offsets inside the
file, sizes below its length - and the mistake does not announce itself. It shows up only as
entries that overlap and point into the middle of their neighbours.

What settles the order is that the payloads then land on the TPL magic. With size and offset
the right way round, all 30 entries of `036_0.tex` point at exactly the 30 `00 20 af 30`
headers the file contains, and consecutive members tile to the byte:

    992 + 1088 = 2080,  2080 + 33376 = 35456,  35456 + 8256 = 43712,  43712 + 32832 = 76544

The reader therefore refuses a file whose members overlap rather than trusting the field order,
which is what turns the swap into a decline instead of 7,641 files of garbage.

## The members are ordinary TPLs

There is no new texture code here: `gcrip/plugins/tpl.py` already claims anything carrying the
TPL magic in its first 64 bytes, so expanding the container is the whole job.

Measured on the first 40 `.tex` of each disc:

| disc | sampled | claimed | members | TPL | decoded |
|---|---|---|---|---|---|
| WWE Day of Reckoning | 40 of 5,338 | 40 | 153 | 153 | 153 |
| WWE Day of Reckoning 2 | 40 of 520 | 40 | 181 | 181 | 181 |
| WrestleMania XIX | 40 of 1,783 | 40 | 1,265 | 1,265 | 1,265 |
| WrestleMania X8 | 20 of 1,011 | 20 | not counted | - | - |

**1,599 textures from 120 of the 8,652 files**, every member a TPL and every one decoding.

## Registering it

A container-only plugin still needs `detect` and `extract`, even when they do nothing:
`container_plugins()` lists only modules that are plugins in the full sense, so a container
without them is never consulted and fails silently. `tests/test_afs.py` guards this for every
plugin in the package and caught it here.

## Still open on these discs

The models. `.pms` (166 files, 101 MB on Day of Reckoning), `.mpc` (45, 62 MB), `.pac`
(196, 57 MB) and `.ymg` (1,099, 14 MB) are unexamined, and the texture names -
`c036_hand`, `c036_waist`, `n001_waist` - say the meshes are per-wrestler and should bind by
the same numbering.
