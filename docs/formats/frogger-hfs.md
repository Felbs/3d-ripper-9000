# Frogger: Ancient Shadow - `gamedata.bin` is an `hfs\n` archive (2026-09-01)

The last unexamined disc of cluster 1.  Its 198 MB `files/gamedata.bin` is the whole game, and
the disc produces nothing today.

## The directory reads

Little-endian::

    +0   char magic[4]      "hfs\n"
    +4   u32  span          bytes of member data this block covers
    +8   u32  count         members in this block
    +12  u32  data offset   absolute, where the members begin
    +16  the entries, 8 bytes each:
             u32  sector | 0x01000000     member start, in 2,048-byte sectors from data offset
             u32  size                    member length in bytes

On the first block: `span` 106,496, `count` 8, `data offset` 137,216, and the eight sector
values 0, 9, 11, 19, 24, 32, 37 and 48.  Multiplied by 2,048 and added to the data offset they
land on **137,216, 155,648, 159,744, 176,128, 186,368, 202,752, 212,992 and 235,520** - and a
scan for the member magic finds it at exactly those eight offsets.  **8 of 8**, which is what
says the directory is read correctly rather than plausibly.

`span` is consistent too: 137,216 + 106,496 = 243,712, which is where the ninth member sits.  So
this header describes one block of a 198 MB file and there are more; whether they chain or are
listed somewhere is not yet known.

## The members are `PRS1`, and it is not Sega's PRS

Each member opens::

    +0   char magic[4]   "PRS1"
    +4   u16  tag        differs per member - 'jp', 'ir', '4E', 'uo', 0x10e4, 0x8c26
    +6   u16
    +8   u32  size       the same length the directory gives
    +12  the payload

**How the header length is known**: members 0 and 2 have different sizes (17,207 and 14,482) and
*identical bytes from +12 onwards*, as do members 1 and 3.  Fields that repeat across members of
different lengths are payload, not header - so the header ends at +12 and what I first read as a
checksum and an uncompressed size at +12 and +16 is the start of the compressed data.

The payload is compressed - entropy 7.59 to 7.75 - and opens `ff ff ef 03 18 01 00 fa`.

## What the payload is, measured 2026-09-02

The directory still reads 8 of 8.  Member 0's header is `PRS1`, tag `jp`, then `37 43 00 00` -
17,207 little-endian, exactly the length the directory gives, which confirms the 12-byte header
independently.  The `ff ff ef 03 18 01 00 fa` recorded above is at **+20**, not at the start of
the payload; +12 is `fd 23 eb f0` and +16 is `7c 14 00 00` (5,244 - and since that is far
*smaller* than the 17,207 compressed bytes it cannot be an uncompressed size).

**The byte histogram says what the content is.**  The most common bytes in the payload are
`ff` (1,061), `3f` (492), `bf` (404), `40` (327), `00` (308), `3e` (251), and the most common
pairs are `9f b0`, `ff 3f`, `1b a0`, `ff bf`, `ff ff`, `3f ff`.  `3f`, `bf`, `3e` and `40` are
the exponent bytes of IEEE-754 floats near 1.0 - so there is float-heavy geometry in here.

But it is **not raw floats**: read as `f32` at every plausible offset in both byte orders, only
0.21-0.23 of the words are finite and in a sane range, where a real vertex array runs 0.67 and
up.  Exponent bytes present while 4-byte alignment is destroyed is what an LZ stream *over*
float data looks like, so the payload is compressed, and it is compressed over exactly the kind
of content worth having.

A family of LZSS decoders was tried and none survives: control words of 8 and 16 bits, literal
flag as 1 and as 0, LSB-first and MSB-first, four common (distance, length) packings, each from
+12, +16 and +20 - **48 combinations, and not one produces 2,000 bytes** before running past
the start of its own output.  Frogger is a RenderWare game, so a correct decode would show
RenderWare chunk ids; that oracle never fired.

**`gcrip.formats.prs` rejects it** at every plausible offset (8, 12, 16, 20, 24), always with
*back-reference before start*.  So the `PRS1` tag is not Sega's PRS, whatever it borrowed from
it.  That codec is the remaining work, and it is a session of its own; the archive around it is
solved.


## The archive is closed (2026-09-03)

Frogger: Ancient Shadow's ``gamedata.bin`` - an ``hfs\\n`` archive, whole.

The whole game is one 197,959,680-byte file and the disc produces four models.  An earlier pass
read the first directory block and left the rest open: *"this header describes one block of a
198 MB file and there are more; whether they chain or are listed somewhere is not yet known."*

They are a contiguous table at the front of the file, one block every 2,048 bytes.  Little-endian::

    +0   char magic[4]     "hfs\\n"
    +4   u32  span         bytes of member data this block covers
    +8   u32  count        members in this block
    +12  u32  data offset  absolute, where this block's members begin
    +16  count x 8 bytes:
             u32  sector | 0x01000000   member start, in 2,048-byte sectors from `data offset`
             u32  size                  member length in bytes

**Three numbers close the archive, and each is exact:**

* the directory is **67 blocks**, and ``67 * 2048 = 137,216`` is exactly the data offset the
  first block declares - so the table ends precisely where the data begins;
* the blocks **chain by span**: block 0's data offset plus its span, ``137,216 + 106,496 =
  243,712``, is block 1's data offset, and so on down all 67;
* the spans sum to **197,822,464**, and ``137,216 + 197,822,464 = 197,959,680`` - the file
  length, to the byte.

That accounts for **4,195 members**.

Every one of them is ``PRS1`` and compressed: measuring 355 of them gives entropy 6.13 to 8.0,
with none stored, so there is no plaintext on this disc to decode the codec against.  ``PRS1``
is not Sega's PRS - ``gcrip.formats.prs`` rejects it at every plausible offset with
*back-reference before start* - and 48 LZSS variants have already failed against it.  That codec
is the remaining work; the archive around it is finished.

