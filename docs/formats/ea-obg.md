# EA `OBG` terrain - Tiger Woods PGA Tour

The `ter` members of the `SHOC` archives ([ea-shoc-hog.md](ea-shoc-hog.md)), 55 MB across the
four discs.  `gcrip/formats/ea_obg.py` + `gcrip/plugins/ea_obg.py`.

Same convention as its sibling `TXG`: `char tag[4]` then a `u32` size that **excludes** the
eight-byte header.  Read the SHOC way the walk stops on chunk one; read this way it lands
**exactly** on the member's last byte - 4,655 chunks on the first one sampled, to the byte.

    OBG   char magic[4] "OBG " | u8 version[4]
    ARRA  a typed array          5 per member
    HEAD  56 bytes
    ELHE  an element header      2,794
    ELDA  an element's indices   1,855

## The array header

An `ARRA` payload opens with two words that describe it:

    u32  (type << 24) | count
    u32  components << 18

so the chunk is `8 + count * components * 4` bytes - which holds on **143 of 144** arrays
across 48 members.  Each member carries one `(type 2, 3 components)` `f32` array: the
positions.  On the first member that is 64,951 vertices spanning x -2948..2948, y -414..3250,
z -2948..2948 - a golf hole in world units.

## The strips, and the 0xffff that looked like corruption

`ELDA` holds big-endian `u16` **triangle strips** after an eight-byte header.  1,815 of the
1,855 index cleanly inside the vertex array; the other 40 reach exactly **65,535**, which read
as an overrun and is in fact the **primitive-restart marker**.  Splitting on it instead of
clamping is the difference between 40 broken elements and 40 correct ones.

Strips alternate winding, and the restarts leave degenerate triangles behind, so both are
handled: every triangle with a repeated index is dropped.

## Yield

Twelve archives of Tiger Woods 06 - the disc has 276 - give **28 scenes and 4,814,090
triangles** from 450,336 vertices.

Two honest limits.  Only 28 of the 89 `OBG` members in that sample produce a scene; the rest
have no finite `(type 2, 3)` array or too few triangles, and what those hold instead is not yet
known.  And **2003, 2004 and 2005 carry no `OBG` at all** in their first twelve archives, the
same way they carry no `TXG` - their content sits somewhere else on the disc, which is the next
question for those three.
