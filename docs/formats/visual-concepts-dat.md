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

## The codec - solved (2026-09-02)

    16 bytes copied to the output verbatim
    then, repeatedly:
        u8 flags
        eight items, bit taken LSB first:
            bit 0 -> literal, one byte
            bit 1 -> match, three bytes read as one big-endian 24-bit word:
                        length   = word >> 14           (10 bits)
                        distance = (word & 0x3fff) + 1  (14 bits)

That is the whole thing: a **10:14 split of a 24-bit word**.

### Why every earlier attempt stopped in the same place

Read byte by byte, the second byte's top two bits look like a control field sitting beside an
8-bit length in the first byte - and every reading of them *as a control* has to explain nine
members that hit the identical triple `01 c0 1b`, at the identical position, with the identical
distance, and need **different lengths**.  They are not a control.  They are the bottom two
bits of the length, and the length is 10 bits wide.

The note used to record "`b1` is a two-bit control, its low six bits are zero in every match
observed".  That was measured over the first few ops of one member.  Over a whole member `b1`
takes 90-odd values.

### What settles it

The 251 packed members in the first 24 MB of NBA 2K3's `game.dat`, each of which states its own
output length at +21:

* **246 of 251 arrive at that length exactly** - the walk is not stopped there, it ends there -
  and the two that fall short and three that overrun by sixteen bytes are reported, not hidden.
* **All 246 then carry `RTXT` at +16 and the nested `RTXT` at +44**, the header the uncompressed
  members show, and read back as named textures: `unif`, `office_photos`, `coachface`, `uni600`.
* The walk consumes 90.4% of the stored span; the remainder is the member's padding.

**The measurement that matters is that the decoder *arrives* at the declared length.**  Clipping
the final copy to the target - the ordinary way to end an LZ decode - makes the length oracle
vacuous, and a wrong split (`length = ((b0 << 2) | (b1 >> 6)) + 3`) scored 251 of 251 that way
while producing visible garbage: `office_photos` interleaved with fragments of itself.  With the
clip removed the same rule scores 164.  That is now recorded in `gcrip/oracles.py`.

`gcrip/formats/vc_pack.py` ships it, with both identities declared.

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

**Once the codec falls the same reader covers the other 1,858 members and the other four
discs** - they hold the same records, just packed.

## Narrowing the last field - four things the next attempt should not re-derive

**1. `span >= declared` does not mean a member is stored raw.**  Members are padded, so the
span is an upper bound on the stored bytes, never the stored length.  `LOGOS.CDF` has span 512
against declared 464 and is still packed - you can read it in the member itself, where
`logos.cdf` appears as `"log" c0 "os.cdf"` with a control byte in the middle of its own name.
Two members were treated as plaintext on this basis and produced pages of meaningless
"solutions".  **The reliable test is the tag: a raw member has its 4CC at +16, a packed one has
a `00` at +16 and the tag at +17.**  (The shipped `vc_iff` reader never used the span, so its
971 textures are unaffected.)

**2. There is no plaintext twin for the `AUSB` or `PLAY` tags.**  Of NBA 2K3's 108 members with
span >= declared, 30 carry `RTXT` at +16 and are genuinely raw; the other 78 have no tag there
and are packed.  So the only known plaintext on the disc is the texture records - which is what
`gcrip/formats/vc_iff.py` reads, and it is why the framing could be verified at all.

**3. The `b1` byte is a two-bit control, not the high half of a distance.**  Its low six bits
are zero in **every** match observed, across every member: only `0x00`, `0x40`, `0x80` and
`0xc0` ever appear.  A distance high byte would vary.

**4. The rule for `control == 0` is also wrong, not just the unknown one.**  This is the
finding that matters, and it invalidates part of the section above.  Take the members whose
decode contains **exactly one** unknown match - so every other op is forced and the single
unknown's length is fully determined by the declared output size.  Nine of them hit the
identical triple `01 c0 1b` at the identical output position 41 with the identical distance 28,
and they require **different lengths**:

    AH999, ANIMS      29 upwards        CAIRBALL, BUILD36  39 upwards
    CTIME, LINES      67 upwards        MDCLASS            exactly 119
    MINTRO, MONONE    37 upwards        MDNONE, MOCLASS    107 upwards

Same input bytes, same state, different answers.  A length is a function of the encoding, so
one of the ops decoded *before* this point is consuming the wrong number of bytes - which means
`length = b0 + 3, distance = b2 + 1` for `control == 0` is not right either, even though it
reproduces the first four matches of `AH959` against the `RTXT` template exactly.

That is the thread to pull: **the trace that verified `control == 0` is only four ops long**,
and four ops of agreement on a template that is mostly zeros is weaker evidence than it looked.
The raw `BUILD04/16/18/21.DAT` give the full `RTXT` plaintext to check a longer trace against -
16 zeros, `RTXT`, the size twice, zeros, `RTXT`, `17`, `25`, zeros, then a name such as
`headband00`, `armband0007`, `socks0000`, then `ff ff ff f5`.  A compressed member of the same
tag (`AA754`, `AH743`, `AH945`, `AH954`, `AH959`, all 17,072 bytes) decodes to exactly that
shape, so the first 176 bytes are known plaintext and can pin far more than four ops.

## 2026-09-04 night: the DOL is in hand; naive scans do not find the decompressor

`sys/main.dol` (689,216 B, double-read against the D: misread rule) is cached at the
session scratchpad (`vc/nba2k3_main.dol`).  The disc is only `main.dol` + `game.dat`, so the
decompressor is certainly in these 156k instructions.  What was ruled out tonight:

- **No strings**: no `BSUA`, `AUSB`, `.IFF`, `game.dat`, `DAT\1` or `RTXT` anywhere in the
  DOL - the member magic seen in compressed streams is not checked by immediate or by
  string, and files are opened by FST entry number, not path.
- **Signature scans miss it**: top-2-bit extractions near byte loads (2 hits - both audio
  header parsers), 0x40/0x80/0xc0 compares near `lbz` (10 hits - none LZ),
  `lbzx`+`stb` backward-copy windows near flag tests (4 hits - a palette twiddler and a
  string reverse), `mulli x24` table stride (2 hits - both date math).
- The `.sym` files on NHL2K3 are speech-line tables under `sound/speech/`, not linker maps.

The next session should walk it properly: find the DVD read of FST entry 1 (`DVDFastOpen` /
`DVDReadAsync` shapes in the SDK code at the top of .text), follow the read buffer's
consumers to the member loader, and take the branch that handles `kind == 0x01000000`.
Failing that, a Dolphin breakpoint on the first read past the `game.dat` name table gives
the decompressor's address in one run.  The known-plaintext corpus (`vc_members.json`,
`cases.json`, the RTXT template) is ready to verify any transcription instantly - and the
"same bytes, different lengths" contradiction from the empirical attack still says the
scheme carries hidden adaptive state, which is why guessing op grammars kept failing.