## No container plugin, and why

Every one of the 4,195 members is `PRS1`-compressed and nothing reads that yet, so emitting them
would add 198 MB of undecodable data to the dump for zero models.  The reader ships with its
identities and its tests; the plugin follows the codec.

## And there is no plaintext on this disc

Measuring 355 members across the first 8.4 MB gives entropy 6.13 to 8.0 - the low end is small
files, not stored ones - and every single one opens `PRS1`.  So the known-plaintext technique
that broke the Tiger Woods codec has nothing to work with *within* this disc.  If it is to be
used here the pair has to come from another Frogger title.


## Two things the codec attempt was missing (2026-09-03)

**The member header holds the unpacked size.**  The earlier pass read the word at +4 as a u16
"tag" (`'jp'`, `'ir'`, `0x8c26`) because it varied per member.  It is a `u32`, and it is the
**unpacked length**: on Ancient Shadow **365 of 368** members have `+8` equal to the directory's
size and `+4` above it, at packed/unpacked ratios of 0.14 to 0.92.  Every one of the 4,195
members carries its own length oracle.

**Frogger's Adventures: The Rescue uses the same archive and the same codec.**  Its 18 `.hfs`
open `hfs` where Ancient Shadow's is `hfs
` - a version byte - with the same 16-byte block
header and 8-byte entries, and every one of its **1,552** sampled members is `PRS1` with the
same 12-byte header.  Twice the corpus, and a second game to cross-check any decoder against.
No stored members there either (entropy 5.0 to 8.0, nothing under 5), so the plaintext will
have to come from the decoder's own output confirming a RenderWare chunk shape.

That shape is visible.  The least-compressed members open, after the header::

    fd 23 eb f0 | 78 14 00 00 ff ff ef 03 18 01 00 fa | f1 00 00 18 3a | eb f0 1c f3 f6 00 00 10 | eb f0 ...

`78 14 00 00 ff ff ef 03` is a RenderWare chunk size and a 3.x version stamp - eight literal
bytes in a row - and **`eb f0` recurs at +14 in every member and every few bytes after**, so it
is part of the control grammar, not data.  What `fd 23` and `eb f0` encode is the codec, and
with a length oracle on every member and a chunk-shaped plaintext to hit, that is now a
tractable search rather than a blind one.


## Closed 2026-09-03: `PRS1` is Okumura LZSS, read out of the DOL

The DOL route again.  Ancient Shadow's executable names its archives (`GAMEDATA.BIN`,
`AREA00.HFS` ...) and the loader that owns those strings (`0x80008dd4`) ends in a
state that byte-swaps the member's first three words, compares the first with `0x31535250`
(`PRS1` little-endian), allocates the second and calls `0x800094a8(src + 12, dst, packed,
unpacked)`.  That routine is 84 instructions of the LZSS everyone learned from `LZSS.C`:

* 4,096-byte ring, zeroed (`memset(ring, 0, 0xfee)`), write position starting at **0xFEE**;
* flag byte consumed LSB-first with the `| 0xff00` refill; **1 = literal, 0 = copy**;
* a copy is two bytes: `pos = b1 | ((b2 & 0xf0) << 4)` - an **absolute ring position** -
  and `length = (b2 & 0x0f) + 3`.

That absolute position is the whole reason 48 variants failed: every one of them measured
distances backwards from the output.  `fd 23 eb f0` was never a control word; `fd` is a flag
byte (literals, literals, copy...) and `eb f0` a copy from ring position 0xfeb - the last bytes
written - which is why it "recurred every few bytes".

`gcrip/formats/prs1.py` is the port.  Members that do not open `PRS1` are **stored**: the
loader's other branch is a plain copy, and those members are RenderWare audio dictionaries
(`0x0809`, vendor 8 = RWA).  Both games use it: The Rescue's `.hfs` differ only in the
version byte (`hfs\x07` against `hfs\n`), and `frogger_hfs.is_hfs` now takes both.

## What the members are

RenderWare 3.6 streams (`ff ff 03 18`), little-endian, one member = one chunk sequence:

| top-level chunk | count in 350 sampled | what |
|---|---|---|
| `0x23` PITEXDICTIONARY | 154 | platform-independent texture dictionaries: `rwImage` (0x18) rasters, 8-bit paletted, with a TEXTURE chunk naming each - `gcrip/formats/rw_pitxd.py` |
| `0x29` CHUNKGROUPSTART ... `0x2A` | 125 groups | named groups ("locator1") of **CLUMPs** (175 in the sample, 256 geometries), HANIM animations, UV animations |
| `0x0B` WORLD | 2 | level sectors |
| `0x24` TOC | 7 | tables of contents |
| `0x0809` (stored) | 12 | RenderWare Audio wave dictionaries - skipped |
| `01 00 01 00` ... | 45 | not RenderWare; Hudson's own, unread |

`gcrip/plugins/frogger_hfs.py` expands an archive to `<block>_<index>_<k>[_<group>].dff / .bsp /
.txd`, and `plugins.renderware` reads the clumps and worlds and binds their textures through
the PI dictionaries (added to its texture index).  On the first 8 MB of `gamedata.bin`:
**186 models, 110,947 triangles, 175 textures bound** - from a disc that produced four models.
The whole archive is 198 MB; the re-rip (wave 33) will say what the game holds.

Tests: `tests/test_prs1.py` carries an LZSS encoder that mirrors the ring and round-trips
literals and absolute-position copies (including a copy from the untouched zero ring), decodes
a two-texture PI dictionary, and walks a synthetic archive through the container plugin.
