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

## The codec - framing solved, one field left

The earlier note said the payload was "dense and bit-packed rather than byte-oriented" and that
nothing read it.  Both halves of that were wrong, and the sweep that produced them had two
blind spots.  What follows is verified against known plaintext, not fitted.

### Three facts that unlock it

**1. The 4CCs are stored byte-reversed.**  `RTXT` is `TXTR`, `YALP` is `PLAY`, `AUSB` is
`BSUA`.  The earlier note recorded `RTXT` as a tag in its own right and never turned it round.

**2. Every packed member states its own output length.**  A `u32` at **+21** equals
`declared - 16`, on 38 of 45 members sampled.  That is a second oracle beside the table's size
column, and it is inside the member, so it survives any doubt about the table.

**3. Fifty-eight of the 1,916 `.IFF` members are stored uncompressed** - `size == span` - and
four of them are large: `PLAYERS.IFF` (10.2 MB), `LOADM.IFF` (4.5 MB), `CHWG.IFF` (3.5 MB),
`AOSTREET.IFF` (1.2 MB).  **These give the plaintext the compressed members decode to**, which
is what cracks the framing.  `AOSTREET.IFF` reads::

    +0    16 bytes of header
    +16   "RTXT"  u32 17056  u32 17056  u32 0   then 12 zero bytes
    +44   "RTXT"  u32 17     u32 25     then zeros
    +64   "HEAD0000"                          <- the asset name
    ...   pixel data

### The framing

    16 bytes copied to the output verbatim
    then, repeatedly:
        u8 flags
        eight items, bit taken LSB first:
            bit 0 -> literal, one byte
            bit 1 -> match, three bytes  b0 b1 b2
                distance = ((b1 & 0x3f) << 8 | b2) + 1
                length   = b0 + 3            (when b1 >> 6 == 0)

The first flag byte of every member is `0x00`, so the first eight items are literals - and they
are exactly the reversed 4CC and the `u32` size, matching the uncompressed layout byte for
byte.  That is not a fit; it is the same eight bytes in both.

Traced on `AH959.IFF` against the template above, the first four matches are `01 00 03`
(len 4, dist 4), `01 00 03`, `02 00 07` (len 5, dist 8) and `01 80 1b` (dist 28), and the
distances land the copied bytes exactly where `RTXT` and the two size fields belong - the
second chunk's sizes come out **17 and 21**, the same shape as `AOSTREET`'s 17 and 25.

### What is left

**The top two bits of `b1`.**  They are not part of the distance: `01 80 1b` needs distance 28,
and reading those bits into the offset gives 32,796 with only 41 bytes of output to copy from.
The trace requires that match to copy **9** bytes where `b0 + 3` gives 4, so the two bits extend
the length - but not additively.  Solving `length = b0 + 3 + extra[top2]` over `extra` in
0..24 fits at best 10 of 14 small members and 19 of 39 overall, so the bits select a different
op shape (a fourth byte, or a different length unit) rather than adding a constant.

Ruled out along the way, each against the exact-length oracle: flag-byte LZSS with two-byte
matches in every nibble arrangement, both bit orders, both polarities, offset widths 11-14 and
length biases 1-4 (best progress 22% of the output); the same with back-distances *and* with
absolute positions; ring-buffer LZSS in every window size, fill and start position - that one
appears to score 16 of 32 until you notice the ring mask was quietly making impossible
positions legal, which is why the ring parameters made no difference to the score.

**The next step** is to decode `AH959.IFF` against `AOSTREET.IFF`'s chunk template and read the
required length off each `top2 != 0` match directly, rather than sweeping for it - the template
pins the output, so every such match has exactly one right answer.
