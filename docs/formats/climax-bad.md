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
