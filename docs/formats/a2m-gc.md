# The `.gc` resource files - Teen Titans, Monster House, Ed Edd n Eddy, The Ant Bully, Happy Feet - CRACKED

**Five discs, all producing nothing at all**, and no note anywhere on the format.  Found by
censusing what the 204 empty discs actually contain: `.gc` appears on nine discs, six of them
empty, and the five above share one engine.  Happy Feet is the same engine with the files
stored compressed as `.cp`.

    Teen Titans      1,368 .gc   236 MB
    The Ant Bully      732 .gc    97 MB
    Monster House      633 .gc   167 MB
    Ed, Edd n Eddy      96 .gc    74 MB
    Happy Feet         684 .cp    93 MB  (zlib)

Read by `gcrip/formats/a2m_gc.py` + `gcrip/plugins/a2m_gc.py`.

`.as`, `.sbk` and `.str` on the same discs are audio - cutscene streams, sound banks and music.
They are the bulk of the bytes and none of it is geometry, which is worth writing down because
they are the first thing an extension census points at.

## The file

Big-endian throughout.

    +0    u32 version        0x0301081f (Teen Titans) / 0x03020bc2 (Monster House)
    +16   char name[12]      "ppdusk", "lu_ch10"
    +28   char project[16]   "tt06", "mhouse"
    +56   char "Build"
    +64   the type table: 256 slots of 8 bytes
              u32 count
              u32 offset     0xffffffff when the type is absent
    +2112 (0x840) the first payload

The table is exactly 256 slots on both discs sampled and the first data lands at 0x840, so its
length is fixed rather than derived.  **A slot's index is the resource type**, and 22 of the 256
are populated on both files.  Detection is the word `Build` at +56 - inside the 64 bytes
`classify` sniffs, which is what makes it usable at all.

Each populated slot points at `count` entries of eight bytes:

    u32 handle    (type << 24) | (file id << 8) | index
    u32 offset    absolute; 0xfffffffb means the resource has no payload

The handle's top byte repeats the slot index and its middle two bytes are constant per file
(`0670` on `ppdusk.gc`, `3e80` on `lu_ch10.gc`).  Requiring the top byte to match the slot is
what keeps the reader from claiming a file that merely has plausible numbers at +64.

## A resource

    +0    u32 guard      0xabababab or 0
    +4    u32 version    the file's version again
    +8    u32 subtype
    +12   u32 handle     matches the table entry
    +16   char name[32]  "crate_big", "barrel_explosif", "fx_barrel_hit", "proxy:movieplayer"
    +48   16 bytes of 0xef  - a guard
    +64   the payload

Every resource is named, so meshes come out under the artists' own names.  Records inside a
payload are 32-byte aligned and padded with `0xef`.  `ppdusk.gc` holds **972 named resources**
across 22 types, covering 4,780,800 of its 4,792,544 bytes.

## `.cp` is a `.gc` behind a chain of zlib blocks

    repeated:  u32 compressed size, then a zlib stream of exactly that many bytes

Each block inflates to **53,248** bytes bar the last.  `dr_final.cp` is 89 blocks, 2,433,313
stored, 4,712,576 inflated.

**This one fails quietly if read the obvious way.**  Letting each stream end on its own and
starting the next where it stopped skips the four-byte size that sits between them, so only
block one comes back - and that block is a complete, valid `.gc` header: the right magic at
+56, the name `dr_final` at +16, the project `hf` at +28.  Every check passes and the file
contains no meshes.  It reported 53,248 bytes instead of 4,712,576 and looked like a format
that simply had no geometry in it.  There is a test pinning this.

## The geometry

An ordinary **GX indexed triangle strip**.  `gxscan` finds nothing in these files, and not
because the geometry is unusual: the vertex array lives elsewhere in the resource and the
scanner has nothing to point it at.

The mesh header:

    u32 vertex count
    u32 0xffffffff        a sentinel
    u32 vertex array offset
    ... 40 bytes
    u32 display list start
    u32 display list end

The vertex is **56 bytes**, all big-endian:

    +0   f32 x, y, z
    +12  RGBA8 colour        0x5d5d5dff, 0x8f8f8fff - six distinct greys on `barrel`
    +16  f32 nx, ny, nz
    +28  f32 u, v
    +36  f32 1.0, then 16 bytes of zero

