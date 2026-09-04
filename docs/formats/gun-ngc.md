# Gun (Neversoft) - `.ngc` reconnaissance (2026-09-01)

Cluster 4's last disc.  It produces **0 models and 0 failures** - nothing claims its files at
all, which is why there is no error to chase.

## The files are not hashed

`docs/OPEN.md` recorded "2,928 hashed `.ngc` files; a 120-file magic sample gives no dominant
header".  Both halves are misleading.  The names are perfectly ordinary once the whole name is
read rather than the last extension - `af_intro_text.apk.ngc`, `gun_bannericon_01.img.ngc`,
`af_intro_cam0.apk.ngc` - and they sort into six kinds:

| sub-extension | files | MB |
|---|---|---|
| `.apk.ngc` | **1,233** | 136.8 |
| `.mpk.ngc` | **1,233** | 191.7 |
| `.shd.ngc` | 166 | 0.6 |
| `.img.ngc` | 158 | 16.8 |
| `.pak.ngc` | 119 | 31.9 |
| `.fnt` / `.qb` / `.nav` | 9 | 1.0 |

**`.apk` and `.mpk` pair exactly, 1,233 to 1,233**, and share their stems.  That is the same
shape as EA's `.ord`/`.orp` pair, where reading only one half of it cost twelve discs every
model they had, so it is the first thing to test here.

## Why nothing claims them

`plugins/neversoft.py` routes `.img.ngc`, `.tex.ngc`, `.mdl.ngc` and `.scn.ngc`, so the 158
`.img.ngc` **are** offered to it - and `nv.is_img` rejects every one, because it requires the
first word to be `2` and Gun's is `0x04200000`.  Content-sniffing all 2,918 files with
`is_model`, `is_img` and `is_tex` claims **none of them**.  So this is a newer format
generation, not a routing accident, and the same is true of the models: Gun is 2005, alongside
American Wasteland, and both fail where Underground succeeds.

## What is known about `.img.ngc`

A 32-byte header, all samples sharing the shape::

    04 20 00 00  00 00 00 00  00 00 05 05  00 06 04 04  ...   gun_icon_01,  1,568 bytes
    04 20 00 00  00 00 00 00  00 80 09 09  00 06 04 04  ...   loadscrn,   786,464 bytes

Bytes +10 and +11 look like **log2 of the dimensions** - `05 05` for a 32x32 icon and `09 09`
for a 512x512 screen - but the payload sizes do not both follow from that, and two samples are
not enough to settle it:

* the icon's 1,536 payload bytes are exactly `32*32` plus a 512-byte 256-entry palette, which
  reads as `C8`;
* the load screen's 786,432 are exactly `512*512*3`, which is not a GX format at all, and also
  exactly `1024*768` at one byte a pixel, which is a screen resolution and suspicious for a file
  called `loadscrn`.

Both readings cannot be right and neither is confirmed.  **Recorded as reconnaissance, not
findings** - the next session should pull a dozen `.img.ngc` of different sizes and let the size
arithmetic settle the dimension field before any decoder is written.

## Tested 2026-09-02: the `.apk`/`.mpk` pairing is **not** an `.ord`/`.orp` pair

The note above called that "the first thing to test here".  Tested, and it is wrong.

**918 of the 1,233 `.mpk` are exactly 32 bytes**, and those 32 bytes are `AB AB AB ...` - the
MSVC uninitialised-heap fill.  They are placeholders, not the second half of anything.  Only
**315 carry content**, 191.7 MB of it, and their names say what they are: `z_steamboat2`,
`z_fort`, `z_lveast`, `z_hunt`, `z_steamboat`.  **`.mpk` is a map pack** - only levels have one -
and `.apk` is the per-asset pack.  So the EA analogy fails: an EA `.orp` is never empty, because
it is half of one object.

The `.apk` type word is a Neversoft checksum rather than a magic.  Over 62 sampled files it
takes four values: `0xa7f505c4` (49), `0x745dcd45` (7), `0xdad5e950` (4), `0x2b0a3095` (2).

## The `04 20 00 00` header reads, and it is shared

`z_hunt.mpk.ngc` **opens with the same header as an `.img.ngc`**, so this is one asset header
used across the disc rather than an image format.  Big-endian::

    +0    u32  0x04200000
    +8    u16  ?              0x0080 and 0x2000 on two files, 0 on the rest
    +10   u8   log2 width
    +11   u8   log2 height
    +13   u8   GX texture format
    +16   u32  payload bytes
    +20   u32  header bytes   32 on every sample
    +24   u32  offset of the next image, 0xffffffff at the end

**The identity: `payload + 32 == the file's length`, on 5 of 5 distinct sizes** - 1,536+32=1,568,
3,584+32=3,616, 8,192+32=8,224, 786,432+32=786,464.  The fifth is what proves `+24` is a chain
rather than padding: `map_compass.img.ngc` declares an 8,192-byte payload but is 16,416 bytes,
and its `+24` is 8,224 - exactly where a second image starts, and 8,224 + 8,192 = 16,416, the
file's length.

