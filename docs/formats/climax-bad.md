# Climax `.bad` archives - ATV: Quad Power Racing 2, Hot Wheels World Race, The Italian Job

Each of the three discs is **one `.bad` plus video and audio**, so the archive is the whole
game: 94, 130 and 76 MB.  The open-formats ledger had these as "probably packed, three codecs
already resisted".  The payload is **Okumura's classic ring-buffer LZSS**.

`gcrip/formats/climax_bad.py` + `gcrip/plugins/climax_bad.py`:

* 4096-byte ring, 18-byte maximum match, threshold 2.
* Flag byte read **low bit first**; a set bit is one literal byte, a clear bit a two-byte
  match.
* `position = lo | ((hi & 0xf0) << 4)` - **absolute in the ring, not a distance back** -
  and `length = (hi & 0x0f) + 3`.
* The ring starts **zero-filled**.

## What proves it

Hot Wheels' first stream decodes to **100% printable text** - `// Params for 24_7`,
`// ENGINE DATA`, `NENGINEBINS`, `ENGINETORQUECURVE` and a torque table - and ATV's header
resolves to the clean big-endian sequence 31, 48, 0, 8, 16, 75, 643.  The zero fill is checked
rather than assumed: early matches really do reach into untouched ring, and Okumura's
traditional space fill turns those same header words into runs of `0x20`.

## The old note recorded a build tag that does not exist

`CUBAN 1._02` was read off the raw header without decompressing it.  There is no underscore in
the tag: byte `0x5f` is the **flag byte** that follows the first eight literals, and the text is
`CUBAN 1.02`.  The Italian Job's `BOG 1.01` had the same shape.  *Sampling a compressed header
shows the compressor's control bytes interleaved with the data* - the same trap as reading a
four-byte magic off an embedded filename.

## Where the stream starts

A file is a run of `u32 kind, u32 count` headers, and the stream begins at the first one whose
payload opens with a flag byte of all literals - which every stream must, while the ring is
still empty.  ATV and The Italian Job start at +8; Hot Wheels has a 728-byte uncompressed
block in front, so its stream is at +744, and its tail carries a second one.

**Detection cannot look for the stream.**  `classify` sniffs 64 bytes and Hot Wheels' stream
begins at +744, so a detector that insisted on finding it would refuse the largest of the
three archives.  The extension carries the claim and the full walk does the real check.

## What is inside - still open

The payload is real and named: ATV's carries 643 hits on part names like `frwheelcentre`,
`rlmudguard`, `lfootpeg` and `GEN_quadmud_01`, alongside `POINT 1.00` and `PHYSICS APPLIED`
records.  But the geometry is **not GX display lists**: `gxscan` over 12.7 MB of ATV's payload
finds 10 meshes and 652 triangles, and over Hot Wheels and The Italian Job it finds none at
all.  The inner container - its directory, and whatever holds the vertices - is the next step,
and it is now reachable, which it was not before.

## 2026-09-02: the ATV payload was being truncated, and it does not decode cleanly

Two findings, one certain and one a correction to this note's own claim.

**Certain: the decode hit its cap.**  `decompress` took a flat `limit = 1 << 28`, and ATV's
98,812,344-byte stream produced **exactly 268,435,466 bytes** - the cap plus one match, because
the loop tests the limit before emitting.  The tail of a 268 MB archive was simply lost, with
nothing anywhere to say so.  The limit now scales with the input (`output_limit`, nine bytes out
per byte in, which is the format's own maximum: a flag byte covers eight items and a match costs
two input bytes for up to 18 output), capped at 1 GiB so one member cannot run away with memory.
`hit_limit` lets a caller ask whether a result is complete.

**A correction: "the whole game on each disc is now reachable" does not hold for ATV.**  The
payload's text does not survive.  `mass di` appears 6 times and `ass dis` 5, but **`tribution`
appears 0 times** - the phrase is present in fragments and never completes.  `distribution`,
`engine`, `suspension`, `texture` and `vertex` occur **zero** times in 268 MB.  The longest
"clean" runs in the output are repeated single characters - `----`, `////`, `0000` - which is
ring fill, not text.

