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
