# Warthog `WART3.00` `.hog` - SOLVED 2026-09-01

Animaniacs: The Great Edgar Hunt, Looney Tunes: Back in Action, Harry Potter and the Sorcerer's
Stone.  101 archives, **138,326 named members**.  Directory, member framing and codec all read;
`gcrip/plugins/wart_hog.py` is a container plugin and every member now reaches the pipeline.

Measured on the three discs, first archives of each: Animaniacs **4,582 of 4,663** members
(98.3%), Harry Potter **290 of 292** (99.3%), Looney Tunes **857 of 859** (99.8%).

## Member framing

A record's `packed` size counts a **`u32` big-endian prefix holding the length of the packed
stream**, so the stream is `blob[4:4+prefix]` and `prefix + 4 == packed`.  Slicing from the
record offset instead feeds the codec its own length word as a token and decodes nothing - that
alone held the container at 78 members of 8,576.

Two members are stored rather than packed, and they look different:

* `packed == unpacked` - stored, take the bytes as they are.
* `packed == 0` - also stored, and the record's span is its **unpacked** size.  Every member of
  Looney Tunes' level archives is like this.  What says they are stored and not truncated is
  that the offsets chain exactly through the unpacked sizes.

## The codec

Four token forms.  Every match form carries its own literals, emitted **before** the copy, and
the copy is self-referencing, so a length may exceed its offset - that is how runs are encoded.
Operand bytes follow the token, then the literal bytes.

| token | literals | length | offset |
|---|---|---|---|
| `t >= 0xE0` | `((t & 0x1f) + 1) * 4` literal bytes, no match | | |
| `t < 0x80` | `t & 3` | `((t >> 2) & 7) + 3` | `((t & 0x60) << 3 \| b) + 1` |
| `0x80..0xBF` | `a >> 6` | `(t & 0x3f) + 4` | `((a & 0x3f) << 8 \| b) + 1` |
| `0xC0..0xDF` | `t & 3` | `((t & 0x1c) << 6 \| c) + 5` | `(a << 8 \| b) + 1` |

One design, three windows: a short match with a 10-bit window, a longer match with a 14-bit
window, and a long match with an explicit length byte and a full 16-bit window.

## What kept this closed for four sessions, and what opened it

**Every wrong rule was fitted to vectors that could not tell it apart from the right one.**

The low form was recorded as `len = (t >> 2) + 3` and `off = b + 1`.  Both are wrong: the
length is only three bits and **bits 5-6 of the token are the offset's high bits**.  Every
token in the small vectors happens to have those bits clear, so the wrong rule reproduced them
perfectly and looked general.  What exposed it was `34 61` in `frontend_scroll.lvl`, which has
to reach back **354** bytes to copy `Number, ` and gets 98 under `b + 1`, quietly emitting
`r, 0.0000` instead.

The same shape of error hid two more masks, and only **binary** members showed them:

* the run count is **five** bits, not four - `0xF0`-`0xFF` are runs of 68 to 128 bytes.  In text
  members those tokens land only as the final run, where the end of the stream truncates them
  to the right length anyway, so a four-bit mask decodes every text vector exactly.
* the long form's length carries the token's **bits 2-4**.  Text never needed a match over 260
  bytes, so `c + 5` was never contradicted.

Together those two cost **two thirds of a real archive** while all eight text vectors decoded
byte-exact.  A format's own documentation files are the easiest members to test against and the
least representative of what it has to decode.

## What actually settled it

Not an exact-length oracle - that was satisfied by wrong rules for four sessions, exactly as it
was on the Pokemon LZSS.  Three things did:

1. **Reconstructing the plaintext.** `frontend_cog1.lvl` is a templated level script, so its
   full 386 bytes can be written out by hand from the fragments already decoding.  With the
   text known, each token's required length and offset can be read off directly instead of
   searched for - that is how `len = (t & 0x3f) + 4` fell, from `0xbb` needing 63 and `0x3f`
   being the only mask that gives it.  Reconstruction also **found my own error**: the decode
   said `Amend` where I had written `Const`, and the decode was right.