What does survive is structure: `CUBAN` 23 times, `BOG 1.01` 114 times, `ROM 1.26` 51.  Literals
and short runs come out right while longer matches do not, which points at the match handling
rather than at the framing.

Ruled out along the way:

* **ring initialisation** - filling the 4096-byte ring with `0x20` instead of `0x00`, the usual
  LZSS convention, changes nothing at all (identical output length, identical word counts);
* five alternative match encodings (absolute, relative-back, byte-swapped, nibble-shifted, and
  a 12-bit split the other way) crossed with lengths of `+2` and `+3` and stream starts of 0 and
  8.  **This test was inconclusive, not negative**: all of them score zero common words on the
  first 2 MB - and so does the shipped variant, because that window is binary.  A rerun needs to
  score against a window that actually holds text.

## The container underneath

`CUBAN 1.02` is the archive magic, with the part count at `+0x28` - **643**, matching the part
names the earlier survey found - and 12-byte records of two big-endian floats from `+0x38`.
Inside it are versioned sub-blocks: `BOG 1.01` (114), `ROM 1.26` (51), `CUBAN 1.02` (23) and
`POINT 1.00`.  That is the directory this note asked for, but reading it is not worth doing
until the payload it points into is trustworthy.

## The framing is right; the match position is not

Decoding ATV's whole stream with the scaled limit settles what the fragmentary text meant.

* **The input is consumed exactly**: 98,812,344 of 98,812,344 bytes, 100.0000%, and the output
  stops on its own at 274,073,929 without reaching the limit.  Landing precisely on the final
  byte.  **This is not evidence of anything**, and two successive versions of this note claimed
  that it was.

  **What consumption actually measures: the loop's termination condition, and nothing else.**
  The walk runs until `i >= n`, so it ends on the last byte whatever it did along the way.
  Measured directly - decoding the same stream from a deliberately *wrong* start offset consumes
  **32.69%** of the input for a 3 MB output budget, and the correct start consumes **32.69%**:
  2,056,605 bytes against 2,056,648.  A wrong start is indistinguishable.

  The first version of this claim said consumption validated the match lengths; it cannot, since
  a match takes two input bytes whatever length it declares.  The second said it validated the
  flag framing; it cannot do that either, for the reason above.  **Exact consumption carries no
  information about correctness in this format.  It should not be cited again.**
* That also measures the truncation the old cap caused: **5,638,473 bytes**, the last 2% of the
  archive, were being silently dropped.

**But exact consumption cannot vindicate the match position**, and this is the point that
matters.  `pos` is only ever used to *read* the ring; the input pointer advances identically
whatever value it takes.  A completely wrong `pos` consumes exactly as much input as a correct
one.  So 100% consumption is evidence about the framing and **no** evidence about `pos`.

* **The tail is 100% printable and meaningless**: `pttept
opt
peoaws
opt
peoaw yt
p
wstt`.
  This matters beyond ATV, because "decodes to 100% printable text" is the evidence this note
  originally gave for Hot Wheels.  **That oracle is weak** - it passes on this garbage - and the
  Hot Wheels result should be re-checked against something stronger before it is relied on.

Taken together: framing right, content wrong, and the one field the consumption check cannot see
is exactly the one the fragmented text implicates.  The match position formula is where to look.

For the record, the ring contents argue the same way from the other side.  At the point where
`mass distri` breaks off, the emitted bytes are `u` and the ring around the referenced
position holds `t u v w x y z` - a clean counting big-endian
`u16` sequence.  That region of the ring is *correct data*, just not the data this match wanted:
the literals that fill the ring are fine and the pointer into it is not.

## Both nibble splits fail, and the search is parked

Decoding ATV's whole stream under each reading of the two operand bytes:

