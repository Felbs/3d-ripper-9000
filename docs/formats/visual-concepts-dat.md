# Visual Concepts `DAT` - NBA 2K2/2K3, NFL 2K3, NCAA Basketball/Football 2K3

**Five discs, 5.5 GB, and each one is a single file.** These discs have nine files apiece:
`sys/boot.bin`, `sys/bi2.bin`, `sys/fst.bin`, the executable, and one `files/game.dat` holding
the entire game - 827 MB on NBA 2K3, 1,346 MB on NFL 2K3.  All five report zero models and
zero textures because nothing opens that file.

Found by a magic census over the `.dat` and `.bin` files of every disc still producing nothing:
it is by some distance the largest single cluster left.

## Layout

Big-endian.

    +0   char magic[4]   "DAT\1" (NBA 2K3, NFL 2K3) or "DAT\0" (NBA 2K2, NCAA Football 2K3)
    +4   u32, u32 16, u32
    +32  u32 entry count            1,968 on NBA 2K3
    +36  the entry table, 24 bytes an entry:
             u32 a counter that falls by about 15 an entry
             u32 name hash
             u32 kind - 0x01000000 on every `.IFF` member, 0 on the rest
             u32 0
             u32 offset
             u32 size
    ...  the **name list**: `count` NUL-terminated names, "PB00.IFF" to "TEAMS.BIN"
    ...  the members, from the next 32-byte boundary after the name list

**The table starts at 36, not 32.**  Read from 32 the columns look plausible - a size, a
counter, a hash, a flag, a zero, an offset - and the offsets even increase for a while.  What
gives it away is that each entry's "size" turns out to equal the *previous* entry's span: on
the uncompressed members `size == next offset - offset` only once the whole record is rotated
by one field, and then it holds on 38 of the 51 of them.  The word at 32 that looked like the
first entry's size is the entry count.

**The names are there.**  The data region opens with a plain NUL-terminated list of exactly
`count` names - 1,968 of them on NBA 2K3, "PB00.IFF" first and "TEAMS.BIN" last - so members
come out named, not numbered.  The extension split settles what the `kind` word means:
**1,916 names end in `.IFF` and exactly 1,916 entries carry `0x01000000`**, against 27 `.DAT`,
22 `.BIN` and 3 `.CDF`.

**Offsets are relative to the end of the name list, rounded up to 32.**  Measured from the
table's end instead, entry 0 lands in the middle of the names.  Two things confirm the base:
the spans tile the file to the byte, and the uncompressed members then read as clean chunk
files - `BUILD00.DAT` opens with sixteen zero bytes, `RTXT`, two `u32` sizes, a second `RTXT`
and the name `hair0000`.

An earlier draft of this note claimed the base was confirmed by every member starting with the
same twelve bytes, `00 01 00 03 02 00 07 01 80 1b 40 00`.  That was an artifact of a base
thirty-two bytes too high: at the wrong offset several members happened to land on the same
recurring pattern in the packed stream.  It is worth recording because it is exactly the kind
of evidence that feels conclusive - a constant byte string across unrelated members - and was
not.

## The container ships

`gcrip/formats/vc_dat.py` + `gcrip/plugins/vc_dat.py`.  **All five discs tile exactly** - the
member spans account for every byte of `game.dat` on each one, which is the check:

| disc | bytes | members | emitted |
|---|---|---|---|
| NBA 2K3 | 827,434,216 | 1,968 | 1,966 (334 MB) |
| NBA 2K2 | 1,055,456,496 | 1,970 | 1,967 (563 MB) |
| NFL 2K3 | 1,346,729,624 | 2,051 | 2,049 (791 MB) |
| NCAA College Basketball 2K3 | 1,310,804,865 | 2,179 | 2,173 (380 MB) |
| NCAA College Football 2K3 | 1,247,317,608 | 1,212 | 1,210 (760 MB) |

**9,380 members, all named.**  `LINES.BIN` (336 MB of commentary) and `PLAYERS.BIN` (140 MB)
are 477 of NBA 2K3's 827 MB between them and hold neither geometry nor textures, so members
over 32 MB are skipped rather than carried - holding those two would add half a gigabyte to
every worker.