2. **A one-character differential.** `frontend_cog1/2/3.lvl` are 199 packed bytes differing at
   one stream byte, so a correct decoder must give three 386-byte texts differing at exactly
   one character.  Only the right rules do; a plausible-but-wrong decoder cannot.
3. **Thousands of members with declared sizes.** Once the container framing was right, a real
   archive is a 96-way oracle, and it is what turned up the two masks the text could not see.

## The members: `.btga` textures ship

The members are a resource format sharing an 8-byte header (`u32 id`, `u32 kind`), kind 3 =
`.btga`, 10 = `.bmsh`, 1 = `.bskl`, 2 = `.banr`.

**`.btga` is solved** (`gcrip/plugins/wart_btga.py`) - 26 of 26 on Animaniacs' `frontend.hog`.
A 96-byte header, then one GX mip chain and no palette::

    +25  u8   mipmapped flag        +60  u32  width
    +27  u8   format code           +64  u32  height
    +4   u32  kind, 3 = texture     +68  u32  levels
                                    +88  u32  payload bytes, repeated at +92

The size identity is self-proving: the declared payload has to equal both `len(data) - 96` and
the mip chain summed over the declared levels.  That is also what gives the bits per texel -
`0x01` is four and `0x81` is eight - and it excludes `C4`/`C8` outright, since a paletted
format would need room for a palette and there is none.

`0x01` is **CMPR**: smoothness against a shuffled copy of each image's own pixels scores 1.6 to
24.5 over the 21 samples, where `I4` scores 0.99 to 2.3 and sits on the noise floor.

`0x81` is **IA4**, and smoothness cannot say so - `I8` and `IA4` share the 8x4 tile and land
within 0.05 of each other on every sample.  Splitting the byte does say so: under `I8` the low
nibble is the least-significant bits of one ramp and should be near noise, under `IA4` it is
alpha and should be as structured as the intensity.  It scores 1.71 to 4.17 against 1.62 to
4.01 for the high nibble.  The samples that carry that argument are the ones using the full
byte range - `ahud04` at 137 distinct values and `animaniacs_text` at 256 - because on an image
that is mostly `0x00` and `0xff` both readings look structured no matter which is right.

## `.bmsh` meshes ship too

**16 of 16** members on the cached `frontend.hog` sample - **6,672 triangles** with positions
and UVs, against the generic display-list scanner's 504 from 4 files.

A `.bmsh` is the resource header then a **chain of section tables**, one table a sub-mesh:
`u32 count`, `u32 total`, then `count` section sizes, the sections back to back.  Two identities
do all the work of locating them - `sum(size) == total`, and the chain ends **exactly** at the
member's end - so nothing has to trust an offset, and a wrong start runs off the end rather
than quietly succeeding.

Section 0 is GX register state and runtime pointers; one section is a display list, found by
content because its index is not constant; the rest are vertex arrays.  The index stride is
derived, not assumed, and so is the width of **each column**: the skinned meshes index position
and normal with `u16` and the texcoord with `u8` in the same vertex, so their lists tile at
stride 5 and no single width reads them.  Every split of the stride into 1- and 2-byte columns
is tried and scored by how many columns find a home, so a stride that merely tiles loses to one
that explains all of its columns.  A column is matched to an array by requiring
`(max + 1) * element` to equal the section size to within its four-byte padding.  Elements seen are **12** (positions, `f32` x3), **3** (normals, `s8` x3) and
**4** (texcoords, `s16` x2 over 16384).  **Column order is not array order** - on the smaller
meshes column 1 indexes the last array - so the mapping is solved rather than assumed, and a
column matching nothing is the **matrix index** the multi-matrix meshes carry, with values
running to about 250 that index no array at all.

### The check, and what it caught

The header carries a bounding volume - half-extent, centre, radius - and the decoded geometry
has to reproduce it.  It does on **16 of 16**, and in every case **exactly one** candidate
offset matches, to better than 1% of the extent.  That is what confirms the stride and the column
mapping together; a triangle count would show none of it.

