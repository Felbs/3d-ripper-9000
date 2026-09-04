# Acclaim Austin `supertree0.tre` (Vexx, Turok: Evolution)

Container and textures read 2026-09-04 (`gcrip/formats/acclaim_tre.py`, `gcrip/plugins/acclaim_tre.py`, `tests/test_acclaim_tre.py`).

Both discs are one file: `files/supertree0.tre`, 739 MB on Vexx and 846 MB on Turok, beside a
`Game.txt` that lists the levels by path (`data\levels\frontend\attractmode\attractmode.atr`).

## The table

16-byte big-endian records from byte 0 - `u32 id, u32 offset, u32 size, u32 key` - sorted by
`key` (a name hash), read until the keys stop ascending: 4,213 records on Vexx, 9,879 on
Turok.  The first member begins right after the last record and the members tile the file
exactly (739,296,370 of 739,296,370 bytes).  Member 2938 (2.1 MB) opens with the same
triples the table holds, so directories are members too - the tree in the name.

## Members

| head | share of a 300-member sample | what |
|---|---|---|
| ten zero bytes, `ff ff` at +24 | 57 % | **textures**: `u16 bytes` at +10, `u16 width, height, width, height` at +16, format byte at +29 - `0x30` / `0x2e` CMPR (with mips: 64x64 = 2,048 + 512 + 128 + 3 x 32 = 2,784 bytes), `0x2c` / `0x2b` RGBA8.  Decoded by the plugin (the plants, water and rock of Vexx come out right) |
| `SWAP` | 12 % | animation / stream packs (`ANIM`, `STRM` inside) |
| `\x01atr`, `\x01ati` | 6 % | actor definitions and instance lists - a tag-length-value stream (`ACTOR`, `NAME`, `POS`, `ROT`, `SCALE`, `ACTOR_VARIABLES`, `EVENTS`) with `Y:\Data\Actors\...` source paths |
| `*PARTDEF`, `*EMITDEF`, `*PF`, `*key`, `;----` | 20 % | text |

`gxscan` finds no display lists in the largest members (a 2.1 MB directory, a 101 KB blob, a
134 KB `.ati`), so the **models are still unlocated** - most likely behind the `.atr` actor
definitions' references.  The plugin hands out every member under 4 MB except the `SWAP`
packs, textures as `tex_<key>.atx`.

## The tree is nested, and the models are `AAAp` (2026-09-04, later)

Members whose first 16 bytes read as a record with an offset and size inside the member are
**tables themselves** - 105 of them on Vexx, one of 407 MB - and the plugin now walks them
(`expand` recurses to depth 3, naming leaves `<key>/<key>/tex_<key>.atx`).  A full recursive
census of Vexx: 7,706 more textures (40 MB; the 65,568-byte ones carry a `u32` byte count at
+8 rather than a `u16` at +10, accepted now), 4,631 `SWAP/ANIM`, 21,264 `*PARTDEF` texts,
3,451 `.atr` actors - and **74 `AAAp` members, 116 MB**, the level geometry: `"AAAp", u32
version 0x01f00002, u32 offset a, u32 offset b, u32 32000, u32`, then 0x50-byte segment
records (the two offsets again, a bounding box of eight `s16`, a count) and, at the offsets,
dense packed data that is not plain `s16` arrays.  Reading `AAAp` is the next step here.
