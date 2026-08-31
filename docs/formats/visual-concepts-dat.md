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
table's end instead, entry 0 lands in the middle of the names.  From the right base every
member begins with the same twelve bytes - `00 01 00 03 02 00 07 01 80 1b 40 00` - which is
what confirms it.

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

## What is blocking it

The `.IFF` payload.  It is dense and bit-packed rather than byte-oriented, and none of the
obvious families reads it:

* zlib in all three window modes, gzip, `refpack`, `prs`, `yaz0`, `yay0`, `lzo`, `avlz` and
  `lzr` all fail;
* a sweep of **plain LZSS** - literal-flag bit either polarity, flag bits taken from either
  end, match words big- or little-endian, offset in either half, 11/12/13 offset bits, match
  length +2 or +3 - reaches the exact output length on **none** of 37 members, at any header
  skip from 0 to 19 bytes;
* LZ4's token format fails at the first token.

The size column makes this cheap to test: every entry states both the stored span and the
length the member should reach, so a candidate decoder is right or it is not - there is no
judgement involved.  That is the thing to keep using.

## Worth knowing before starting

* 1,968 entries in an 827 MB file, so a decoder has to be fast enough for the rip pass, but
  the members are large rather than numerous.
* The uncompressed members (`.DAT`, `.BIN`, `.CDF`, 52 of them) can be extracted **now** -
  they need no codec, and `TEAMS.BIN` / `PLAYERS.BIN` are likely to be readable tables.
* `.IFF` is Visual Concepts' own, not the Amiga chunk format: there is no `FORM` magic and no
  4CC anywhere in a member.
