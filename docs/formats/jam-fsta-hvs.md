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
headers throughout - `RotT`, `ISVH`, `Node`, `Surf`, `Set
`, `Stag` - and the TPL magic on
every member the extension table calls `TPL`.

### The TPL members are a High Voltage variant - CRACKED

`gcrip/formats/tpl_hvs.py`, tried first by `gcrip/plugins/tpl.py`.

They carry Nintendo's magic and nothing else about them is stock.  Stock TPL is
`magic | u32 count | u32 table offset`, with the table holding a pair of POINTERS per image.
The variant inserts an extra `u32` (always zero), so the table offset sits at **+12**, and the
table holds the image headers **inline**:

    +0   u32 magic 0x0020AF30
    +4   u32 image count
    +8   u32 0
    +12  u32 table offset          (0x14 on every file seen)
    ...  image headers, 0x2c apart:
             u16 height | u16 width | u32 GX format | u32 data offset

Offsets are relative to the start of the TPL.  The 0x2c stride is confirmed by the pixels
rather than assumed: in `ZOMBIEG1` the headers sit at 0x14 and 0x40, and the first image
(64x64 `CMPR`, 2,048 bytes) starts at 0x6c and ends exactly where the second's data begins at
0x86c.  Over 41 members it reads 50 images with no failures, all `CMPR`.

**Three false starts worth keeping.**  The offsets are not absolute within the archive - an
early read had a 4 KB member pointing at byte 2,142,000 of the `.jam`.  The image header is at
0x14, not 0x18; miscounting the dump by one row made the `u32` at +12 look like junk when it is
the table pointer.  And matching magic never meant matching layout.

End to end: **50 textures on Billy & Mandy and 4 on Kids Next Door** from the 20 smallest
archives of each - a joystick UI icon and effect glows among them.  `GMS`, `GON`, `GKA` and
`MNG` remain the geometry candidates.

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

## What each extension holds (Billy & Mandy, 20 archives)

| ext | n | opens | contents |
|---|---|---|---|
| ASD | 45 | `Node` | scene nodes |
| ASN | 45 | `RotT` | animation / rotation tracks |
| TPL | 41 | `00 20 AF 30` | **textures - decoded** (`tpl_hvs`) |
| AGD | 38 | `Text`, `Mate` | text, materials |
| AGM | 35 | `Stag`, `Mate` | stage / materials |
| AKC | 35 | `RotT` | |
| GKA | 35 | `ISVH` | (note the magic is byte-swapped vs GMS) |
| ANL | 32 | `Set

{` | **plain text** animation lists - `List[ 67 ]`, `Animation "INTRO"` |
| AGT | 28 | `Surf` | surfaces |
| MNG | 26 | `Grap`, `Soun` | manifests |
| GGG | 23 | `ISVH` | |
| AGS | 17 | `Shad` | shaders |

## `GMS` is the model format, and it is COMPRESSED

`HVSI` + `GMS\0`, then a readable header: `u32 version | u32 size` (0x3418 = 13,336, exactly the
member length) `| u32 0x14 |` counts and offsets, including two `f32` (100.0 and 500.0) and the
value 13,024 twice - the end of the payload.

Everything after 0x60 is **entropy 7.73**, i.e. compressed or encrypted, and none of gcrip's
decoders bite: not zlib at any plausible offset, not Yaz0, not Yay0.  The header itself sits at
entropy 2.39, so this is a compressed payload behind a plain header rather than an encrypted
file.

That puts `GMS` in the same box as the `.hog` WART3.00 codec: a private LZ that has to be
reverse engineered bit by bit before any geometry is reachable.  Worth knowing before anyone
spends a session on the mesh layout - there is no mesh layout to find until the codec falls.

`GKA` and `GGG` (`ISVH`, the same magic byte-swapped) are the other binary candidates and have
not been entropy-checked yet.

## `GKA` and `GGG` are not compressed

Checked after `GMS` turned out to be.  Both open `ISVH` - `HVSI` byte-swapped - but their fields
are **big-endian**: the `u32` at +12 is the exact file size on both (`0xc20` = 3,104 for a `GGG`,
`0xdf5c` = 57,180 for a `GKA`).

Body entropy is **5.28** for `GGG` and **6.82** for `GKA`, against 7.73 for `GMS`, so these are
plain data behind a plain header - readable without cracking a codec.  Neither shows any run of
plausible f32 in either byte order, so whatever geometry they carry is quantised.

Worth keeping in perspective: the models are in `GMS`, which is the compressed one.  `GKA` and
`GGG` are more likely animation or collision, so they are lower value than their readability
suggests.


## Correction: "entropy 7.73, therefore compressed" does not hold (2026-09-02)

The section above puts `GMS` "in the same box as the `.hog` WART3.00 codec: a private LZ that
has to be reverse engineered bit by bit before any geometry is reachable", on the strength of
the payload's entropy.  Entropy alone cannot carry that, and measured properly the payload does
not behave like compressed output.

