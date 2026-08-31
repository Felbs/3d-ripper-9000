# `WART3.00` `.hog` archives - Warthog's engine

Three discs, 101 archives, **165,704 named members** - 36,156 `.btga` textures, 29,021 `.bmsh`
meshes, 3,622 `.bskl` skeletons, 10,597 `.anm` animations, 5,226 `.lvl` and 3,269 `.mdl`.
`gcrip/formats/wart_hog.py`, big-endian:

    +0   char magic[8]        "WART3.00"
    +8   u32  member count
    +12  u32  name table offset
    +16  u32  file-name section bytes
    +20  u32  directory-name section bytes
    +24  the records, 24 bytes each:
             u32 data offset
             u32 packed size
             u32 unpacked size
             u32 hash
             u32 file name offset    from name table + directory bytes
             u32 directory name offset

The name table is two runs of NUL-terminated strings - the directories first, each ending in a
slash, then the file names - so a member's path is its directory plus its name.  All 101
archives parse.

## The field order is the trap, and contiguity does not catch it

Read as if the records began at +16 rather than +24, **every offset and size still chains
perfectly**: member N ends exactly where member N+1 begins, all the way down every archive.
The two name words merely shift the whole window by eight bytes, so the arithmetic that
normally confirms a table confirms nothing here.

What gives it away is the payload.  Under the wrong order Animaniacs' two `.btga` font
textures unpack to 9,602 bytes and its two `.tnf` metrics files to 131,168; under the right
one both textures are 131,168 and both metrics files are 9,602.  *Contiguity proves the
stride, not the field order* - only the data can.

The directory-bytes word is byte-swapped on some archives: Animaniacs stores 30 as
`00 00 00 1e`, Looney Tunes stores 147 as `93 00 00 00`.  Neither byte order can be trusted, so
the reader accepts the value only if it lands just past a NUL in the name table.

## Tiger Woods is not this format

The cluster was listed as seven discs.  It is three.  The four Tiger Woods discs also carry
`.hog` - 872 of them, more than eight times the rest of the cluster - but they open `CTRL`
followed by `00 00 00 18` and share nothing else with these.  **An extension is not a format**;
this cluster was sized by one.

## The codec - open

Every member is compressed (the only 607 exceptions are empty `.mrk`), and the codec is
private.  What is established, so the next attempt does not start over:

* A member begins with `u32 packed size - 4`, then the stream.  That holds on 160 of 177.
* **A token byte `0xE0 | n` is a literal run of `(n + 1) * 4` bytes.**  Four independent
  anchors agree: `e1` gives exactly `model` CRLF `{`, `e3` gives `level` CRLF `{` CRLF TAB
  `name(`, `e5` gives that plus `{cactus}`, and `e6` gives `ObjectType}, Const, Number, `.
  The run is always a multiple of four bytes.
* Tokens under `0xE0` are matches, and they are **not a fixed width**.  Since the literal runs
  are known exactly, a walk with a fixed match width must land on the last byte of the stream:
  over 3,732 member streams, two bytes lands on 541, three bytes on 493, and the best split
  model on 613 - all near chance.  The overshoot histogram is a long flat tail, not a
  concentration at one to three bytes, so this is not a padded stream either.  **Match tokens
  carry length extensions or are otherwise variable-width.**
* A parameter sweep over 2-byte matches - offset `((b & mask) << 8) | next`, length
  `((b >> shift) & mask) + min`, every shift 0-7, five length masks, seven offset masks, and
  offsets and lengths additionally scaled by 2 and 4 in case the codec is word-oriented, since
  literal runs come in multiples of four - decodes **none** of six known-length members to
  their exact size.

Length-extension grammars are **also ruled out**.  Re-running the sweep with LZ4/LZO-style
extension bytes - on the literal nibble when it saturates, on the length field when it
saturates, and with 16-bit offsets - decodes none of five known-length members to their exact
size.  What remains untried is a match encoding whose *offset* is variable-width, or a
second token plane; both would explain a variable match width that no length rule fits.  `frontend_cog1.lvl` and `frontend_cog2.lvl` on Animaniacs are the test vector:
199 packed bytes each to 386 out, **differing in exactly one byte** (`67 31` against `67 32`,
the `g1`/`g2` of their own names), so any correct decoder must produce two texts differing in
one character.
