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

## `.TEX` textures - CRACKED

`gcrip/formats/tr_tex.py` + `gcrip/plugins/tr_tex.py`.  Short little-endian header, then GX
pixels:

    u32 version   2 (BloodRayne) / 3 (Blowout)
    u32 format
    u32 width
    u32 height
    u32 [2]       zero
    u32           version 3 only, also zero

**The header is 24 bytes in version 2 and 28 in version 3.**  That is the only trap in the
format: get it wrong and the pixels shift by four bytes and every texture decodes to noise -
which is exactly what happened on the first pass over BloodRayne (0 of 600 decoded) while
Blowout was already at 787/787.

The format word is Terminal Reality's own, not a GX code, but the payload underneath is
straight GX, and the bits-per-pixel arithmetic identifies each one:

| code | n | bpp | layout |
|---|---|---|---|
| 11 | 4,303 | exactly 4.000 at every size | GX `CMPR`, no palette, no mips |
| 19 | 169 | 8 bpp + 512 bytes (9.000 at 64x64, 8.250 at 128x128, 8.062 at 256x256) | 256-entry `RGB5A3` palette FIRST, then GX `C8` indices |

Verified by eye: Blowout `AIRLOCK_BASIC_WALL12` is a clean crate, `ART/123.TEX` decodes to the
digits "123", and BloodRayne's walls come out as sharp concrete.  Coverage: **Blowout 787/787,
BloodRayne 3,685/3,785 (97%)**.

Still open (100 BloodRayne textures, none on Blowout): code 1 (1 texture, 9.5 bpp) and code 8
(25; 8.125 / 8.5 / 10.0 bpp) are paletted with a 256-byte palette whose entry count is not
fixed; code 2 (64; 16.02-17.5 bpp) is 16 bpp plus a variable tail that decodes as neither
`RGB5A3` nor `RGB565`; code 3 (10; exactly 32.0 bpp) is 32 bpp but not GX `RGBA8` - decoding it
as one gives vertical stripes, so the tiling differs.

## `.PKG` packages - CRACKED

`gcrip/formats/tr_pkg.py` + `gcrip/plugins/tr_pkg.py`.  The POD holds the game's files; the
`.PKG` inside holds its ASSETS, as a flat chain of named chunks with no directory:

    char magic[4]  "adoY"   - "Yoda" stored back to front
    char tag[4]             - also reversed: "xet1" is 1tex, "fms_" is _smf
    u32  size               - payload only, header is 76 bytes
    char name[64]           - NUL-padded: "WHITE.TIF", "SHELL_MG.SMF", "HERO.SKL"
    u8   payload[size]

The chain ends with a zero-length `oMoN` chunk - "NoMo", no more.  Every chunk carries its own
length, so the walk either lands exactly on the terminator or the file is not a package: the
format verifies itself.  It does verify - 18 of 18 sampled packages across the three discs
walked clean to their final byte (Blowout `GCB_11_CREDITS.PKG` 189 chunks,
BloodRayne `GC_BOILERROOM.PKG` 59, RoadKill `GC_UI.PKG` 40).

| stored | reads | contents |
|---|---|---|
| `xet1` | 1tex | a texture in the `.TEX` format above - 3,199 of 3,262 sampled decode |
| `fms_` | _smf | static mesh (389 sampled) |
| `mfd_` | _dfm | deformable / skinned mesh (53) |
| `lks_` | _skl | skeleton - the payload names bones, `Bip01 Pelvis` (59) |
| `lpms` | smpl | audio sample, `GCA1` |
| `fedv` | vdef | video (RoadKill) |
| `oMoN` | NoMo | end of file, zero length |

Chunk names are the artists' ORIGINAL file names, which is the key to binding: a level's
`.BST` asks for `airlock_hull_001.tif` and the package carries exactly that name.

## `.BST` level layout (probe, not yet decoded)

`.BST` is the SET file - the level's layout, not its geometry.  Blowout's
`11_CREDITS.BST` (156 KB) is: a small header (`u32 30`, then a float), a run of `0x01` bytes,
a `u32` texture count (12) at 0x214, then **356-byte texture records** each holding a `.tif`
name at +0x0c, and then **92-byte object records** each starting with a 32-byte name
(`credits_shaft22`) followed by three `u32` and a transform.  770 strings in the file, and the
mesh names repeat - these are instances placed in the room, referring to meshes that live in
the matching `.PKG`.  Decoding the `_smf` chunk is therefore the next step, and the `.BST`
after it, to place the instances.