## The codec - solved (2026-09-02, stream semantics settled 2026-09-04)

    16 bytes copied to the output verbatim
    then, until the member's bytes run out:
        u8 flags
        eight items, bit taken LSB first:
            bit 0 -> literal, one byte
            bit 1 -> match, three bytes read as one big-endian 24-bit word:
                        length   = word >> 14           (10 bits)
                        distance = (word & 0x3fff) + 1  (14 bits)

That is the whole thing: a **10:14 split of a 24-bit word**, decoded **to the end of the
input**, not to a target length.  There is no adaptive state.

### Why every earlier attempt stopped in the same place

Read byte by byte, the second byte's top two bits look like a control field sitting beside an
8-bit length in the first byte - and every reading of them *as a control* has to explain nine
members that hit the identical triple `01 c0 1b`, at the identical position, with the identical
distance, and need **different lengths**.  They are not a control.  They are the bottom two
bits of the length, and the length is 10 bits wide.

The note used to record "`b1` is a two-bit control, its low six bits are zero in every match
observed".  That was measured over the first few ops of one member.  Over a whole member `b1`
takes 90-odd values.

### The stream is input-driven - the last riddle, and where "adaptive state" came from

The u32 at +21, long called "the declared output length", **is not a header field at all**.
The stream's first flags byte is `0x00` and its first eight literals are the tag and a u32 -
so +17 is the tag and +21 is the *first record's own size field*, seen through the stream.  A
member may hold several records: `MORPHEDIT.IFF` (span 45,616 against a "declared" 17,056)
decodes to **three** 17,072-byte `RTXT` records that tile to the byte.  Stopping the walk at
+21's value was wrong for every multi-record member, and it produced the five "failures" the
2026-09-02 note reported.

The other three of those five are the second encoder habit: **trailing zero-producing ops are
trimmed from the stored stream.**  `AH743.IFF` ends cleanly 16 zeros short of its record;
`AA743.IFF` ends *inside* a match word - the trim cut at the container's 32-byte alignment and
left the first byte of a `06 00 00` match (24 more zeros, distance 1) dangling.  A cut like
that ends the stream.  The decoder gives the zeros back by padding to the record tiling the
output itself shows.  Up to 31 bytes of slop may also decode *past* the last record - the
encoder compressed its source buffer through the alignment padding - and record walkers never
see it.

The "same bytes, different lengths" contradiction that suggested hidden adaptive state is
fully dissolved: under the wrong op grammar the ops *before* the comparison point consumed the
wrong number of bytes, so the "identical position" was not identical.  The nine members that
carried the contradiction (`AH999`, `MDCLASS`, ...) all decode under the 10:14 split, most of
them into readable plaintext - `aistreet.bin`, `cwdloop.bin`, and runs of the string
`PADDING*` - which the old "no plaintext twin for `AUSB`" note said could never be checked.

### What settles it

All 359 packed members that sit whole inside the first 24 MB of NBA 2K3's `game.dat` - 251
`RTXT` texture members and 108 others (`BSUA`, `AUSB`, `PLAY`, ...):

* **zero decode errors** - no match ever reaches before the start of the output, the check
  that catches a wrong split of the 24-bit word within a handful of ops;
* **every decoded member carries the tag it advertises at +17**;
* **239 of the 251 `RTXT` members tile into complete records exactly** (the other 12 carry
  non-`RTXT` chunks after their first record, `A030.IFF`-style, and tile as far as `RTXT`
  goes); `MORPHEDIT.IFF` and `REF1.IFF` tile as 3 x 17,072 to the byte;
* 301 streams end cleanly between ops, 58 end inside a trimmed match word - both ordinary;
* end to end, **311 of 311 packed `RTXT` members decode and 425 textures come out** of the
  24 MB slice through the shipped `vc_iff` reader (60 members decode but hold `LOADM`-style
  record layouts the reader declines by design - a reader gap, not a codec one).