| reading | input consumed | output | tail |
|---|---|---|---|
| shipped - `pos = lo \| (hi & 0xf0) << 4`, `len = (hi & 0x0f) + 3` | 100.0000% | 274,073,929 | gibberish |
| swapped - `pos = lo \| (hi & 0x0f) << 8`, `len = (hi >> 4) + 3` | 100.0000% | 292,237,044 | gibberish |

**Both consume the input exactly**, which is the point made above: consumption is a property of
the flag bytes alone and cannot separate these. Neither tail is readable English, and neither
output contains `distribution` or `Copyright` even once in ~280 MB.

So the swapped split is not the answer either, and I am parking this rather than trying a
seventh variant. What a further attempt needs first is a **trustworthy oracle**, and this note
has now burned through three that looked reasonable and were not:

* *"decodes to 100% printable text"* - passes on gibberish;
* *"the input is consumed exactly"* - true for every variant, by construction;
* *"a part name should not repeat"* - `rlmudguard` appears 186 times, but nothing establishes
  that a 643-part table cannot legitimately list it once per vehicle configuration.

## An oracle that does work: the length of the name chain

The container declares **643** parts, so a correct decode must contain a long run of
back-to-back NUL-terminated identifiers - a name table.  Measured on the shipped decode, over a
4 MB window centred on the first part name, **the longest such chain is 5**, and those five are
`MIT`, `UGR`, `SEP`, `QCN`, `OAL` - three-letter noise, not part names.

It is countable and tied to a number the file declares, so it was worth sweeping against.
**Sixteen operand packings scored 2 to 13 and none produced a name table** - four ways of
splitting the two operand bytes into position and length, crossed with length offsets of +2 and
+3 and ring starts of 4078 and 0.  The best was the shipped packing itself, at 13.

**But this oracle is not safely grounded either, and the sweep is a weak negative rather than a
proof.**  It assumes the 643 names sit in a packed string table.  They may not: the occurrences
of a single part name are spaced irregularly - 5,968 then 3,975 then 1,026 then 8,303 bytes
apart - so the file is neither a packed table nor a fixed-stride record array, and a short chain
may be what a *correct* decode of this container looks like.  Four oracles have now been tried
here and none of them can distinguish a good decode from a bad one.

## What *is* established

One thing decodes verifiably right: **the start**.  The raw stream opens `ff` - an all-literals
flag byte - followed by eight bytes that spell `CUBAN 1.`, and the next flag byte `5f` takes
five more literals giving `02  @`.  That reproduces the container magic `CUBAN 1.02` exactly,
which validates the stream offset, the flag polarity and the literal path together.

So the framing at the start is right, the packing sweep finds nothing better, and no available
oracle can judge the rest.  **This needs a known-plaintext pair before any more decoder work** -
an asset stored both compressed here and uncompressed elsewhere - which is what broke the Tiger
Woods codec open.

The one oracle that would settle it is a **known-plaintext pair**, as on Tiger Woods: some
asset present both compressed here and uncompressed elsewhere on the disc. That is the next
thing to look for, before any more decoder variants.

## The decoder is compiled now (2026-09-02)

One of the two reasons this codec was parked was cost: each full decode of the 98.8 MB stream
took about a minute in a Python loop, so testing a decoder variant against real data was a
coffee break and sweeping sixteen of them was a morning.

LZ decoding is **inherently serial** - every match copies from output the decoder has just
produced - so there is nothing here for threads or a GPU to do, whatever hardware is available.
What it does respond to is compilation.  The ring-buffer walk is now factored into
`_decompress_core` and JIT-compiled with numba when it is installed, with the pure-Python walk
kept as the reference implementation and used for inputs below 64 KB.

Measured on 6.3 MB of the real ATV stream: **3.53 s to 0.08 s, 45x**, and byte-identical.
Extrapolated to the whole file that is **55 seconds down to 1.2**.

The tests compare the compiled path against the reference byte for byte on five random inputs,
at the small-input boundary, under the output limit, and with numba forced off - because a
faster decoder that disagrees with the reference is worse than no decoder at all.