**Format 14 is CMPR and the dimensions are log2**, confirmed together: the 128x128 maps carry
exactly 8,192 payload bytes, which is 128 x 128 / 2.

**Format 6 does not reconcile and is not settled.**  Under the same reading it implies three
different rates for one code - 1.5 bytes a pixel at 32x32 (1,536), 0.875 at 128x32 (3,584) and
3.0 at 512x512 (786,432).  One of the dimension or format readings is wrong for those files and
guessing which would only bury it; recorded so the next attempt starts from the contradiction.

## The geometry is not display lists

A full `gxscan` of the 2.4 MB `z_hunt.mpk.ngc` finds **3 meshes and 168 triangles** in 23
seconds.  As on Asterix, the fallback scanner is not the route in on this disc.


## The map pack's regions (2026-09-03)

`z_hunt.mpk.ngc` (2,434,464 bytes) with the salvage scanner: **still 3 meshes and 168
triangles**, so the geometry is not GX display lists in any shape the scanner recognises, with
or without the greedy skip.  What the file holds, mapped by entropy and float plausibility:

| region | bytes | what |
|---|---|---|
| 0 .. 2,080 | 2 KB | one `04 20 00 00` image: 64x64 CMPR, the chain's only entry |
| 36,256 .. 1,057,824 | 1 MB | **32-byte records**, 31,924 of them - see below |
| 1,056,768 .. 1,441,792 | 385 KB | **floats**, byte autocorrelation peaking at stride 24 and 12 |
| interleaved | ~250 KB | high-entropy blocks of 8-32 KB - textures or packed |
| 1,769,472 .. end | 665 KB | mid-entropy, unread |

The 32-byte records carry a constant 16-byte tail `00 00 30 00 30 00 41 00 00 01 00 00 00 00
00 00` on 241 of them (spaced 32, 64, 96 apart - so most records differ in that tail) and a
head that ends `ff ff 00 00 80 80 80 ff` - an RGBA colour, (128, 128, 128, 255).  Byte 3 of the
head takes 76 distinct values and bytes 12-14 take 36 each: an index and three more.  These
are per-primitive or per-material descriptors, not vertices - 31,924 of them is far more than
one level's materials, and far fewer than its vertices.

The float region at stride 24 is the obvious vertex array - 385 KB / 24 = 16,000 vertices - and
it sits between the records and the high-entropy blocks.  Nothing found yet says which record
field points into it; that pointer is the next thing to look for, and the record's 76-valued
byte 3 is where to start.


### The table is not uniform: descriptors, then index pairs

Looking at consecutive 32-byte rows rather than at the records the constant tail selects:

    00 00 00 00 00 81 00 00 ff ff 00 00 80 80 80 ff 00 00 30 00 30 00 41 00 00 01 00 00 00 00 00 00
    02 72 00 07 02 0a 01 1a 01 96 00 08 01 85 01 1b 01 01 01 1c 00 bc 00 08 00 82 01 1d 00 2d 00 08
    00 08 01 1d 02 88 01 19 03 01 00 07 03 01 01 19 03 7b 01 19 03 92 00 07 03 fa 01 1a 03 9f 02 56
    ...
    03 b9 02 40 03 d6 02 45 03 f5 02 4f 03 f4 01 7d 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00

The first row is a **descriptor** - an RGBA colour `80 80 80 ff` and the constant tail.  What
follows is **big-endian `u16` pairs**: `(626, 7)`, `(522, 282)`, `(406, 8)`, `(389, 283)` ...
with the first value under 1,024 and the second either a small number (7, 8) or in the 280s.
That is an **indexed vertex stream without display-list opcodes** - a position index and a
second attribute index - and it is why `gxscan` sees nothing: there is no `0x98` to find.

The run ends in zeros and the next descriptor follows.  Between the first ten descriptors the
runs are 1,287, 903, 903, 22,416, 0, 0, 48,264, 0, 0 and 178,895 pairs - **253,416 pairs in
all** - and no descriptor field predicts the run length (every header byte correlates at under
0.11 with it), so the runs are terminated, not counted, and the zero-length ones are
descriptors with no geometry of their own.

What is still not known is how a pair addresses the float array: 253,416 pairs against about
16,000 stride-24 vertices means either the first value indexes a per-run window, or the
attributes are split across arrays.  The stride-24 float region is the place to test that.

**2026-09-04 evening (z_steamboat2.mpk.ngc, cached copy):** the map-pack internals are
per-member variable - this member has its position array at **stride 12** (pure f32 triples,
~32,400 verts, world extent +-15k-38k, coarse quantized mantissas) at 0x35c000 after a
14-record descriptor table at 0x35ae80, where z_hunt had stride 24 and a 1 MB table.  The
'80 80 80 ff' record terminator holds on both.  Regions here: 0x140000 = repeating
`07e1 07e0 5555...` fill, 0x3c0000 = RGBA-like color rows.  Do not assume one fixed layout
across .mpk members; the descriptor records must drive the reader.

## CRACKED 2026-09-04: the map pack's level geometry reads