**The measurement that matters is structure the decode cannot fake.**  Clipping the final copy
to a target - the ordinary way to end an LZ decode - makes any length oracle vacuous, and a
wrong split (`length = ((b0 << 2) | (b1 >> 6)) + 3`) once scored 251 of 251 that way while
producing visible garbage.  That lesson is recorded in `gcrip/oracles.py`; the tiling of whole
record runs, and plaintext like `PADDING*`, are the oracles that replaced it.

`gcrip/formats/vc_pack.py` ships it, with both identities declared, and
`tests/test_vc_pack.py` pins three real members - one per way a real stream ends.

## The textures that need no codec at all

Fifty-eight of NBA 2K3's `.IFF` members are stored as they are, and they are texture banks.
`gcrip/formats/vc_iff.py` + `gcrip/plugins/vc_iff.py` read them, and **971 textures come out**
without touching the codec:

    PLAYERS.IFF   600 records  128x128
    AOSTREET.IFF   72 records  128x128
    CHWG.IFF       53 records  256x256
    BUILD00.DAT    60 records  ... and the rest of the BUILDnn.DAT

A record is one image::

    +0    16 bytes of header
    +16   "RTXT"  u32 size (the record less 16), the same u32 again, then zeros
    +44   "RTXT"  two more sizes
    +64   char name[]     NUL-terminated, padded to 4 - "HEAD0000", "logo030", "0369"
    ...   12 bytes, then u32 width, u32 height
    +176  width * height bytes of 8-bit palette indices
    ...   512 bytes: 256 palette entries, RGB565 big-endian

**`176 + width * height + 512 == record size` is the check.**  It holds on every record of the
three members above and fails on `LOADM.IFF`, whose 102 records are laid out differently - so
those are declined rather than turned into garbage pictures.  Three members on NFL 2K3 carry the
tag and fail the same check; they are declined too.

Two things here are the opposite of what the rest of this project assumes, so they are worth
stating rather than leaving to be rediscovered:

* **The indices are not tiled.**  Reading them row-major is measurably smoother than
  de-swizzling them as GX `C8` - 1.4x on every record tried, in both axes.  Every other
  GameCube texture in gcrip is tiled.