It also caught my own error.  Reading the block at a fixed +72 made two meshes look misplaced
by 740 units - but their two sub-meshes agreed with *each other*, which is what said the
geometry was right and the offset was wrong.  Those two use a variant header with the block at
+92, so it is now located by signature: a bounding sphere's radius lies between the largest
half-extent and the box diagonal.

### The bug every format test missed

The first disc run of `wart_bmsh` **failed 5,651 meshes on Animaniacs** and wrote zero
triangles, while all 16 cached members parsed and 12 tests passed.  Two mistakes in the plugin,
neither visible from the format reader:

* `Primitive.material` is an **index** into `scene.materials`, not the material's name.  Passing
  the name raises `ValueError: invalid literal for int()` inside the exporter, once a mesh.
* `Primitive.indices` is **flat**, three entries a triangle - not the `(M, 3)` the reader
  naturally produces.

Both are export-contract mistakes, so no amount of testing the parser finds them.  What finds
them is running `ripcore.gltf.export` on the plugin's own output, which now happens in the
tests: 42 scenes, 0 failures, 6,672 triangles written.

### The guard that threw away every skinned mesh

A section may be **empty**, and rejecting a table that contains a zero size looks like a
sensible sanity check.  It is not: the skinned character meshes carry long runs of zero-length
sections - one table has 48 sections of which 8 are empty - and that guard alone made all three
of them look like a different format with no section table at all.  `sum(size) == total` and
the chain reaching the member's end are the real guards, and they hold with the zeroes in
place.  Dropping the guard and reading per-column index widths took the sample from 13 files
and 1,926 triangles to **16 and 6,672**.

---

# The record below is the pre-solution note, kept for the reasoning


Three discs, 101 archives, **165,704 named members** - 36,156 `.btga` textures, 29,021 `.bmsh`
meshes, 3,622 `.bskl` skeletons, 10,597 `.anm` animations, 5,226 `.lvl` and 3,269 `.mdl`.
`gcrip/formats/wart_hog.py`, big-endian:

    +0   char magic[8]        "WART3.00"
    +8   u32  member count
    +12  u32  name table offset
    +16  u32  file-name section bytes
    +20  u32  directory-name section bytes
    +24  the records, 24 bytes each:
             u32 data offset
             u32 packed size
             u32 unpacked size
             u32 hash
             u32 file name offset    from name table + directory bytes
             u32 directory name offset

The name table is two runs of NUL-terminated strings - the directories first, each ending in a
slash, then the file names - so a member's path is its directory plus its name.  All 101
archives parse.

## The field order is the trap, and contiguity does not catch it

Read as if the records began at +16 rather than +24, **every offset and size still chains
perfectly**: member N ends exactly where member N+1 begins, all the way down every archive.
The two name words merely shift the whole window by eight bytes, so the arithmetic that
normally confirms a table confirms nothing here.

What gives it away is the payload.  Under the wrong order Animaniacs' two `.btga` font
textures unpack to 9,602 bytes and its two `.tnf` metrics files to 131,168; under the right
one both textures are 131,168 and both metrics files are 9,602.  *Contiguity proves the
stride, not the field order* - only the data can.

The directory-bytes word is byte-swapped on some archives: Animaniacs stores 30 as
`00 00 00 1e`, Looney Tunes stores 147 as `93 00 00 00`.  Neither byte order can be trusted, so
the reader accepts the value only if it lands just past a NUL in the name table.

## Tiger Woods is not this format

The cluster was listed as seven discs.  It is three.  The four Tiger Woods discs also carry
`.hog` - 872 of them, more than eight times the rest of the cluster - but they open `CTRL`
followed by `00 00 00 18` and share nothing else with these.  **An extension is not a format**;
this cluster was sized by one.

## The codec - the literal form and the low match form are solved

Two of the three token ranges are cracked and verified against real text rather than against a
length count.

