# AFS archives: what is actually inside (GameCube, surveyed 2026-08-30)

31 discs carry `.afs` files, not the 8 the earlier backlog map counted, and about 18 of them
report **zero models and zero textures** today.  The container has been readable for a while
(`gcrip/plugins/afs.py`); the question was always what the members are.

## Most AFS content is media

Sampling members across a dozen discs, the two commonest member magics by far are:

* `80 00 ...` - **CRI ADX audio**;
* `00 00 01 ba` - **MPEG program stream** (video).

That is the whole story for several discs.  R - Racing Evolution's 559 MB `MOVIE.AFS` is 16
MPEG streams; Soul Calibur II's two AFS are three movies and 78 ADX tracks; Viewtiful Joe 2's
ten `st*.afs` are ADX only; Sonic Riders' two are ADX only.  **These discs have no models to
find in their AFS**, which is worth knowing - it stops them being re-probed.

Picking the biggest AFS on a disc is therefore the wrong move: it is usually the soundtrack.

## The data archives

| disc | archive | members | contents |
|---|---|---|---|
| Home Run King | `data.afs` | 372 | **236 `DDS ` texture packs, 69 `XMDL` models**, 14 other |
| Bleach GC | `chr.afs`, `scenario.afs`, `com.afs`, `stg.afs` | 298-1553 | members open `16 00 00 00` |
| Gotcha Force | `afs_data.afs` | 2857 | mixed; one member opens `STIH` |
| Gundam vs Z Gundam | `afs_data.afs` | 2572 | mixed small-integer headers |
| Auto Modellista | `afs01_gu.afs` | 722 | mixed |
| Capcom vs SNK 2 EO | `afs02.afs`, `afs03.afs` | 518, 268 | mixed |
| Digimon World 4 | `ndmw.afs`, `area.afs` | 973, 1382 | mixed |

## CRACKED: Home Run King's texture packs

`gcrip/formats/dds_pack.py` + `gcrip/plugins/dds_pack.py`.

Each `DDS ` member is a **run of concatenated DDS files** - 118 in the first member - with two
GameCube twists: the header is **big-endian** (`dwSize` reads `00 00 00 7c`) and the fourcc is
stored **reversed**, `1TXD` for `DXT1`.

The fourcc is the only DXT1 thing about them.  **The payload is GX `CMPR`** - the same blocks
in GameCube tiling and byte order - and decoding it as linear DXT1 gives noise no matter how the
header or the block words are swapped.  What settles it is the distance between consecutive
files: it equals `gx_texture.encoded_size(CMPR, w, h)` **exactly** for every entry (16,384 for
256x128, 4,096 for 64x128, 2,048 for 64x64), so the DDS header is left-over tooling metadata
around a GameCube texture.

Splitting is on the `DDS ` magic with `dwSize == 124` required in one byte order or the other,
which is what keeps a `DDS ` byte sequence inside pixel data from being read as a header.

First member: 118 textures, all DXT1, sizes 256x128 (17), 256x64 (12), 256x32 (12), 256x256
(12), 256x16 (8), 64x32 (6); 38 are flat (masks or unused).  The richest decodes to a batter
under the *Home Run King* title art.  At 236 members that is on the order of **25,000 textures**
on the disc, which currently reports zero.

## CRACKED: `XMDL` models

`gcrip/formats/xmdl.py` + `gcrip/plugins/xmdl.py`.  A member is a run of self-contained models,
each big-endian::

    char magic[4]    "XMDL"
    char platform[4] "NTGC"        - Nintendo GameCube
    u16 4 | u16 3
    u32 size                       - of the model after this 16-byte header

and the next model begins at `align32(16 + size)`.  Sections are tagged but NOT
length-prefixed - `MDEL` (bounding box), `MATR`, `TXNM`, `GRPV`, `VRTX`, `COLV`, `INDX` - so
walking them by tag alone does not work.

`GRPV` is the directory, eight big-endian `u32`:

    +4  0x0e | +8 flags | +12 vertex count | +16 0
    +20 VRTX offset | +24 0 | +28 INDX offset | +32 index count

Both offsets are relative to **the model start plus 12**.  Getting the count from the wrong
field is what made a first attempt parse only 5 of 32 models - `+8` is a flags word whose top
byte looks like a plausible count for small meshes.

A vertex is **32 bytes of big-endian f32**: position, normal, uv.  The normals prove it - read
this way, every normal in the smallest member comes out at length **1.0000 to four decimals**.
Indices are one byte each, three to a triangle.

