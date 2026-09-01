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

## Still open: the `LZSS` codec

It is the whole of the remaining value here - 2,257 of Colosseum's 2,414 members in the
40 largest archives, and every one of XD's.

A member's `LZSS` header is the magic, the unpacked size, the stored size and a zero
word, then the stream from +16.  The unpacked size makes an exact oracle, and **48
parameter sets already reach it** across the usual ring-buffer LZSS space - both bit
orders and polarities, 4 KB and 8 KB windows, fills of 0x00 and 0x20, three
offset/length layouts and two length biases.  They collapse to **four distinct outputs**,
and every one of them starts with ring-fill bytes (`00 00 00 ...` or `20 20 20 ...`),
meaning the first operation copies from a window nothing has written yet.

So the exact-length oracle is not sufficient on its own here, and none of the standard
variants is right.  The next attempt should start from the first few operations of a
stream and require the output to begin with real data, rather than sweeping for a length
match.
