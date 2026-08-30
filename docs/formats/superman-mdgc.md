# `MDGC0200` (Superman: Shadow of Apokolips) - block format mapped

255 `.dgc` files, disc reports zero models and zero textures.  Nothing to do with the TotemTech
`.dgc` of Spirits & Spells - the extension is shared, the format is not.

**Not compressed**: entropy 3.74 on a script file and 5.27 on the biggest level, against 7.7+
for genuinely compressed payloads.  So unlike High Voltage's `GMS`, everything here is readable
in place.

## File header

    +0   char magic[8]   "MDGC0200"
    +8   u32 size        (0x59aea0 = 5,877,920 on a 6,124,240-byte file)
    +12  u32
    +16  u32 count
    +20  u32 0x1007      the block type tag, repeated per block

Small files are scripts - `L08LinkD.dgc` is full of readable handler names,
`<handle>::hOnCreate`, `<handle>::hWalkToFailed`, `<handle>::hTakeDamage`.  The tag word at 0x24
splits the set: 155 files carry `00000004`, 72 carry `00001019`, and 28 carry `SUP\x03` /
`SUP\x16`.

## Mesh blocks

A block begins with a 64-byte header whose second word is **`0x1007`**, and the useful fields
are:

    word5  corner count
    word6  vertex count
    word7, word8   repeat the corner count

then, immediately after the header:

    n  x  3 x f32 big-endian     vertex positions
    c  x  RGBA                   per-corner colours (c = word5, not n)
    c  x  3 x s8                 per-corner normals

Sizes confirm each other: on the block at 0x29c2c, `word6` = 33 vertices and `word5` = 45
corners, the colour run ends exactly 45*4 bytes after the vertices, and the s8 run that follows
reads as unit-ish normal triples (`ff fb 0f`, `f5 fb 09`, `f1 fb ff`).  45 corners is 15
triangles over 33 vertices, which is a sane ratio for a closed mesh.

Two blocks 260 KB apart share a byte-identical 64-byte header apart from an id word, and their
`word6` values (0x210 = 528) match their float runs exactly (1,584 floats = 528 triples).

**Yield so far:** 78 blocks and 9,328 vertices in the first 3 MB of `L95.dgc` alone, and that
file is 6 MB of 255.  Bounding boxes are sensible room and prop shapes
(-45..44, -42..47, -134..138).

## The index list - FOUND, and it is a GX display list

It was never a bare index array, which is why searching for one failed: `w11` points at a
**GX display list**.  `0x98` - the triangle-strip opcode - is what gives it away.

    u8 opcode | u16 vertex count | count * 6 bytes

and a display-list vertex is three big-endian `u16`: **position index, colour index, normal
index**, with `0xffff` for an attribute the block does not use.  On one block
`98 00 04 | 00 17 00 a2 00 a2 | ...` reads as a four-vertex strip whose first corner is vertex
23 of 75 and corner 162 of 163 - both in range, which is the check that confirms it.

Two things are found rather than assumed.  The list does **not** start at `w11`: a sub-header of
varying length sits in front (40, 52 and 56 bytes on the three blocks measured), so the reader
scans forward for the first opcode from which the whole list walks.  And the walk proves itself
- on two of three blocks it consumes the bytes up to the next block exactly (22 strips / 137
triangles, 260 strips / 618 triangles), and no position index ever exceeds the vertex count.

Strips stitch their runs by repeating a vertex, so ~12% of the expanded triangles have zero
area; those are dropped as an artefact of the encoding.

## SHIPPED

`gcrip/formats/mdgc.py` + `gcrip/plugins/mdgc.py`.  Whole disc: **14 of 255 `.dgc` yield
geometry -> 947 meshes, 89,023 vertices, 130,937 triangles**, on a disc that reported zero.
The other 241 files are scripts and other block types.

Sanity check beyond the counts: the span-to-median-edge ratio is **10.8**, which is what a
coherent mesh measures; noise measures in the thousands.
