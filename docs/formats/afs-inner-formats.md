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
