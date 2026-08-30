# `res` `rdms` meshes - Digimon Rumble Arena 2, Lemony Snicket, Samurai Jack

The `res` middleware splits into tagged sections (`gcrip/formats/res.py`).  `surf` sections are
textures and already shipped; `rdms` sections are the geometry, and they were the last thing on
these three discs that produced nothing.

`gcrip/formats/res_rdms.py` + the `rdms` branch of `gcrip/plugins/res.py`.

## Layout

Big-endian.

    +0x00 u32 1
    +0x04 u32 0xffffff1c
    +0x08 u32 display-list block size      - undercounts the padding on some sections
    +0x0c u32 display-list block offset    - 0x54
    +0x1c f32 position scale               - used only when positions are s16
    +0x40 u32[5] array offsets             - each relative to its own header word
    +0x54 u8  position format              - 0 = f32 triples, 1 = s16 triples
    ...   a short preamble, then the GX display list

A corner is five `u16` attribute indices - position, normal, colour, uv, and a fifth that is
always zero - so the display-list stride is 10.

## The two things that had been wrong

**The array offsets are self-relative.**  Array *i* is at `u32[i] + 0x40 + 4*i`.  Any single
base gets the first array right and every later one wrong by four more bytes than the last,
which is precisely the symptom the earlier pass recorded: "the arrays are consistently one
element short of what the index columns need".  With the right base all five offsets are
32-byte aligned and the last is the end of the section - two checks that a wrong base fails.

**The strides come from the arrays' own sizes.**  Each array is padded to 32 bytes, so a stride
is admissible only when `count * stride` rounds up to exactly the gap to the next array.  On
every section sampled that leaves a single candidate: 6 for positions (12 where the header byte
says `f32`), 3 for normals, 4 for uvs.  Nothing has to be guessed, and a wrong walk fails this
test rather than producing a plausible-looking mesh.

## Scales

* normals `s8/64` - an `s8` normal of (24, -59, 0) has length 63.7;
* uvs `s16/4096` - the maximum on most sections is exactly 4096, one texture edge;
* `s16` positions times the `f32` at +0x1c.

That last one is the least certain part, and it is worth saying why it is believed: raw `s16`
positions are quantised into a power-of-two box (256, 512, 1024, 1536, 2049 across the sample)
and the float brings them back to 90-1,070 world units, the same range as the sections that
store `f32` positions directly (±418).  Without it the two encodings differ by a factor of
several hundred.

## Strips are mostly stitches

A section is one long `0x98` strip that joins many short runs, so **about half the corners are
zero-area joins** - 3.1 million raw triangles on Samurai Jack against 1.5 million real ones.
They are dropped by area.  This is worth knowing before treating a 50% degenerate rate as a
sign that a layout is wrong; here it is normal.

## Result

| disc | `rdms` sections | parsed | triangles | with uvs |
|---|---|---|---|---|
| Samurai Jack: The Shadow of Aku | 23,860 | 22,947 (96%) | 1,499,463 | 22,512 |
| Lemony Snicket | 60,722 | 56,707 (93%) | 4,976,261 | 55,833 |
| Digimon Rumble Arena 2 | 14,984 | 14,364 (96%) | 939,695 | 14,104 |

Median span over median edge is 2.7 to 6.6, so the meshes are coherent rather than exploded.

## Still open

The `node` sections hold the scene graph, so meshes come out one section at a time in their own
space rather than assembled into a level.  Colour arrays are read but not bound (they are a
single entry on nearly every section), and `surf` textures are not yet matched to the meshes
that use them.
