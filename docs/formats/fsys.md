# `FSYS` archives - Pokemon Colosseum and Pokemon XD

Two discs whose content is almost entirely inside these: **1,852 archives and 350 MB** on
Colosseum, **2,540 and 1,032 MB** on XD.  Both reported nothing at all, because nothing opened
an `.fsys`.

Big-endian::

    +0    char magic[4]   "FSYS"
    +4    u32 version     0x102 (Colosseum) / 0x201 (XD)
    +8    u32 identifier
    +12   u32 entry count
    +16   u32 flags
    +20   u32 3           how many pointers the table at +24 holds
    +24   u32 -> a three-pointer table
    +32   u32 file length

The three pointers are, in order, the **list of per-entry detail pointers**, the start of the
detail records, and the start of the data.  Two independent sums confirm that reading, on both
versions at once: Colosseum's 157 entries need `96 + 157 * 4 = 724` bytes of pointer list, and
the second pointer is **736** - the same number rounded up to 32.  XD's two entries need
`96 + 8 = 104`, and its second pointer is **112**.  The third pointer equals the first entry's
data offset, and `+32` equals the file length exactly (18,069,472 and 131,180,768).

A detail record - 80 bytes on Colosseum, 112 on XD, so the stride is taken from the pointer
list rather than assumed::

    +0    u32 identifier
    +4    u32 data offset
    +8    u32 **unpacked** size
    +20   u32 **stored** size
    +32   u32 kind
    +36   u32 -> the member's name, NUL-terminated

**+8 is the unpacked size and +20 the stored one, not the other way round.**  On an
uncompressed member the two are equal, so the mistake is invisible on exactly the archive you
would check first - `people_archive.fsys`, where both read 61,743.  It shows up only on a
compressed one, as a "size" larger than the archive containing it.

**Members are named**, which is the point of opening these at all: `people_archive.fsys`
holds `sensei_b1`, `hunter_f_b2`, `warugaki_b3`, `jiji_b_b1` - the game's cast, one
entry each.

A member is stored one of two ways, and the first four bytes say which: an uncompressed member
repeats its own stored size there, and a compressed one begins `LZSS` followed by the
unpacked and stored sizes again.  Anything else is refused, so a mis-read table cannot carve
the archive up at invented offsets.

**Almost everything is compressed**, which is the honest limit on this reader: across the 40
largest archives of each disc, Colosseum has 157 stored members (17 MB) against 2,257 `LZSS`
(143 MB), and XD has none stored at all.  The container is solved; the codec is the gate.

## Results

`people_archive.fsys` yields **157 named members** - `sensei_b1`, `niku_m_b3`,
`hunter_f_b2`, `jiji_b_b1`, `hunter_m_b1`, `warugaki_b3` - the game's cast, one entry
each.  Read by `gcrip/formats/fsys.py` + `gcrip/plugins/fsys.py`.

## The `LZSS` codec - CRACKED

It was the whole of the value here: 2,257 of Colosseum's 2,414 members in the 40 largest
archives, and every one of XD's.

A member's `LZSS` header is the magic, the unpacked size, the stored size and a zero word, then
the stream from +16.  The stream is **Okumura's LZSS**: a flag byte then eight items, bit taken
**LSB first**, a **set** bit meaning a one-byte literal and a clear bit a two-byte match with
twelve bits of window position and four of length, `(b1 & 0x0f) + 3`.  The window is 4 KB and
`r` starts at `4096 - 18`.

**800 members decode to their declared size exactly, 0 failures** - 400 sampled on each disc -
and the outputs open with structured u16 pairs (`00 2a 00 54`, `00 c8 00 96`, `00 54 00 54`:
42x84, 200x150, 84x84).

### Why the first attempt failed, which is the useful part

**Matching the declared output length is far too weak a test.**  Eighty parameter sets satisfy
it, and the four distinct outputs they produce all begin with runs of untouched window fill.
Sweeping against length alone cannot find the answer here and will happily report success.

Two things fixed it:

* **a two-sided oracle** - the decoder must consume the stream to its *final byte* at the same
  moment it reaches the declared length.  Both ends have to line up;
* **re-compression as the ranking** - a correct decode squeezes back down to roughly the ratio
  the file was stored at (0.52 against a stored 0.657), while a wrong one does not.

And one belief had to be abandoned: that the first operation must be a literal, on the grounds
that a match cannot reference an empty window.  **It can, and here it does.** These files open
with sixteen zero bytes, and against a zero-filled window a match is precisely what a good
encoder emits.  That heuristic pointed at the wrong flag polarity and cost the first pass.

`RING_FILL` only shows through where a match reads window nothing has written, which happens in
a file's first few bytes or not at all; `0x00` is used because these files start with zeros
rather than spaces.

## Results

`people_archive.fsys` yields **157 named members**; across the 8 largest archives of each disc
the reader now decompresses **804 members on Colosseum and 1,132 on XD**.  Read by
`gcrip/formats/fsys.py` + `gcrip/plugins/fsys.py`.

## The image members - Colosseum

`gcrip/formats/fsys_tex.py` + `gcrip/plugins/fsys_tex.py`.  A decompressed member is an image
when it opens:

    +0    u16 width
    +2    u16 height
    +4    u8  bits per pixel   0x20 = 32 (GX RGBA8), 0x10 = 16 (RGB5A3)
    +5    u8                   0x01 on every image seen
    +128  GX pixels

**Bits per pixel names the format, not a GX code** - the field holds 32 and 16 where GX would
say 6 and 5 - and `+4` is a **single byte**.  Read as a `u16` it comes out 8,193, matches no
depth, and every image is silently skipped; that cost a pass returning zero textures, and there
is a test on the exact value.

`128 + encoded_size(format, width, height) == the member` is the check.

**1,332 textures from Colosseum's fourteen largest archives**, a median **4.5x** smoother than
a shuffled copy of their own pixels: 64x64 (822), 42x84 `poke_face` portraits (370), 200x150
(88), 84x84 (48).

That is also the proof the `LZSS` codec above is right.  "It decoded to the declared length"
never could have been - eighty wrong parameter sets managed that - but a wrong decompression
cannot yield 1,332 coherent pictures.

## Still open

**XD's members are wrapped, and the wrapper is now known.**  296 of the 1,132 members in its
ten largest archives are:

    +0    u32 the member's own length
    +4    u32 payload bytes
    +8    u32 relocation count
    +12   u32 1
    +32   the payload
    ...   `count` u32 relocation entries, then padding to under 64 bytes

`size == 32 + payload + count * 4` holds on all 296 - `pokeship_0100` is 2,253,031 =
32 + 2,245,772 + 1,802 * 4 + 19.

**Their payloads are not textures.**  They open with `f32` triples (3.69, 64.82, 531.09 on
`pokeship_0100`) and none of the 296 matches the image header that Colosseum's 1,332 use, so
these are models behind a pointer-relocation table rather than pictures.  That is a geometry
job, not a continuation of the texture work.

The other 836 members do not match the wrapper either and have not been characterised.

Colosseum's non-image members - 1,456 in the same sample - are likewise not images and are
left alone.
