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

**Still to do:** the entries are grouped per extension, and the 52 bytes between the extension
table and the first group (0x1e8..0x21c) are the per-group index that has not been decoded, so
only one group is reachable so far.  Finding it gives the whole archive.

That is worth doing for one reason above all: **`TPL` is in the extension list** - Nintendo's
texture format, which gcrip already decodes - so the two discs should give up their textures as
soon as the archive walks.  `GMS`, `GON`, `GKA` and `MNG` are the candidates for geometry.

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
