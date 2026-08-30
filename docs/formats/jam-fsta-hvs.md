# `.jam` archives (GameCube) - surveyed 2026-08-30

`.jam` is not one format.  Across five discs it is three:

| magic | discs | files |
|---|---|---|
| `FSTA` | Grim Adventures of Billy & Mandy (99), Codename: Kids Next Door (56) | 155 |
| `JAM2` | Charlie and the Chocolate Factory | 38 |
| `LJAM` | Hunter: The Reckoning | 35 |

All five discs report zero models; Hunter has 566 textures from elsewhere, the rest are blank.

## `FSTA` - structure mostly mapped

High Voltage Software's archive (the members open `HVSI` - the studio's initials).

    +0   char magic[4]   "FSTA"
    +4   u32 checksum
    +8   u32 directory size
    +12  char compression[16]   "none" on every file seen
    +28  u16 name count         (47 in Bbay4.JAM)
    +30  u16 extension count    (20)
    +32  char names[count][8]   fixed 8-byte NUL-padded: ART, AUDIO, BBAY4, BLADE, CAST ...
    ...  char exts[count][4]    fixed 4-byte: "", AGD, AGM, AGS, AGT, AKC, AOB, AOD, AOS,
                                ASB, ASD, ASE, ASN, GGG, GKA, GMS, GON, MNG, TPL, VFX

Entries are **12 bytes**: `u16 name index | u16 extension index | u32 offset | u32 size`.  The
offsets are **0x800-aligned**, which is the check that identifies the table: at 0x21c in
`Bbay4.JAM` six `MNG` entries parse cleanly and their members really do start where they say
(`BBAY4.MNG` at 0x1000 is a `Load...` manifest, the other five are `Soun...`).

**SHIPPED** as `gcrip/formats/fsta.py` + `gcrip/plugins/fsta.py`.

The entry table is not uniform - the `MNG` group is 12 bytes per entry but other groups pack
differently, and the per-group index has not been decoded - so rather than guess a stride the
reader takes anything in the directory that satisfies all four constraints at once: both indexes
in range, non-zero size, an offset past the directory that is **0x800-aligned**, and the member
fitting in the file.  Members are keyed by offset so nothing is counted twice.

A scan rather than a walk, but a strict one, and what it recovers is right: over 20 archives per
disc, **477 members on Billy & Mandy and 21 on Kids Next Door**, whose first four bytes are real
headers throughout - `RotT`, `ISVH`, `Node`, `Surf`, `Set`, `Stag` - and the TPL magic on
every member the extension table calls `TPL`.

### The TPL members are a High Voltage variant

They are NOT stock Nintendo TPL and `gcrip.formats.tpl.parse` cannot read them.  The variant has
an **extra `u32` at +8**, so the field the standard reader takes for the image-table offset is
zero, and the one after it (0x14) is not a table either.  The image header itself is ordinary
and sits at **0x18** of the member - `ZOMBIEG1` reads height 64, width 64, format 0x0e (`CMPR`),
data offset 0x6c - and those offsets are relative to the member.

Two false starts worth recording: the offsets are not absolute within the archive (an early
read had a 4 KB member pointing at byte 2,142,000), and the magic alone is not enough to assume
the layout.  Finishing this variant is what turns these two discs' textures on; `GMS`, `GON`,
`GKA` and `MNG` remain the geometry candidates.

## `.dgc` is three engines, not one

The earlier map treated `.dgc` as TotemTech across the board.  It is not:

| disc | files | opens with |
|---|---|---|
| Spirits & Spells, Jimmy Neutron, SpongeBob | 225 / 80 / 78 | `TotemTech Data v...` |
| Superman: Shadow of Apokolips | 255 | `MDGC0200` |
| Disney-Pixar Ratatouille | 320 | `v1.06.63.01 - As...` (a version string) |

So Superman and Ratatouille are two more unexplored formats, not part of the TotemTech work.

## `.fsb` is FMOD

Barnyard (76), Polar Express (70), Nicktoons: Battle for Volcano Island (50), American Chopper 2
(38), Nicktoons Unite! (25) - FMOD sound banks.  Audio, not geometry; not worth pursuing for
models.