* **The palette is `RGB565`, not `RGB5A3`.**  Decoding with `RGB565` gives an image about twice
  as smooth as `IA8` or `RGB5A3` (47 against 90-115 on `AOSTREET`'s first records), and the
  other two invent an alpha channel the format does not have.

Smoothness against a shuffled copy of the same indices is what settled both: a real picture is
several times smoother than its own pixels in a random order, and that test does not care what
the picture is of.  Measuring it on the *indices* is what does not work - it only agrees when
the palette happens to be ordered, which `AOSTREET`'s is and `CHWG`'s is not.

**The codec has now fallen, and the same reader covers the packed members too** - on the
24 MB verification slice alone it turns 311 packed `RTXT` members into 425 more textures.

## Two field tests that survive the solve

**1. `span >= declared` does not mean a member is stored raw.**  Members are padded, so the
span is an upper bound on the stored bytes, never the stored length.  `LOGOS.CDF` has span 512
against declared 464 and is still packed.  **The reliable test is the tag: a raw member has
its 4CC at +16, a packed one has a `00` at +16 and the tag at +17** - and the `00` is no
accident: it is the stream's first flags byte, eight literals deep, and the tag and "declared"
u32 are simply the first eight bytes of the output read through it.

**2. The nine-member "different lengths" table** that once sat here (`AH999` ... `MDCLASS
exactly 119`) is preserved in spirit as a warning: it was an artifact of a wrong op grammar,
not evidence of adaptive state - a length disagreement at "the same position" means the
positions were never the same.  Four ops of agreement on a template that is mostly zeros is
weak evidence; whole-member record tiling is the real oracle.

## 2026-09-04: the DOL is a bootstrap - the engine is `files/game.img`

Why every scan over `sys/main.dol` failed to find the decompressor: **it is not in there.**
The xref walk over the cached DOL (`vc/nba2k3_main.dol`, 156k instructions) settles it:

- The `[VCLOADER]` strings resolve to an **ELF loader** at `0x8009ac34`: it opens a file by
  name (`0x8009b288`, a wrapper over the SDK `DVDOpen` at `0x80020cdc`), checks `\x7fELF`
  (magic string at `0x800a2060`), requires `e_type == 2` (ET_EXEC), copies every
  `PT_LOAD` program segment to its vaddr, zero-fills the BSS tails, prints
  `[VCLOADER] Jumping to the executable...` and jumps to the entry point (`blrl` at
  `0x8009afa8`).
- Every caller passes the name at `0x800a1d60`: **`game.img`** (with `intro.mov` beside it -
  the DOL also carries the CRI Sofdec movie player, which is most of its bulk).
- The DOL's only three `DVDOpen` call sites are that loader and two in the CRI `gcCi` device
  layer.  Nothing in the DOL parses the `DAT\1` header, walks 24-byte entries, or reads
  `game.dat` at all.

So the boot flow is `main.dol` (bootstrap: intro movie + ELF loader) -> `files/game.img`
(the actual engine, a plain uncompressed ELF on the disc) - and the member decompressor lives
in `game.img`, which is not cached.  **No DOL transcription of the codec is possible from
what is on hand**, and none is needed: the codec is verified empirically at scale above.  If
a disassembly-level confirmation is ever wanted, the file to fetch is `files/game.img` from
any of the five discs (double-read, per the D: misread rule), and the `[VCLOADER]` addresses
above are the front door.

## 2026-09-04 (night 2): the member families, and the MODELS

Every decoded member is a run of **generic records** sharing one frame - `16 bytes of
header, a 4CC, u32 size` (span `size + 16`), the frame the `RTXT` reader already used -
and the 4CCs are all **reversed**: `RTXT`=TXTR, `ENCS`=SCNE, `YALP`=PLAY, `EMAN`=NAME,
`BSUA`=AUSB, `MNAA`=AANM, `ODUA`=AUDO, `TSOR`=ROST, `TNOF`=FONT, `" SSC"`=CSS.  The 370
members whole inside the 24 MB slice group as:

| family | members | what they are |
|---|---|---|
| `RTXT` | 251 | texture banks - already shipped |
| `HTXT` | 60 | the `AA0xx`/`AH0xx` "LOADM-style" members: per-NBA-team uniform art - `HTXT names` + `NAME`, `HTXT numbers` + `NAME` (jersey lettering), and one standard `RTXT unif` record `vc_iff` can already read |
| `YALP` | 34 | `PB*.IFF` playbooks (floats + play scripts, "plb") |
| `ENCS` | 9 | **SCNE scene records - the models** (12 MB: FRONTEND, GAMEDATA, ...) |
| `" SSC"` | 6 | cutscene scripts |
| rest | 10 | AANM (AISTREET, 4.8 MB), ROST, AUDO, FONT, `nSiH/tFiH/uAiH` (LIGHTS.IFF), DRCT, HITX, AUSB |

### SCNE - Maya-exported scenes, cracked (ships as `vc_scene`)

The `ENCS` records are Maya exports - the string tables carry the artists' source paths
(`W:/Artists/NBA2K2/icons/light_pyramid/blue.pix`, `D:/nba2k3/coach/textures/...`),
material names (`lambert2`) and node names, including full skeletons (`rhumerus`,
`rcollar`, `lfingers`...).  On the 24 MB slice, FRONTEND.IFF alone holds the NBA **ball**,
a full **player** (`benplay`), a **referee**, the **basket + backboard + net**, position
icons and the ESPN overlay props; GAMEDATA.IFF holds **coach, cheerleader, cameraman01-04,
crowd, crowdfem, media01-02**.

A record holds node tables, a **position dequantization matrix** (row-major 4x4, per-axis
scale + translation - the player's is diag(0.005976, 0.005955, 0.0012555) - followed by
its exact inverse and the normal matrix diag(1/64)), the string table, and per shape a
vertex array + **GX display lists**:

    vertex, 16 bytes:  [u16 U (s8.8)] [s16 x y z] [s8 nx ny nz] [pad] [u16 0] [u16 V]
    vertex, 14 bytes:  [u16 misc: 1 or a bone id] [u16 U] [u16 V] [s16 x y z] [u16 RGB565]
    display list:      0x20/0x28/0x30 load-indexed-XF (pos mtx -> XF row 0, normal -> 0x400,
                       texture -> 0x78 = GX_TEXMTX0), then 0x9a tristrip (0x80/0x90/0xA0
                       also live): u16 count, then per vertex [pnmtx][texmtx?][p][n][u] -
                       the trailing index fields are always equal (one index per vertex),
                       u8 or u16.

Facts that took a night elsewhere, settled here by oracles:

* **Vertices are model-space** (the Acclaim SKN archetype, not bone-local): every bind-pose
  matrix in the record's palette is the identity, and the raw point cloud is a T-pose.
  The per-vertex `pnmtx` bytes (0/3/6/9 = XF row slots) are matrix-palette skinning for
  animation only.  A blend table (`40 00 40 00` = 0.5/0.5 in 1.15 fixed) sits after the
  vertex array; unresolved, not needed for the static export.
* **The engine repoints the CP array base between draws** - indices stay 8-bit over a
  630-vertex array.  The base lives in the unmapped node graph, so the reader solves it:
  by **normal congruence** (stored normals vs triangle normals; ~0.95 right, ~0.5 wrong)
  for the 16-byte layout, and by **minimum mean-log strip-edge length** with hard filters
  on the misc/uv fields for the 14-byte layout.  Normalizing by bounding box is gameable
  (junk inflates the box); the median alone is blind to a shifted read's seam outliers;
  mean-log is what survived both.
* Oracles that pinned it: `ballhi` = 170 verts at radius 16383.3 +- 0.3, position/normal
  cosine >= 0.9992; GLOBAL.IFF's light pyramid = exactly 4 faces x 3 verts sharing face
  normals, strip `0 1 2 2 3 3 4 5 5 6 6 7 8 8 9 9 a b` reducing to those 4 faces.
* Renders (the gate that matters): the ball is a clean geodesic sphere; the player is a
  complete T-pose with head, hands, feet in all three views; the net is a tapered cylinder
  hanging at rim height; the backboards render as a facing pair at both ends of the court
  with circular rims.

`gcrip/formats/vc_scene.py` + `gcrip/plugins/vc_scene.py` ship it.  The plugin claims
`ENCS` and `HTXT` members (stored or packed), emits one Scene per scene record - named
from the record's NUL-bounded node strings: `GAMEDATA_coach`, `FRONTEND_ball` - and sweeps
the member's record run for inline `RTXT` records (GAMEDATA carries 29 crowd/coach
textures that way; each `AA/AH` member yields its `unif` texture).  On the slice: FRONTEND
13 model scenes + 36 textures, GAMEDATA 13 + 29.  `tests/test_vc_scene.py` pins both
layouts with synthetic fixtures.

## What is still open here

- **Skinned colored-layout characters (the coach class)**: parts with their own arrays
  (head, hands, feet) come out placed right, but the INDEX16 body draws span multiple
  base repointings inside one index window, so a single solved address leaves seam
  spaghetti.  Needs the node graph's real array pointers.  (Attempted per-draw re-solving;
  it traded one artifact for another and was reverted.)
- Mesh->texture binding and the skeleton/skin tables: all in the unmapped node graph.
  Scenes ship with textures unbound.
- The `HTXT`/`NAME` jersey-lettering record layout (the `names`/`numbers` art). The
  members' `unif` RTXT records are already extracted.
- Readers for `PLAY`, `AANM`, `CSS`, `ROST`, `AUDO`, `FONT`, `HiSn/HiFt/HiAu` and friends.
- `vc_pack.is_packed` misses two real cases seen in the slice: a tag with a non-alpha
  character (`" SSC"` fails `isalpha`) and a stream whose first flags byte is not 0x00
  (a match landed in the first eight items - `PB01.IFF`'s head starts `0x80`).  Six
  members in 370.  The scene plugin sidesteps the first for its own tags; the container
  route still emits the raw bytes for the rest.
- The other four discs: same container, same codec, same engine - pipeline work.