Like the Terminal Reality meshes, the triangle list needs tidying: ~15% of triangles repeat a
vertex (zero area) and ~5% are wound inside out.  Both are fixed from the file's own data -
drop the degenerate ones, flip any triangle that disagrees with its stored normals - taking the
cross product in float64, because some models span 2,000 units and it overflows f32.  After
that: **0 degenerate, 0 inverted, mean normal agreement 0.878**.

Whole archive: **69 members -> 6,273 models, 199,226 vertices, 155,356 triangles**, on a disc
that reports zero models today.

## Next

Both halves of Home Run King now read.  Still open in this cluster: binding the `DDS ` textures
to the `XMDL` models (the `TXNM` section names them), and the other data archives - Bleach GC's
`chr.afs` / `scenario.afs` members opening `16 00 00 00`, Gotcha Force's `afs_data.afs`, Gundam
vs Z Gundam's, Auto Modellista's `afs01_gu.afs` and Capcom vs SNK 2's `afs02` / `afs03`.

## The reason every AFS disc read as empty

`gcrip/plugins/afs.py` had `is_container` and `expand` but **no `detect` / `extract` pair**, and
`gcrip.plugins.all_plugins()` only registers a module that has both.  The AFS container was
therefore never in `container_plugins()` at all: **no AFS archive on any of the 31 discs had
ever been expanded**, silently, with no error anywhere.