**The byte histogram is nowhere near flat.**  Over the 13,240 bytes after `0x60`:

| | chi-square (255 df) | max / mean | top autocorrelation |
|---|---|---|---|
| the payload | **5,282** | 4.78 | 0.024 |
| zlib of those same bytes, as a control | **310** | - | 0.005 |

A strong general-purpose compressor produces the control's numbers.  The payload is seventeen
times further from flat than that, so whatever it is, it is not a good compressor's output.

**And there is an 8-byte framing.**  Read at stride 8, **one column in eight holds 79 distinct
values where the other seven hold 238 to 248** - and a shuffled copy of the same bytes gives
248, 244, 245, 246, 252, 252, 247, 249, so the asymmetry is real and not an artifact of the
alphabet.  The phase is fixed: the low-variety column is byte 0 counting from the payload start.

That column is constrained in a specific way:

* its **top bit is clear on 99.8% of records**, where every other column's top bit is set about
  half the time;
* the values it takes come in runs - 0-12, 19-28, 36-44, 52-60, 67- - with regular gaps.

A byte under 128, recurring every eight bytes, taking a restricted set of values, is what a
**flag byte** looks like, or a record tag.  Either way this is a framed private scheme rather
than an opaque blob, and the next attempt should start from that group of eight rather than
from the bit level.

**Not claimed:** that the framing is solved.  The windowed stride-8 agreement is only 0.006 to
0.027 against a 0.011 file mean - far from the 0.363 that settled Terminal Reality's stride - so
the eight bytes are not a plain record array either.  What is established is the negative (not a
strong compressor) and the framing (a constrained byte every eighth), which together say the
door has a handle on it.


## Closed 2026-09-03: the models were `GGG` all along - `GMS` is sound

Two corrections and a reader.

**`GMS` is DSP-ADPCM audio, not a model.**  Billy & Mandy's DOL lists `GmsFormat` beside
`MsaFormat`, `RwfFormat`, `WbaFormat`, `SbaFormat` and `GmdFormat` in its *sound* format
table, the header's two floats (100.0 and 500.0, or 5.0 and 20.0) are 3D-sound min/max
distances, and the "8-byte framing with a constrained first byte" is the DSP-ADPCM frame:
one predictor/scale byte (predictor 0..7 in the high nibble, scale 0..12 in the low - exactly
the runs 0-12, 19-28, 36-44, 52-60 the note measured) and seven bytes of nibbles.  **99.8% of
frames validate at phase 0 and 46-48% at every other phase.**  Entropy 7.7 was ADPCM.  There
was never a codec to crack.

**`GGG` is the model** (`ISVHGGG\0`, big-endian, "uncompressed and quantised" - entropy 5-6
because s16 positions and RGBA8 colours are exactly that).  `gcrip/formats/hvs_ggg.py`:

* header: material names (16 bytes each), then a flat node tree - `u32 mesh count, u32, u32,
  char name[12]` followed by that many 48-byte mesh records - then a geometry header whose
  word at +0x34 carries the **position fraction bits** in its top half and whose seven words
  at +0x44 are the array starts (normals, texcoords, bone index, colours, -, display lists);
* arrays after the header (and after a leading node/instance block of the size at +0x44 in
  the file header - the cars have one, and its bytes were being read as the car body's
  positions before that was found): positions s16 xyz / 2^frac, normals s8 / 64, texcoords
  s16 / 16384, bone index u8, colours RGBA8;
* one GX strip per mesh at a 32-byte boundary, u16 big-endian indices local to the mesh, one
  per attribute in GX order; skinned meshes (attribute word 0x02xx) lead each vertex with a
  u8 matrix index.  The strips are not back to back on multi-node or skinned models, so the
  reader walks to the next boundary whose strip has the record's vertex count.

Textures come through the archive's text databases: `.AGM` binds `Material "X" {
SimpleTextureShader n }` to the n-th name of its `StagedShaderTexture` list, and that name
upper-cased is a `.TPL` member (`gcrip/formats/hvs_agm.py`, `gcrip/plugins/hvs_ggg.py`,
which reads them through the rip's source like the RenderWare plugin does).

**House4.JAM, one level archive: 57 of 69 `GGG` read - 39,022 triangles, 72 textures
bound.**  The level (`MAIN1`, 44 meshes) is a house with a red roof and sky dome; the toy car
is a car with wheels and a grille.

Open on this format: skinned characters (Cerberus, the clowns) export in bone-local space
with some meshes skipped because their strips index past the arrays - the skeleton is in the
`GKA` files (`loop0`, `idle` clips) and the binding is not read; `VISTEST` / `DGATEO` style
files (attribute mask 0x80, position only) are visibility / collision volumes and are
declined; the 0x120-byte stub `GGG`s are not models.

Discs: Billy & Mandy and Kids Next Door (`FSTA` archives).  Charlie and the Chocolate
Factory's `JAM2` archives are a different container and were not checked for `GGG`.