`gcrip/formats/gun_mpk.py` + `gcrip/plugins/gun_mpk.py`.  Verified on three members -
z_steamboat2 (cached), z_hunt and z_fort (double-read from the disc): 28,085 / 27,592 /
31,878 triangles, and the wireframes are the levels (z_fort's walled compound with two
X-braced watchtowers, z_steamboat2's river valley).  Two of the earlier readings dissolve:
the "index pairs" were display-list corners seen without their opcodes, and the "stride-24
float region" was the position array seen at the wrong phase - it is stride 12.

### The pack, top to bottom (z_steamboat2)

| region | what |
|---|---|
| 0x0 | `04 20 00 00` image chain (a 128x128 CMPR lightmap page), more CMPR blocks after it |
| ~0x6000 .. 0x338000 | **prop objects**: per-object inline arrays + the same mesh records (below), plus embedded 32x32 CMPR textures, material register display lists (`61` BP loads), 32-byte material records (checksum, pass count, f32 draw distance, texture checksum) |
| 0x337d0c | the LAST `aa ff ee ff` marker - the **scene header is the 44 bytes before it** |
| .. 0x352000 | CMPR texture pages |
| 0x352xxx | 32-byte material table (`00..00 ff | texture crc | idx | crc | passes | .. | pass idx | material idx`) |
| 0x356410 .. 0x35bdcc | 718 32-byte descriptor/group records (u32 0, u32 corner count, u32 format word, u16 texture index or ffff, u16 2, RGBA, `30 00 30 00`, `41/51`, u16 1) - counts sum to 54,441, more than the meshes draw; **not needed to read the geometry**, purpose open (LODs?) |
| 0x35BDD0 | **positions**: 32,725 x f32[3] big-endian |
| +16 zero pad | **colours**: 5,505 x RGBA8 |
| next | **uvs**: 22,130 x s16[2], /1024 |
| +2 | **normals**: 43,481 x s16[3], /16384, unit length (the run test that locates them) |
| .. end | **the level meshes** - mesh records + display lists, back to back |

### Scene header (marker - 44)

    u32 position count | u32 normal count | u16 colour count | u16 uv count | ...

z_steamboat2: 32725 / 43481 / 5505 / 22130.  The reader finds the arrays end-anchored:
the normal array is the file's longest run of unit s16 triples; uvs end 2 bytes before it
(4-aligned), colours before the uvs, positions before the colours with the exact base
settled by a bounding-sphere vote (the padding varies).

### Mesh record - scan signature `00 15 00 04`, dl size repeated

Relative to the signature at `s` (the record is 64 bytes; level meshes carry one extra
leading sphere copy at s-52, making 80 - scan by signature and both read the same):

    s-36  u32    display list size        s+4   u16  corner count
    s-32  u32    material checksum        s+6   u16  0x0200
    s-28  u32    flags (81000007 / 90000007 / 80002047 ...)
    s-24  u32    mesh checksum            s+12  u32  display list size again
    s-20  f32[4] bounding sphere x y z r  s+16  f32  (draw distance?)
    s-4   u32    0                        s+24  u32  0x00004400
                                          s+28  the display list

### Display list

`08 50` CP VCD_LO (0x7e00 on level meshes), `08 60` VCD_HI (3), `10 ...` XF loads, then
GX draws - `9f` strips / `97` triangles, VAT 7 - whose vertices are index16 tuples
`(pos, nrm, col0, tex0)` per the VCD.  **Indices are absolute into the global arrays**:
across all 692 level meshes the per-attribute maxima are 32724 / 43480 / 5504 / 22106 =
count - 1 for every array.

### The proof

Every level mesh's decoded vertices sit inside the bounding sphere its own header stores:
mean containment 1.000 over 692 meshes, worst dmax/r = 1.017.  A wrong position base
fails this instantly (base +8 scores 0.087), which is also the reader's runtime vote.
Face-vs-vertex-normal agreement is only moderate (mean dot +0.27, 39% > 0.7 on
well-shaped triangles, positive-leaning so the winding is right) - the normal indices and
array are as described, but treat exported normals as best-effort.

### Still open

* **Prop objects** (front of the pack): the same mesh records, but their indices address
  per-object INLINE arrays (positions f32 right after an `80 80 80 ff` descriptor, then
  colours, then uvs; z_hunt's "(626, 7)" pairs are 2-attribute corners of this kind).
  The sphere test rejects them (10-103 per pack), so they are skipped, not garbled.
  Their object header is 32 bytes at marker-44 shape too: `u32 nvert, u32 ntri, ...`
  (0x6d60 in the cached member: 24 verts, 8 tris, 480 bytes = 24 x (12+4+4)).
* **Textures**: material checksum -> texture checksum is in the pack's material table;
  the CMPR pages and 32x32 tiles are embedded with `04 20` headers.  Not yet bound.
* The 718-record descriptor/group table before the position array (counts sum past what
  the meshes draw).
* `.img.ngc` format 6 still does not reconcile; `.apk` (1,233) and `.pak` (119) unread.