## `_smf` static meshes - CRACKED (version 7 / Blowout)

`gcrip/formats/tr_smf.py` + `gcrip/plugins/tr_smf.py`.  The chunk payload is little-endian
bookkeeping (`u32 version`, `u32 material count`, then 360-byte material records from 0x24,
each starting with the artist's `.tif` name) wrapped around big-endian GX data.

**The geometry is a GX display list with the vertices written INLINE**, not pulled from indexed
arrays - which is why scanning for the usual `0x98` triangle-strip opcode finds nothing.  Every
list seen draws QUADS: opcode `0x84` = `0x80 | prim | vat 4`.  A list is
`u8 opcode | u16 vertex count | count * 13 bytes`, and the 13-byte vertex is:

| bytes | field | scale |
|---|---|---|
| 0-5 | position, 3 x big-endian s16 | `* 2^-8` |
| 6-8 | normal, 3 x s8 | `/128` |
| 9-12 | uv, 2 x big-endian s16 | `* 2^-8` |

The `2^-8` scale is proven, not guessed: decoding `WEAP_MACHINEGUN.SMF` that way reproduces the
bounding box stored beside the mesh to within 0.004 (pure quantisation), while `2^-7` and
`2^-9` are out by 1.2 and 2.3.  `bullet.smf` comes back as
(-0.031, 0, -0.031)..(0.031, 0.320, 0.004) against a stored
(-0.03125, 0, -0.03125)..(0.03125, 0.3203, 0.0039).

Lists are found by the eight-byte big-endian preamble `00000008 00000001` (version 7 puts
`00000007` in front of that too), then zero padding, then the opcode.  Walking with a 13-byte
vertex lands exactly on the next preamble: all 42 lists in the 25 meshes of
`GCB_11_CREDITS.PKG` walk clean.

### Two corrections the file pays for itself

Quads are also how the engine writes single triangles - it repeats a vertex - and the quads
are NOT consistently wound.  Raw, that gives 7% zero-area triangles and 10% inside out.  Both
are fixed from data already in the file: drop the degenerate ones, and flip any triangle whose
winding disagrees with its own stored normals.  Result on Blowout: 4,044 -> **3,761 triangles,
0 degenerate, mean normal agreement 0.971, none inverted** (from 0.770 / 10% inverted).

### Version 4 (BloodRayne) - ALSO CRACKED

Same `0x84` quad lists behind the same preamble, but a wider vertex - 16 bytes, all
big-endian - and a single texture name at 0x6c instead of 360-byte records:

| bytes | field | scale |
|---|---|---|
| 0-5 | position, 3 x s16 | `* 2^-15` |
| 6-11 | normal, 3 x s16 | `/ 16384` (Q1.14) |
| 12-15 | uv, 2 x u16 | `/ 256` |

Found by profiling the eight 16-bit columns of the vertex: three of them run to exactly
+/-16384, which is Q1.14, and they come out unit length (0.949 mean) - that is the normal.
With positions in columns 0-2 the normals agree with the geometry at **0.974 mean cosine,
99.7% within 0.7, none inverted**.

**The position scale had no anchor inside the file** - version 4 stores no bounding box.  It
has one outside: both games ship a `bullet.smf`, and BloodRayne's spans 10,496 units, which at
`2^-15` is 0.3203 - the exact length Blowout's stored bounding box gives for its own bullet.
The rest fall in line (missile 0.86, `tatermasher` 1.18, against Blowout's 1.98 machine gun).

Version 4 pads with `F00DBAAD` and carries a `kfmp1` marker where version 7 keeps its material
records.  Both versions now export: Blowout's credits package 25 meshes / 3,761 triangles,
BloodRayne's boiler room 6 meshes / 367 triangles, all six textured.

## `_smf` version 6 (RoadKill) - CRACKED

RoadKill's meshes carry the tag `fmsl` (kind `lsmf`) rather than `fms_`, but their names still
end `.SMF`, so only the version stopped them.  Version 6 is the **indexed** form of the same
13-byte vertex versions 4 and 7 use - no display list at all:

    <bounding box: 6 x f32>
    u32 2 | u32 block size | u32 | u32 vertex count | u32 triangle count
    ... vertex array, 13 bytes each (s16 position, s8 normal, s16 uv, all big-endian)
    ... index list, 3 x big-endian u16 per triangle

Two traps.  The object header is **not 4-byte aligned** to the start of the chunk (the first
one in `JSCATTERGN.SMF` sits at 0x2e6), so a scan stepping 4 walks straight past every mesh -
step 2.  And the block size does not land on the index list: the array actually runs to the end
of the chunk, four bytes past `header + 20 + size`.  Rather than trust either, the reader scans
the ~276 bytes after the header for the vertex start and keeps whichever candidate makes the
stored normals agree with the geometry - the same self-check the rest of the format uses.

### The position scale is per mesh

Unlike version 7's fixed `2^-8`, version 6 picks a power of two per mesh to use the s16 range,
and the bounding box stored immediately before the object header says which: the observed
exponents are 8, 12, 13, 14 and 15.  Snapping `log2(raw span / bbox span)` to the nearest
integer reproduces **all six bounding-box components of all 34 meshes with zero error**.  Take
only the axes with real extent when doing it - a ground plane is flat on one axis and would
otherwise divide by zero.

Result on `GC_DM11.PKG`: **35 meshes, 3,122 triangles, mean normal agreement 0.977, 100% within
0.7, none inverted**, 34 of 35 texture-bound.  35-43 meshes per package across ~15 packages, so
roughly 500 on the disc.

## `_dfm` deformable meshes - structure mapped, vertex layout still unknown

Blowout's `kane.dfm` (version 5, 72 KB) names `HERO.SKL` at offset 28, then:

* **28 part records of 60 bytes** from offset 108: a 30-byte name (`rhand`, `rshin`,
  `torsobottom`, `head`, `lforearm`, ...), a `u16` **bone index** (20, 5, 19 - all inside the
  skeleton's 29 bones), a `u16`, and six f32 that are a bounding box.  One bone per part means
  these are **rigidly segmented characters, not smooth skins**;
* 360-byte material records like version 7's, two names each (`kane.TIF`, `kane_glossmap.TIF`);
* **46 geometry records of 36 bytes** at 0xee4:
  `u32 2 | u32 size | u32 4 | u32 vertices | u32 triangles | u32 29 | u32 2 | u32 index | -1`.
  The `29` is the skeleton's bone count and the eighth field counts 1, 2, 3, ... The blocks
  follow the table in order and their sizes sum to 67,104, landing on the end of the file from
  0x155c - so the geometry is laid out exactly as the table says.

Size arithmetic points at a **20-byte vertex**: `size - vertices * 20 - triangles * 6` leaves
14 to 32 bytes of alignment padding on every record, whereas 16, 24 and 32 do not come close.
The index list is big-endian `u16`, as in version 6.

**The vertex layout itself is still unknown, and the obvious searches are worthless here.**
Fitting stride, position offset and normal offset by normal agreement returns fits at 0.989 and
even 0.999 - all of them false.  Every one has an axis balance of 0.0039, i.e. one "position"
column spans 0-255 while the others span a full s16, so the point set is nearly planar, every
face normal points the same way, and the metric saturates.  With a non-degeneracy guard
(smallest axis extent at least 5% of the largest) the best s16 fit falls to 0.577, and no f32
layout fits at any stride from 24 to 40 in either byte order.

Lesson worth keeping: **normal agreement validates a layout you already believe, but it cannot
search for one on its own** - a planar mis-read beats the real answer.  Version 6 was safe from
this because its scale was cross-checked against the stored bounding boxes, an independent test
that reproduced all six components of all 34 meshes exactly.

### Second attempt: the bounding boxes do not rescue it either

The part records each carry their own bounding box, so there is an anchor that planarity cannot
fake - the ratio of decoded span to box span has to be the SAME on all three axes for a correct
layout.  Two forms of that test were run and both come back empty:

* per block, against each of the 28 part boxes, over strides 16-32, both byte orders and every
  even position offset - **no candidate** gets the three axis ratios within 2% of each other;
* globally, the union of all 46 decoded blocks against the union of the 28 part boxes
  (model span 1.801 x 2.408 x 1.130, which is a sensible character height next to Blowout's
  1.99-unit machine gun) - **no candidate** within 5%.

Blocks outnumber parts 46 to 28, so a block is a fragment of a part and a per-block span is
expected to be smaller than its part's box; that is why the global union test was tried too.
Both failing together suggests the vertices are in **bone-local space** rather than model
space, which would break any comparison against a model-space box, and/or that the 20-byte
vertex is packed rather than a plain array of s16 or f32 fields.  Direct inspection supports
the second reading: the blocks have a clear 20-byte cadence with a byte that is always zero at
+4 and a recurring `04 00` at +3, but the leading twelve bytes are not plausible f32 in either
byte order (`3700b404` is 7.6e-6 big-endian, denormal little-endian).

Two sessions have gone into `_dfm` without a decode.  It is parked here with everything known
written down; the remaining cluster work (Blitz `.gcp`, AFS inner formats) is better value.

### The bone-local hypothesis is still untested, and here is what it would need

The note above proposes bone-local vertices as the reason both box tests fail, but that was
never actually *tested* - only offered as an explanation.  Testing it needs bind transforms to
push the vertices into model space, and `HERO.SKL` does not obviously carry them: the 29 bone
records are **not fixed-layout**.  Names sit on a 36-byte cadence, but the numeric fields do
not line up beneath them - bone 0 has a float in its third word, bone 1 in its second, bone 2
in its first - so a fixed name field is the wrong reading and the record is something else.
Anyone resuming this should settle the bone record before attempting the transform.

## `.SKL` is a skeleton **and an animation bank** (2026-09-01)

The note above records only that the payload "names bones".  It carries far more::

    +0     u32  version, 2
    +4     u32  bone count, 29
    +8     the bone records, on a 36-byte cadence (layout unsettled, see above)
    +1052  u32  animation count, 32
    +1056  the clip names, a 30-byte stride: STAND_DEFAULT, STAND_CHECK_HEADSET,
           STAND_AMBIENT_1..9, GETUP_FRONT, GETUP_BACK, ACTIVATE_LEFT, ACTIVATE_RIGHT,
           HURT_FRONT, HURT_BACK, STRAFE_LEFT, STRAFE_RIGHT, ...
    +2016  the animation payload, 152,960 bytes - 4,780 a clip on average

The payload opens `u32 34` then the clip's own lowercase name (`standdefault`), so each clip
repeats its name in a second form.  **`HERO.SKL` is 99% animation by weight** - 152,960 of its
154,976 bytes - which is worth knowing before anyone spends another session treating it as a
skeleton file.  It also means Blowout's character animation is locatable even while `_dfm`
geometry is not.


## `.SMB` binary models (4x4 Evo 2) - CRACKED from `4x4.elf` (2026-09-03)

`gcrip/formats/tr_smb.py` + `gcrip/plugins/tr_smb.py`.  4x4 Evo 2 keeps no `.PKG`: its 1,113
models are `MODELS/*.SMB` in `GCMODEL.POD`, and the disc had yielded 11 models.  The shipped
`4x4.elf` symtab names the loader: `C3DModel::loadBinary` reads `u32 1, parts, flag, f32 50.0`,
then per part a 32-byte name (0xCD fill), `u32 flag`, `u32 vertices, frames, triangles`, 172
bytes of material (the `.TIF` / `.RAW` name 32 bytes in), and either

* `frames == 1`: a `CRenderPacket` - `u32 2, payload, kind, vertices, triangles, u32, u32` and
  the payload: kind 1 is the **32-byte `SGCPacketHeader`** - `bytes, bytes + 4, 32, 0, position
  fraction bits, normal fraction bits, uv fraction bits, kind` - followed by a GX `0x94`
  triangle list of 16-byte vertices (s16 position / 2^10, s16 normal / 2^15, s16 uv / 2^8).
  The `_smf` reader's "`00000008 00000001` preamble" is this header's last two words (uv bits
  8, kind 1), which `setVertexFormat` feeds to `GXSetVtxAttrFmt`; the reader now takes the
  bits from the header on every game (BloodRayne's `_smf` switch between 14 and 15 normal
  bits per mesh).  A bounding box (6 f32) follows the payload.
* `frames > 1`: `frames x vertices` 32-byte `SVertex` records (f32 position, normal, uv, all
  little-endian) then `triangles x 3` u16 - keyframe-animated props; frame 0 ships.

The Statue of Liberty (`!STATUE.SMB`) comes out at 1,167 triangles, torch and tablet, normal
agreement 0.94; `1BFOOT.SMB` is 31 frames of 825 vertices, every index inside.  The `.RAW`
textures are the `.TEX` layout and `tr_tex` now claims them.