The display list is `0x98 | u16 count | count * 8 bytes`, each vertex being **four u16
attribute indices** (position, normal, colour, texcoord - equal on every vertex seen, so the
array is already unified).  The list is padded with zeros to a boundary, so the walk finishes a
few bytes before the declared end rather than exactly on it.

### The header is not at a fixed offset

Reading `barrel`'s offsets as constants finds 11 meshes in 972 resources and mean normal
agreement falls to 0.62.  Each header is found by its own shape instead - the `0xffffffff`
sentinel with a plausible count and array offset either side - and then **confirmed against the
data it points at by four checks that have nothing to do with winding**:

* every stored normal is unit length (mean 0.9999, standard deviation 0.0000);
* the display list walks to its declared end, give or take zero or `0xef` padding;
* every index is inside the vertex count;
* the list references **every** vertex.

On `ppdusk.gc` that finds 49 meshes in 972 resources and never fires on the other 21 types.

### The winding is not consistent - and it looked like failure

Raw, the face normals agree with the stored ones at a mean cosine of **0.41**, with meshes
spread from +1.0 to -0.80.  Read as a precision figure that says "45% of these are real and the
rest are false positives", which is what it was first taken for.

It is not.  The **unsigned** agreement is **0.90 to 1.00 on all 49**, every one has unit
normals with standard deviation 0.0000, and every one uses 100% of its vertices.  They are all
real meshes - `slade_minion_ref`, `sentry_turret_ref`, `w_crate_big_ref` - and the sign is a
per-triangle winding flip, exactly as in Terminal Reality's `_smf`.  Each triangle is flipped
to agree with its own stored normals.

That makes the signed agreement 1.0 by construction, so **the figure worth quoting is the
unsigned one measured before the flip**; the reader returns it per mesh so it cannot be
confused with a post-hoc score.

## The textures - type 34

Every image is one resource of type 34: a **256-byte header** then a GX mip chain.

    +168  u32 width, u32 height     128x128, 64x64, 32x32, 128x256, 128x16
    +248  u32 GX format             14 CMPR (163 of Teen Titans' 185), 6 RGBA8 (22)
    +256  the pixels, level 0 first

**`256 + the whole mip chain == the resource length` is the check**, and it holds on all 185.
The word at +164 looks like a level count and reads `1` on every texture, so it is not one -
the size is what says how many levels are stored, and a texture where no level count fits is
declined rather than decoded from a header read in the wrong place.  Paletted formats are
declined too: nothing has located a palette, so decoding one would invent its colours.

Measured against a shuffled copy of the same pixels, the decodes are **3.3x to 69x smoother**
than noise, and the alpha channel is meaningful rather than flat - `electricbarrel` averages
82, `gizswirl` 30, `crate_big` 255.

## Binding a mesh to its texture

A geometry resource carries a `u32` equal to the texture resource's **handle** - the same word
the type table holds.  74 of Teen Titans' 83 geometry resources contain exactly one, and the
names line up: `barrel` to `ob_barrel`, `barrel_explosif` to `ob_barrelexplosif`,
`doorgarage_ref` to `pd_porte_garage2`, `robot_sentry_drone_ref` to `robot_sentry_drone`.

A resource mentioning several handles is left unbound rather than guessed at, since putting the
wrong picture on a model is worse than shipping it bare.

## Results

| disc | sampled | meshes | triangles | textures | bound |
|---|---|---|---|---|---|
| Teen Titans | `ppdusk.gc`, 1 of 1,368 | 49 | 5,461 | 185 | 32 / 49 |
| Happy Feet | 3 of 684 `.cp` | 30 | 57,483 | 232 | 30 / 30 |
| Ed, Edd n Eddy | 3 of 96 | 46 | 13,422 | 485 | 44 / 46 |
| The Ant Bully | 3 of 732 | 5 | 3,120 | 187 | 4 / 5 |
| Monster House | 3 of 633 | 3 | 1,118 | 188 | 3 / 3 |

These are three files per disc out of hundreds, so the disc totals will be far larger.

## Still open

Nothing blocking: the container, the meshes and the textures all read.  The one loose end is
that a mesh naming more than one texture handle is left unbound (17 of Teen Titans' 49), and
type 24 - a single 1.29 MB resource per level, the environment - has not been looked at.
