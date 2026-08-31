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

## The codec - the literal form and the low match form are solved

Two of the three token ranges are cracked and verified against real text rather than against a
length count.

* A member begins with `u32 packed size - 4`, then the stream (160 of 177 checked).
* **`0xE0 | n` is a literal run of `(n + 1) * 4` bytes.**  Four independent anchors agree:
  `e1` gives exactly `model` CRLF `{`, `e3` gives `level` CRLF `{` CRLF TAB `name(`, `e5` that
  plus `{cactus}`, `e6` `ObjectType}, Const, Number, `.
* **A token below `0x80` is a match carrying its own literals**::

      literals = b & 3            emitted BEFORE the match
      length   = (b >> 2) + 3
      offset   = next byte + 1    counted back from the end of the output

  The stream order is token, offset byte, then the literal bytes - but the literals come out
  *first*, and the match copies after them.

`frontend_cog1.lvl` decodes cleanly under this all the way to the first token that is not below
`0x80`, and every step is checkable against the text:

    e5  24 literals            level CRLF { CRLF TAB name({cactus}
    01  lit ')' len 3 off 17   -> CRLF TAB
    e1  8 literals             acount(4
    04  lit -  len 4 off 12    -> ) CRLF TAB
    0d  lit 'p' len 6 off 12   -> count(
    05  lit '0' len 4 off 12   -> ) CRLF TAB
    87  ...                    stops here, at output byte 52

giving `level CRLF { CRLF TAB name({cactus}) CRLF TAB acount(4) CRLF TAB pcount(0) CRLF TAB` -
correct text, matched brackets, real CRLF.

On its own the solved half decodes **44 of 4,663 members outright** - the small ones that never reach a high token - so the value here is the verified grammar, not the yield.

### What is left: the tokens from `0x80` to `0xDF`

Only that one range.  The next bytes are `87 40 0b 73 87 40 0b 74 87 40 0b 62 87 40 0b 6f`,
which is a **four-byte unit repeating with only its last byte changing** - `s`, `t`, `b`, `o` -
and the text it has to produce is known exactly from the pattern already decoded:
`scount(0) CRLF TAB`, `tcount(0) CRLF TAB`, and so on.  So the unit emits one literal letter
and then copies `count(` and `) CRLF TAB` from twelve back, the same offset the low form has
been using.

That is a very tight constraint - a known input of four bytes and a known output of twelve -
and it is where the next attempt should start.  Note the offset cannot come from the byte
after the token: `0x40 + 1` is 65 and the output is only 52 bytes long at that point, so the
`0b` (which is 12, the offset in use) is the more likely offset byte and `0x40` something else.

The high form takes **two operand bytes** - the repeating unit `87 40 0b XX` is four bytes and
`XX` is the literal, leaving two - and with

    lit = (t >> 2) & 3       len = (a >> 4) * 2 + 3       off = b + 1

`frontend_cog1.lvl` produces its full 386 bytes and the first 130 characters are **exactly
right**::

    level CRLF { CRLF TAB name({cactus}) CRLF TAB acount(4) CRLF TAB pcount(0) CRLF TAB
    scount(0) CRLF TAB tcount(0) CRLF TAB bcount(0) CRLF TAB ocount(0) CRLF TAB
    attribute({ObjectType}, Const, Number, 0.000000

with the `s`, `t`, `b`, `o` series coming out in order and no repeated fragment.  For the
`0x87` unit the arithmetic checks exactly: `a = 0x40` gives length 11, `b + 1` gives offset 12,
and copying 11 bytes from 12 back at output 53 lands on index 41, the `c` of the previous
`count(0) CRLF TAB`.

**What is still wrong is the literal count, and only for the tokens above `0x87`.**  The decode
derails at `0x8b`, where `(t >> 2) & 3` claims two literals and takes `e0 4d` - and `0xe0` is a
literal-run token, not text.  The same thing happens at `0x89` (takes `88 40`), `0x9c` (takes
`e1 53 75`) and `0xaf` (takes `ae 8d 00`).  Every one of those wants **zero** literals while
`0x87` wants one:

    token   (t>>2)&3   literals it actually needs
    0x87       1            1
    0x89       2            0
    0x8b       2            0
    0x9c       3            0
    0xaf       3            0

**And the literal count is not the only thing wrong above `0x87`.**  With `len` and `off` held
at the formulas above and the literal count left completely free - brute-forcing all four
values at each of cog1's eight high tokens, 65,536 assignments - **none** produces 386
printable bytes.  So `len = (a>>4)*2+3` and `off = b+1` are right for the `0x87` units and
wrong for the tokens above them: the range has sub-forms rather than one shape with a variable
literal count.

### `a == 0` marks a second sub-form, and it carries no literals

The two forced data points are `0x87`, whose `s` must be a literal, and `0x8b`, whose next
byte is `0xe0` and so must be a token.  No bit-field of the token separates them - but their
**first operand does**: `0x87` has `a = 0x40`, `0x8b` has `a = 0x00`.

Treating `a == 0` as a sub-form that takes **no literals** improves every test vector at once,
which is what a real rule does and a lucky one does not:

| member | baseline | with `a == 0` handled |
|---|---|---|
| `frontend_cog1.lvl` | 38.1% | **95.6%** |
| `frontend_scroll.lvl` | 42.5% | 58.1% |
| `frontend_new.lvl` | 5.8% | 12.4% |
| `triggers.txt` | 2.5% | 3.6% |

**Read that table carefully: it is the share of declared output the walk *produced* before
failing, not the share that is correct.**  Every byte produced is printable, but the output is
visibly wrong long before the end - cog1's tail comes out
`)CRLF TAB attrib)CRLF TAB attrib)CRLF TAB attrib`, a fragment replayed over and over, which
is what a match does when its length overruns the cycle it is copying.  The verified-correct
prefix is still the ~130 characters the low form alone produces.

So what `a == 0` buys is a walk that stays in step much further, not a decode.  That is real
evidence the sub-form exists - a wrong rule desynchronises immediately and hits a non-text
byte, and this one does not - but it is not 95% of a working decoder.

The best length seen for the sub-form is `(t & 0x1f) * 2 + 3` with the offset still `b + 1`;
`(b >> 2) + 3` is close behind.  Both are clearly too long: the two `a == 0` tokens before
cog1's failure take lengths 55 and 39, and those are what produce the repeated `attrib`.  The
sub-form's length is the thing to pin next, and it wants to be far shorter.

A constraint search also came up empty and is worth recording, because it rules out a whole
family rather than one guess.  Branching only on **distinct `(t, a, b)` triples** - so cog1's
four identical `87 40 0b` units cost one choice, not four - with the literal count free over
0-3, the length free over 3-48, and the offset drawn from every value derivable from `a` and
`b` (`b`, `b+1`, `a`, `a+1`, and the two-byte combinations either way round), pruned on
printable output and the exact 386-byte target, finds **no consistent decoding in seven
minutes** - and a second run widening the lengths to every `a`-derived value up to 400, which
the first capped at 48 and so never tried, finds none either.

**Both searches time out rather than exhaust their space, so this is evidence and not proof.**
What it says is that the offset being a simple function of the two operand bytes - the
assumption every attempt tonight has shared, including the one that got the first 130
characters right - now looks unlikely enough to try elsewhere first: a running or previous
match offset, or a value carried in bits of the token that nothing else uses.

Two other angles came up empty and are recorded so they are not repeated: a search for members
whose first high token leaves a short enough tail to solve exactly finds **none** of 18,730
(the first high token is always far from the end), and the free-length DFS over the whole
stream does not terminate in any reasonable time.

So the literal count is not a fixed bit-field of the token.  Either it comes from somewhere
else, or `0x87` is not a high token at all and its `s`/`t`/`b`/`o` letters arrive by a reading
of `87 40 0b XX` that this one does not have yet.  That single question is what is left.