* A member begins with `u32 packed size - 4`, then the stream (160 of 177 checked).
* **`0xE0 | n` is a literal run of `(n + 1) * 4` bytes.**  Four independent anchors agree:
  `e1` gives exactly `model` CRLF `{`, `e3` gives `level` CRLF `{` CRLF TAB `name(`, `e5` that
  plus `{cactus}`, `e6` `ObjectType}, Const, Number, `.
* **A token below `0x80` is a match carrying its own literals**::

      literals = b & 3            emitted BEFORE the match
      length   = (b >> 2) + 3
      offset   = next byte + 1    counted back from the end of the output

  The stream order is token, offset byte, then the literal bytes - but the literals come out
  *first*, and the match copies after them.

`frontend_cog1.lvl` decodes cleanly under this all the way to the first token that is not below
`0x80`, and every step is checkable against the text:

    e5  24 literals            level CRLF { CRLF TAB name({cactus}
    01  lit ')' len 3 off 17   -> CRLF TAB
    e1  8 literals             acount(4
    04  lit -  len 4 off 12    -> ) CRLF TAB
    0d  lit 'p' len 6 off 12   -> count(
    05  lit '0' len 4 off 12   -> ) CRLF TAB
    87  ...                    stops here, at output byte 52

giving `level CRLF { CRLF TAB name({cactus}) CRLF TAB acount(4) CRLF TAB pcount(0) CRLF TAB` -
correct text, matched brackets, real CRLF.

On its own the solved half decodes **44 of 4,663 members outright** - the small ones that never reach a high token - so the value here is the verified grammar, not the yield.

### What is left: the tokens from `0x80` to `0xDF`

Only that one range.  The next bytes are `87 40 0b 73 87 40 0b 74 87 40 0b 62 87 40 0b 6f`,
which is a **four-byte unit repeating with only its last byte changing** - `s`, `t`, `b`, `o` -
and the text it has to produce is known exactly from the pattern already decoded:
`scount(0) CRLF TAB`, `tcount(0) CRLF TAB`, and so on.  So the unit emits one literal letter
and then copies `count(` and `) CRLF TAB` from twelve back, the same offset the low form has
been using.

That is a very tight constraint - a known input of four bytes and a known output of twelve -
and it is where the next attempt should start.  Note the offset cannot come from the byte
after the token: `0x40 + 1` is 65 and the output is only 52 bytes long at that point, so the
`0b` (which is 12, the offset in use) is the more likely offset byte and `0x40` something else.

The high form takes **two operand bytes** - the repeating unit `87 40 0b XX` is four bytes and
`XX` is the literal, leaving two - and with

    lit = (t >> 2) & 3       len = (a >> 4) * 2 + 3       off = b + 1

`frontend_cog1.lvl` produces its full 386 bytes and the first 130 characters are **exactly
right**::

    level CRLF { CRLF TAB name({cactus}) CRLF TAB acount(4) CRLF TAB pcount(0) CRLF TAB
    scount(0) CRLF TAB tcount(0) CRLF TAB bcount(0) CRLF TAB ocount(0) CRLF TAB
    attribute({ObjectType}, Const, Number, 0.000000

with the `s`, `t`, `b`, `o` series coming out in order and no repeated fragment.  For the
`0x87` unit the arithmetic checks exactly: `a = 0x40` gives length 11, `b + 1` gives offset 12,
and copying 11 bytes from 12 back at output 53 lands on index 41, the `c` of the previous
`count(0) CRLF TAB`.

**What is still wrong is the literal count, and only for the tokens above `0x87`.**  The decode
derails at `0x8b`, where `(t >> 2) & 3` claims two literals and takes `e0 4d` - and `0xe0` is a
literal-run token, not text.  The same thing happens at `0x89` (takes `88 40`), `0x9c` (takes
`e1 53 75`) and `0xaf` (takes `ae 8d 00`).  Every one of those wants **zero** literals while
`0x87` wants one:

    token   (t>>2)&3   literals it actually needs
    0x87       1            1
    0x89       2            0
    0x8b       2            0
    0x9c       3            0
    0xaf       3            0

**And the literal count is not the only thing wrong above `0x87`.**  With `len` and `off` held
at the formulas above and the literal count left completely free - brute-forcing all four
values at each of cog1's eight high tokens, 65,536 assignments - **none** produces 386
printable bytes.  So `len = (a>>4)*2+3` and `off = b+1` are right for the `0x87` units and
wrong for the tokens above them: the range has sub-forms rather than one shape with a variable
literal count.

### The sharpest test available: three files one byte apart

`frontend_cog1.lvl`, `cog2` and `cog3` are 199 packed bytes each and differ **at exactly one
stream byte, offset 142** (`31` / `32` / `33` - the `1`/`2`/`3` of their own names).  So any
correct decoder must produce three 386-byte outputs that differ **in exactly one character**.

That is far stronger than "the output is printable", which is what every sweep here has been
scored on and which a badly wrong decode can still satisfy by replaying fragments.  **Use this
first.**  A sweep of 105 candidate length rules for the `a == 0` sub-form - every
`((t >> s) & m) * u + k` and `((b >> s) & m) + k` over the plausible shifts, masks and biases -
produces **no rule that even decodes all three cogs to 386 bytes**, let alone to outputs one
character apart.

### `a == 0` marks a second sub-form, and it carries no literals

The two forced data points are `0x87`, whose `s` must be a literal, and `0x8b`, whose next
byte is `0xe0` and so must be a token.  No bit-field of the token separates them - but their
**first operand does**: `0x87` has `a = 0x40`, `0x8b` has `a = 0x00`.

Treating `a == 0` as a sub-form that takes **no literals** improves every test vector at once,
which is what a real rule does and a lucky one does not:

| member | baseline | with `a == 0` handled |
|---|---|---|
| `frontend_cog1.lvl` | 38.1% | **95.6%** |
| `frontend_scroll.lvl` | 42.5% | 58.1% |
| `frontend_new.lvl` | 5.8% | 12.4% |
| `triggers.txt` | 2.5% | 3.6% |

**Read that table carefully: it is the share of declared output the walk *produced* before
failing, not the share that is correct.**  Every byte produced is printable, but the output is
visibly wrong long before the end - cog1's tail comes out
`)CRLF TAB attrib)CRLF TAB attrib)CRLF TAB attrib`, a fragment replayed over and over, which
is what a match does when its length overruns the cycle it is copying.  The verified-correct
prefix is still the ~130 characters the low form alone produces.

So what `a == 0` buys is a walk that stays in step much further, not a decode.  That is real
evidence the sub-form exists - a wrong rule desynchronises immediately and hits a non-text
byte, and this one does not - but it is not 95% of a working decoder.

The best length seen for the sub-form is `(t & 0x1f) * 2 + 3` with the offset still `b + 1`;
`(b >> 2) + 3` is close behind.  Both are clearly too long: the two `a == 0` tokens before
cog1's failure take lengths 55 and 39, and those are what produce the repeated `attrib`.  The
sub-form's length is the thing to pin next, and it wants to be far shorter.

### An exhaustive negative - the first one here

Every other search on this codec has ended on a deadline, so finding nothing meant little.
This one **finished**.  Holding fixed everything that is verified - the literal runs, the low
form, and for `a != 0` the rule `lit = (t>>2)&3`, `len = (a>>4)*2+3`, `off = b+1` that produces
correct text for the `0x87` units - and leaving the `a == 0` sub-form's **length completely
free** over 1-120 (consistent per `(t, b)`, offset `b + 1`), there is **no assignment at all**
that decodes `frontend_cog1.lvl` to 386 printable bytes.  The search space was exhausted, not
abandoned.

So one of the "verified" pieces is not general.  The candidates, in the order worth testing:

1. the `a != 0` **length** `(a >> 4) * 2 + 3` - it is fitted to a single observation, `a = 0x40`
   giving 11, and every high token in cog1 shares that `a`;
2. the `a != 0` **literal count** `(t >> 2) & 3`;
3. the `a == 0` **offset** `b + 1`.

The low form and the literal runs are not among them: those are confirmed against real text
character by character.

A constraint search also came up empty and is worth recording, because it rules out a whole
family rather than one guess.  Branching only on **distinct `(t, a, b)` triples** - so cog1's
four identical `87 40 0b` units cost one choice, not four - with the literal count free over
0-3, the length free over 3-48, and the offset drawn from every value derivable from `a` and
`b` (`b`, `b+1`, `a`, `a+1`, and the two-byte combinations either way round), pruned on
printable output and the exact 386-byte target, finds **no consistent decoding in seven
minutes** - and a second run widening the lengths to every `a`-derived value up to 400, which
the first capped at 48 and so never tried, finds none either.

**Both searches time out rather than exhaust their space, so this is evidence and not proof.**
What it says is that the offset being a simple function of the two operand bytes - the
assumption every attempt tonight has shared, including the one that got the first 130
characters right - now looks unlikely enough to try elsewhere first: a running or previous
match offset, or a value carried in bits of the token that nothing else uses.

Two other angles came up empty and are recorded so they are not repeated: a search for members
whose first high token leaves a short enough tail to solve exactly finds **none** of 18,730
(the first high token is always far from the end), and the free-length DFS over the whole
stream does not terminate in any reasonable time.

So the literal count is not a fixed bit-field of the token.  Either it comes from somewhere
else, or `0x87` is not a high token at all and its `s`/`t`/`b`/`o` letters arrive by a reading
of `87 40 0b XX` that this one does not have yet.  That single question is what is left.


## 2026-09-01: the literal count comes from `a`, not from the token

The note above ends: *"So the literal count is not a fixed bit-field of the token.  Either it
comes from somewhere else, or `0x87` is not a high token at all."*  It is the first of those,
and the field is **`a >> 6`**.

Two units prove it, and they pull in opposite directions under the old rule:

* `87 40 0b XX` - four of these in a row carrying `s`, `t`, `b`, `o`.  Each must consume
  **one** literal.  The text confirms what they are: the output up to that point ends
  `pcount(0) CRLF TAB`, and these four continue it as `scount(0)`, `tcount(0)`, `bcount(0)`,
  `ocount(0)` - so the match copies `count(0) CRLF TAB`, **eleven characters at offset twelve**,
  which is exactly `len = (a>>4)*2+3` with `a = 0x40` and `off = b+1` with `b = 0x0b`.  Those
  two rules are therefore right, and were never the problem.
* `8b 00 32` at stream 106 must consume **zero** literals.  The byte after it is `0xe0`, which
  has to be read as a literal-run token because the four bytes it introduces are `Mesh`.  Take
  two literals there - which `(t>>2)&3` does for `0x8b` - and `e0 4d` are swallowed as data,
  the run is lost, and everything after it is wrong.

`(t>>2)&3` gives 1 and 2 for those two tokens; `a >> 6` gives 1 and 0.  Only the second is
consistent with the text.

### What it fixes, and what it does not

Holding the verified rules and changing only the literal count:

| literal rule | output | printable | stream consumed |
|---|---|---|---|
| `(t>>2)&3` (old) | 386 / 386 | 380 / 386 | 197 / 199 |
| `a >> 6` | 291 / 386 | **291 / 291** | 198 / 199 |

The old rule's "complete" 386 bytes were never a decode - it emitted six unprintable bytes,
including the `à M` of the swallowed `Mesh` run, and stopped two bytes short of the stream.
The new rule produces **only printable characters** and gets `Mesh` and `frontend_cog1` right,
but stops at 291.

So the remaining error is in neither the literal count, the low form, nor the literal runs.
It is in the length or offset of some high token later than stream 106 - the first place the
new rule diverges is after `Mesh`, where it emits `Nlev({ObjectTy` instead of continuing the
attribute list.

**Do not re-test:** `(t&0x1f)+3` as the length reaches 344 bytes and stays printable, which
looks like progress, but it breaks the four `count` units that are known to be correct -
`scount(0)` comes out as `scount(0) CRLF tscount(0)`.  Printability alone will mislead here;
the `count` run is the check to hold on to.
