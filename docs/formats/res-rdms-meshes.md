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

## `indx` is a name directory (2026-09-01)

Not an index of the text, which is what the tag suggests.  It names the other sections::

    u32 count
    u32 4
    then count entries of 12 bytes:
        u32  name offset    self-relative from this field, into `strg`
        char tag[4]         the kind of section referred to
        u32  delta          self-relative from this field, to the section itself

**Both offsets are self-relative** - `field position + value` - which is the same convention
`rdms` uses for its array offsets and the reason the earlier pass's base was wrong there too.
Measured from the `indx` section's start instead, **none** of Lemony Snicket's six names lands
on a string; measured from the field, all six do.

Every entry resolves to a section whose tag matches the entry's own - 6 of 6 on Lemony Snicket,
1 of 1 on Samurai Jack - and to a full asset path from the artists' tree:

    surf @  4096  menus/train_game/bobblehead_texture.tif
    node @ 63616  menus/train_game/fx_hud_bobblehead
    surf @ 12416  menus/train_game/fx_hud_mainframe.tif
    node @ 84128  menus/train_game/fx_hud_shelf
    node @ 89408  menus/train_game/fx_hud_target
    surf @ 91648  menus/train_game/target_texture.tif

That the tag has to match the section it points at is also the parser's check: a misread entry
drops out instead of naming the wrong thing.

`expand()` now uses those names, so a texture comes out as `000_surf_bobblehead_texture.bin`
rather than `000_surf_468.bin`.  The numbered prefix and the `_tag_` infix stay, because the
plugin screens members on `_surf_` and `_rdms_`.

**The index only covers a handful of sections** - 6 of Lemony Snicket's 25, 1 of Samurai Jack's
3 - so it names the assets the file was built from, not every section in it.

## Still open

The `node` sections hold the scene graph, so meshes come out one section at a time in their own
space rather than assembled into a level.  Colour arrays are read but not bound (they are a
single entry on nearly every section), and `surf` textures are not yet matched to the meshes
that use them.

### The nodes do reference their meshes (`res.node_links`)

By the format's usual **self-relative** offset - a word whose value plus its own position lands
on an `rdms` section.  On Lemony Snicket's file **all seven `rdms` sections are referenced,
each exactly once**, by the three nodes, so the nodes account for the whole geometry:

    node @63616  menus/train_game/fx_hud_bobblehead -> rdms 29184, 30144, 39552
    node @84128  menus/train_game/fx_hud_shelf      -> rdms 74368
    node @89408  menus/train_game/fx_hud_target     -> rdms 84992, 86016, 87040

The reference sits in a **52-byte record**::

    f32[6]   a min/max box, small and near the origin
    u32 0 | u32 1 | u32 1 | u32 4
    u32      the self-relative offset of the mesh
    u32      0x7f7fffff (FLT_MAX)
    u32 2

Both three-mesh nodes put their references at exactly +148, +200 and +252, which is what fixes
the stride at 52.

**The box is not the placement, and it is worth saying so plainly.**  Each record's six floats
are componentwise min < max, so they read as a box - but the box is about 0.3 units wide and
off centre, while the mesh it points at spans +-39 and is symmetric about the origin.  It is
neither the mesh's bounds nor any scale of them, and no uniform factor maps one onto the other.
A node section also carries `0x7f7fffff` - `FLT_MAX`, the usual bounding-box initialiser - and
repeated f32 triples such as `(-4.501, 0.408, 1.771)`, so the transform is somewhere in the
node; this record is not it.

What the links do buy is **grouping**: which meshes belong to one object, and through the index
that object's name.  `expand()` uses it, so the three parts of the bobblehead come out as
`004_rdms_fx_hud_bobblehead_436.bin`, `005_rdms_fx_hud_bobblehead_420.bin` and
`008_rdms_fx_hud_bobblehead_372.bin` instead of three unrelated numbers.  Assembling a level
still needs the transform.

## The textures bind (2026-09-04)

The `0xffffff1c`-looking word at `rdms` +4 is not a constant: it is the format's usual
**self-relative offset**, and it lands on a `gshd` section - the mesh's shader.  A `gshd`'s
word at +0x5c lands the same way on the `surf` it samples.  On Samurai Jack's level files
73 of 73 `rdms` resolve (`ladder`, `test_bridge`, `test_platforms`), and 71 of the 73 come out
textured - the two that do not sample a 4,128-byte `surf` with one mip level and no palette
bytes, which `res_surf` decodes to nothing.  `res.shader_textures` walks the two links,
`expand()` suffixes the mesh member with `_tNNN` (the surf's section index) and the plugin
binds the sibling `NNN_surf_*` member from the container.  Wave 58 re-rips the three discs.

## Characters are `bmsh`, not `rdms` (2026-09-04, open)

`characters/*.res` on Samurai Jack carry `surf`, `gshd`, **`bmsh`** (the skinned mesh, 7-95
KB), `body` (248 bytes: a bone / bind block with 4x4 identity-ish matrices) and `banm`
animations - no `rdms` at all, so the characters of all three discs are still unread.
`bmsh` opens `u32 batches, u32 8, f32 scale (1/4096), u32 6, u32 0x28, u32 0x70, 0, 1, 0,
u32, f32, 0` and then 0x28-byte batch records whose first word is a self-relative offset to
the batch's `gshd` (`0xfffffcb0` from +0x30 lands on the first shader) and whose +0xc / +0x1c
words reach tables near the section's end; after the records comes a bone-index list and
`s16` position data with x = 0 rows.  There are **no GX display lists** in a `bmsh` (no
`0x98` chains at any stride), so the triangles are an index list the CPU skins - the next
thing to find.