**This removes the cost obstacle, not the oracle one.**  The codec is still parked on the harder
problem: four oracles have been tried and none can tell a good decode from a bad one.  What has
changed is that the *proven* oracle is now affordable - `gcrip/knownplain.py` against a full
decode takes seconds, so the next attempt should look for a Climax asset stored raw somewhere in
the library rather than guessing at operand encodings.


## Settled from the DOL (2026-09-03): a block a member, and the `.bah` names them

Hot Wheels ships `HotwheelsFCDntsc.map`, and it fits `sys/main.dol`.  `cLZSS::Decompress(char*
src, char* dst)` reads `u32 kind, u32 count` and either copies `count` bytes (kind 0) or zeroes
the 4113-byte ring, resets the decoder state and calls `cLZSS::read_data` until exactly
`count` bytes are out.  The ring walk is what this note had all along - flag byte low bit
first, `pos = lo | ((hi & 0xf0) << 4)` absolute in the ring, `len = (hi & 0x0f) + 3`, ring
index from 4078, zero fill.  **The framing was the bug**: the archive is not a stream, it is
one block per file, and running the decoder past the first block's `count` fed the next
block's header in as compressed data.  That is precisely where "mass di" stopped completing
into "distribution".  None of the oracles could see it because every one of them judged the
ring walk, which was right.

Decoded a block at a time, ATV's first 6 MB are **746 named members that all inflate to the
size the directory declares**; blocks follow each other 4-byte aligned.

The directory is `harchive.bah` / `ATV.bah` / `Archive.bah` beside the `.bad` (`Bark 1.06`,
`cFile::LoadArchiveHeader` / `LoadArchiveDir`): from +12, a tree of `u32 name length, u32
files, u32 subdirectories, u32`, the name, per file `u32 name length, u32 offset, u32 stored
bytes, u32 size, u32 hash` and the name, then the subdirectories.  Hot Wheels: 6,796 files -
3,575 `.bog`, 1,282 `.rom`, 21 `.row` tracks, 21 `.kdt`, 21 `.nin`; ATV: 2,113 - 983 `.bog`,
380 `.rom`, 144 `.cuban` (the animations, not models), 19 `.row`; The Italian Job: 2,591.

### `.bog` textures - `cBogFile::Load`, `BlimeyToGX`

`BOG 1.01` (ATV, Italian Job) is a 40-byte header, `BOG 1.02` (Hot Wheels) 56: magic, u32
format, width, height, mip levels, 1, image bytes.  `BlimeyToGX` maps the format: 2/8 RGB5A3,
4 RGB565, 0x10/0x20/0x200/0x8000 RGBA8, 0x40 C8, 0x80 C4, 0x100/0x800/0x2000/0x4000 CMPR.  C8
and C4 carry a 256 / 16 entry ARGB8888 palette before the tiles.  `24_7.bog` is the Street
Breed livery; ATV's `Tpage2ATC` the quad's dragon decal.

### `.rom` models - `cModelFile::Init`, `cModelMeshFile::Init`

The file is the runtime image.  Counts at +12: materials (140-byte records at +0x48, the
`.bog` stem in the first 16 bytes), B (124), attachment points (44: `frwheelcentre` + xyz),
D (104), E (32), meshes; min/max patch steps at +36; bounds at +48.  Each mesh: `u32 flags,
i32 material, u32 x3, u32 triangles, patches, C, vertices, u32 x3` (0x30 in 1.26, 0x34 in
1.27 - ATV's DOL says 0x30, Hot Wheels' 0x34), then u32 triangle triples, 672-byte bicubic
Bezier patches (12 bytes, f32 x[16], y[16], z[16] control points, six more zero arrays), C
u32s and 56-byte vertices (f32 position, normal, uv, uv2, four words).  The ATV body walks
to its last byte: 12 meshes, 1,156 triangles with the 21 patches tessellated 4x4, normal
agreement 0.93, a quad with seat, fenders and pegs.
