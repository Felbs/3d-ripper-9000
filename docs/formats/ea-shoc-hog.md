# EA `SHOC` chunk archives - the `.hog` on the four Tiger Woods PGA Tour discs

`gcrip/formats/shoc.py` + `gcrip/plugins/shoc.py`.  Big-endian chunks, `char tag[4]` then
`u32 size` **including** the eight-byte header:

    CTRL   file header
    SHOC   wrapper: 8 bytes of zeros, then one inner chunk
      SHDR   u32 version | char type[4] | u32 index | u32 unpacked size
      Zdat   a zlib stream          (Tiger Woods 06)
      SDAT   raw, behind a 40-byte prefix   (2003, 2004, 2005)
      Rdat   a continuation of either

A member is an `SHDR` and **every data chunk that follows it until the next `SHDR`**.  All 120
sampled archives across the four discs parse.

## Three things that each break the walk on their own

* **The data runs to the end of the SHOC wrapper, not to the end of the `Zdat` chunk.**
  `Zdat`'s own size word falls a few bytes short of its stream, so bounding the inflate by it
  truncates every one: 0 of 170 streams finish, against 140 when the wrapper supplies the
  bound.
* **`SHDR`'s second word is a version, not a byte count**, so its fields start one word into
  the chunk rather than after an 8-byte header.  Reading it as a normal chunk shifts every
  field by four bytes and yields four members from 160 archives instead of 7,433.
* **A member spans several data chunks.**  A `txf` member reaches 1.3 MB across many `Rdat`
  continuations; taking one chunk each truncates all of them.

The `SHDR`'s unpacked size is what confirms the pairing - it equals the assembled length, so a
member that comes out the wrong size is dropped rather than reported.

## What is in them

From 120 archives: `sfx` 4,020, `Cact` 1,650, `Cnet` 1,067, `TEOh` 211, and the large ones -
`ter` 55.5 MB, `txfh` 39.8 MB, `tgd` 17.0 MB, `abnk` 7.9 MB.

The three worth following up, with their magics already identified:

* **`ter` is terrain** and opens `OBG ` with an `ARRA` chunk.
* **`txfh` is a texture group**, opening `TXG ` with a `HEAD` chunk, and it carries real
  names - `tbmulch`, `tbcp1`, `tbdr1`, `tbfw1`, `tbgn1`, `tbpv1` (turf, cart path, bunker...).
* `tgd` opens with two counts and then float data.

`gxscan` finds only a handful of meshes in `ter` (2 or 3 per archive), so the terrain
primitives are inside `OBG`/`ARRA` rather than in GX display lists.  That, and `TXG`, are the
next step.

## The cluster was two formats wearing one extension

The backlog listed a single seven-disc `.hog` cluster.  It is two: **101 Warthog `WART3.00`
archives** on three discs (see [warthog-hog.md](warthog-hog.md)) and **872 of these** on four.
They share an extension and nothing else - these open `CTRL`, those open `WART3.00`.  Sizing a
cluster by extension put 872 archives behind the wrong crack.


## Two things measured on 2026-09-02, so the next attempt does not repeat them

**06's terrain plaintext is already in hand, through the reader that ships.**
`shoc.members()` on 06's `hole.hog` returns `ter` #1 as **5,173,392 bytes** - exactly the size
its `SHDR` declares - opening `OBG  01 04 00 00 ARRA`.  It is a single zlib stream spanning 95
data chunks, and the member reader concatenates them before inflating, which is why it works.

That also means a **block-level** inflate of a `Zdat` block can never work, and its failure is
not evidence of anything: a block starts 44 bytes into its chunk payload, where the stream does
not.  266 of 278 `Zdat` blocks refuse to inflate at any offset from 0 to 47 under any window
setting - and the codec is still zlib.  This was nearly written up as "`Zdat` is not zlib"; the
member reader decoding 162 members including `ter`, `txfh` (967,808) and 134 `sfx` at their
exact declared sizes is what says otherwise.  **Test the layer the format actually uses.**

**2004 Disc 1 is the wrong disc for the known-plaintext pair.**  `hole01.hog` there holds a
`ter` of 3,922,304 bytes in 276 `Rdat` blocks, and **not one 16-byte window of 06's terrain
appears in it** - 0 runs, 0.00% coverage.  It is a different course, not a differently packed
one.  The pairing the note records is 06 against **2005 Disc 1**, which share 58 `.hog` paths;
that is the pair to carry the plaintext, and 2004 will waste the attempt.