That is why the whole cluster reported zero.  Adding the no-op pair registers it; the same gap
was found in `gcrip/plugins/lpac.py` (TMNT 2's LPAC packs) and fixed with it.

A regression test now walks every plugin module and asserts that anything carrying
`is_container` + `expand` is actually registered, so the class of bug cannot come back.

End to end afterwards on Home Run King's `data.afs`, sampling one member in 25: **132 scenes,
1,725 triangles, 505 textures**.

### Related: `dds_pack` needed 128 bytes to detect

Caught in the same pass.  `dds_pack.is_pack` validated the whole 128-byte DDS header, but
`detect` is handed only `SNIFF_BYTES` (64), and the fourcc it wanted sits at offset 84.  It
returned False for every real file, so Home Run King's ~25,000 textures would have produced
nothing.  It now checks the magic and `dwSize == 124` in either byte order - eight bytes - and
leaves the rest to `entries()`, which gets the whole file.  This is the third time this
64-byte limit has bitten; every new plugin gets a test at that exact width now.

## Survey, 2026-08-30

Every `.afs` on every disc still producing nothing was opened by reading its index and the
first eight bytes of up to forty members - a few kilobytes a disc, using the `disc_offset`
already stored in each dump's `disc_manifest.json` rather than re-reading the archives.

**Most AFS is audio, and that is now settled rather than assumed.**  The members open
`80 00 .. 03 12 04 ..`, which is CRI `ADX` - copyright offset, encoding type 3, block size 18,
four bits a sample - or `00 00 01 ba`, an MPEG program stream.  On One Piece: Grand Adventure,
One Piece Grand Battle 3, Sonic Riders and the Bleach and Digimon audio archives, that is all
there is.  Do not re-check the big ones.

The archives that hold something else:

| disc | archive | members | first bytes |
|---|---|---|---|
| Bleach GC | `chr.afs` | 298 | `16 00 00 00`, and 3 `gcaxDTPK` sound banks |
| Bleach GC | `scenario.afs` | 1,553 | `16 00 00 00` |
| Bleach GC | `com.afs` | 332 | `16 00 00 00` |
| Bleach GC | `stg.afs` | 55 | `16 00 00 00`, `29 00 00 00` |
| Digimon World 4 | `area.afs` | 1,382 | `bc 12 00 00 a9 00 00 00` |
| Auto Modellista | `afs01_gu.afs` | 722 | `00 00 c0 00 00 00 00 4d` |
| Capcom vs SNK 2 | `afs02.afs` | 518 | `TIM2`, `43 00 00 80` |
| Capcom vs SNK 2 | `afs03.afs` | 268 | `00 00 00 10` |

### Bleach, mapped furthest

Every member of the four Bleach archives opens the same way:

    +0   u32 22            little-endian
    +4   u32 size          the member length minus 12
    +8   u32 0x1c02002d    a tag that recurs at fixed offsets
    ...
    +76  char name[]       "ich_1_cut2"

The tag `2d 00 02 1c` appears fifteen times, at **the same offsets in every member** - 8, 20,
36, 48, 66216, 99640 and so on - whether the member is 133,352 bytes or 141,928.  So the first
100 KB is a fixed layout and only the tail varies, which suggests fixed-size texture or
animation banks rather than a chunked file.

`gxscan` finds no display lists in any member, so whatever geometry is there is not stored as
GX primitives - the same result as Free Radical's `gcr`.

## 2026-09-01: nothing gcrip already reads is hiding in here

Worth doing once and recording, because it bounds the search: members from the five `.afs`
discs that still produce nothing - Digimon World 4, R:Racing Evolution, Bleach, Sonic Riders,
Viewtiful Joe Red Hot Rumble - were offered to **every one of gcrip's 86 non-fallback plugins**
by `detect()`.

**Not one member was claimed by any plugin, on any of the five discs.**

So there is no already-supported format sitting unreached behind the AFS layer, and each of
these discs is a separate inner-format crack rather than a routing problem.  That is the
opposite of what was true for Avatar, where the container was open and the leaves turned out to
be zlib'd textures a small reader could take.

Two details to add to what is already recorded above:

* Digimon World 4's **`ndmw.afs` members are named** - `dng4_47` and so on - and little-endian,
  opening with what read as paired values (`560, 25, 2324, 38, 31312, 750, ...`) where the
  larger ones are inside the member and the smaller ones look like counts.  The note above
  already covers `area.afs`; this is the other archive, 973 members.
* Bleach's `.rg1` carry a recurring word `37 00 02 1c` at +8, +20, +36 and +48 - not a fixed
  stride, so it reads as a separator or type tag between variable-length records rather than a
  field of one. The `16 00 00 00` opening and the names at +76 were already known.

### Bleach: the recurring word is a typed record header (2026-09-01)

It is not one word, it is a **header**::

    u16 type      0x2d and 0x00 inside a chr member; 0x37 in the .rg1
    u16 0x1c02    the magic
    u32 field
    u32 field

That reading is what makes the rest fall out.  The wrapper is `u32 22`, `u32 size` where size is
the member length minus 12, exact on both samples.

**The large records carry a real length** and chain on `at + 12 + size`, where `size` is the
`u32` at +8, exactly::

    66216  type 0x15  size 33412  ->  99640     (observed)
    99640  type 0x15  size 33412  -> 133064     (observed)
    66228  type 0x01  size 33388  ->  99628     (observed, then a 12-byte record to 99640)

**But a flat walk from +8 fails on the first record**, so this is a nested tree and not a chunk
list: the records at 8, 20 and 36 are 12, 16 and 12 bytes, and `(type 1, 4)` at +8 does not
mean a four-byte payload - the next header is twelve bytes later, not sixteen.  Whoever picks
this up needs the per-type header shape before the walk generalises.

A **type 0** record at 19132 introduces about 47 KB of byte data with smooth runs
(`07 07 07 06 06 07 07 07 51 51 47 47 ...`).

### The texture lead, and why it is not shipped

Read as GX `I8`, that region scores 11.7 at 256x128 and 13.2 at 256x176 against a shuffled copy
of its own pixels, where noise scores about 1 and real textures 3-70; width 256 wins at every
height tried, which is the signature of a correct row stride.

**It is still only a lead.**  The region is 47,080 bytes and factors into no clean texture -
256x176 is not a power of two and leaves 2,024 bytes over - so there is no size identity to
confirm any of it, and the Blitz note's lesson applies directly: a smoothness score validates a
layout you already believe and cannot search for one.  Shipping a reader on this evidence would
be guessing.  What it needs is the per-type header shape, which would give the payload's
declared length and turn the guess into an arithmetic check.

The linear (untiled) width sweep is **not** evidence either way: its scores fall monotonically
from width 8, which is an artifact of narrow images having fewer rows, not a peak.

## Bleach `chr.afs`, measured 2026-09-02

`chr.afs` is 192 MB; the first 42 MB expand to 66 members.  The two big ones (2,425,642 and
2,506,360 bytes) are the typed-record files; the rest are smaller and different - `member0002`
onwards open `00 00 00 04` / `00 00 00 03` big-endian with `3f 80 00 00` (1.0f) a few words in,
at power-of-two sizes of 65,536 and 131,072.

The head of `member0000`::

    +0    16 00 00 00      22
    +4    5c 0a 04 00      264,796
    +8    37 00 02 1c      marker      +12: 1        +16: 4
    +20   37 00 02 1c      marker      +24: 0x30004  +28: 21       +32: 66,180
    +36   37 00 02 1c      marker      +40: 1        +44: 66,156
    +48   37 00 02 1c      marker
    +76   "ich_t001"       the asset name

**The per-type header theory does not survive this.**  The note proposed that the recurring word
is `u16 type, u16 0x1c02` and that "the per-type header shape is what is needed next".  All four
markers here carry **the same type**, `0x0037`, and yet the gaps between them are **12, 16, 12** -
so record length is not a function of the type, and shaping headers per type will not produce a
walk.  Whatever selects the length is in the record's own fields, and that is where to look.

Recorded rather than guessed at: none of `at + 12 + size`, `at + 8 + size` or a fixed 12-byte
stride reproduces the observed marker positions.
