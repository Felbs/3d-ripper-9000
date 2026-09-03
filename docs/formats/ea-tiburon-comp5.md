# EA Tiburon `comp5` = GCMP.LIB `LZH1` - cracked 2026-09-03

The codec behind fourteen EA Tiburon discs (Madden NFL 2002-08, NCAA Football 2003-05, NFL
Street 1-2, NASCAR Thunder 2003 / 2005): every model on them is a `TERF` member whose `COMP`
entry says type 5.  `gcrip/formats/ea_lzh1.py` decodes it; `ea_terf.expand` now hands the
unpacked bytes on, and they are `TMdl` models and `MMAP` texture packs
([ea-tiburon-tmdl.md](ea-tiburon-tmdl.md)).

## How it was found

Madden 06's DOL, disassembled with capstone (`CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN`).
The parser that loads `TERF` tags calls nothing decoder-shaped, so the hunt went the other
way: score every function in the text segment by shifts + byte loads + back-branches - calls,
dump the top hits, and follow the pointers.

* The two best candidates had **zero direct callers** - they are states of a state machine,
  reached through a function pointer in the small-data area (`-0x4210(r13)`).
* The function that installs that pointer sits in a vtable at **`0x805816c0`**, next to the
  string `GCMP.LIB`, which registers five codecs in order: `NONE`, `RLE1`, `HUFF`, `LZM1`,
  **`LZH1`**.  TERF's type 5 is the fifth.
* `LZH1`'s decoder reads its tables from `0x80543950`: deflate's length base / extra-bit
  tables and deflate's distance base / extra-bit tables, byte for byte.  Its bit reader
  (`0x804f9c44`) shifts a 32-bit accumulator left and takes bits from the top - **MSB-first**,
  which is why `zlib.decompress(data, -15)` failed at every offset, in both bit orders: the
  code assignment matches deflate but the block header does not exist.

## The stream

Bits MSB-first, bytes big-endian.

```
repeat:
  1 bit           0 = a block follows; 1 = end of stream
  if end:         32 bits = Adler-32 of the whole output (checked); stop
  285 x 4 bits    code lengths of the literal/length alphabet, 0 = unused
  30 x 4 bits     code lengths of the distance alphabet
  canonical Huffman codes assigned by deflate's rule (shorter first, then by symbol),
  each code read one bit at a time
  until symbol 256:
    < 256         literal
    256           end of block
    257 + i       match length: i + 3 for i < 8, else LEN_BASE[i] + LEN_EXTRA[i] bits;
                  i = 27 is a bare 227 - the longest match
    then a distance symbol d: d + 1 for d < 4, else DIST_BASE[d] + DIST_EXTRA[d] bits
```

Window 32 KiB.  The 4-bit code lengths are what made the members look "nibble-coded": a
member's first bytes are `33 c4 44 44 4c 4c` - lengths 3, 3, 12, 4, 4, 4 ... for symbols
0, 1, 2, 3 ...

## Verification

* All 365 `COACHES.DAT` members decode to their declared 17,020 bytes with matching
  Adler-32 and start `MMAP`.
* `STADIUMS.DAT` members unpack 701,745 -> 1,484,356 bytes and start `TMdl`.
* `UNIFORMS.DAT` members unpack to 331,684-byte `MMAP` packs (Hip, Thigh, Torso, Helmet ...).
* Tests: `tests/test_ea_lzh1.py` carries a reference encoder written from the description
  above; the decoder round-trips literals, overlapping copies, far distances with extra
  bits, the bare-227 symbol and multi-block streams, and refuses a bad checksum, a wrong
  declared size and a distance before the start.

Speed: ~3 MB/s of output in pure Python; a stadium takes half a second.

## Not done

The other GCMP codecs (`RLE1`, `HUFF`, `LZM1`) have not been seen in any TERF on these discs
(every packed member is type 5); their members would keep the `.compN` name.
