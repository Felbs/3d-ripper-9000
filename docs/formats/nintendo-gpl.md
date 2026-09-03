# Nintendo SDK character pipeline `.gpl` geometry palettes (2026-09-03)

The Dolphin SDK's "character pipeline" (`charPipeline`: GeoPalette, DisplayObject, Actor,
TexPalette) shipped with several early-generation GameCube titles, each keeping the SDK's
file formats: `.gpl` (geometry palette), `.act` (actor: bone tree placing display objects),
`.anm` / `.skn` (animation, skin) and the ordinary `.tpl` texture palettes.  Two `.gpl`
version tags are in the library:

| version | discs (loose `.gpl` count) |
|---|---|
| `0x005bbc61` | Harvest Moon: A Wonderful Life (402 in U8 `.arc`), Another Wonderful Life (169), Zatch Bell! Mamodo Fury (41) |
| `0x00b749e0` | Def Jam Vendetta (558 - the disc reported **zero** triangles), Doshin the Giant (532), Lotus Challenge (413, Kuju's own layout - not read), Ultimate Muscle (66), Swingerz Golf (58), PoolEdge (688), Universal Studios Theme Parks Adventure (32) |

Implemented: `gcrip/formats/nin_gpl.py`, `gcrip/plugins/nin_gpl.py`.

## Layout

Every pointer inside a display object is an offset **from that display object**; the
palette's own pointers count from the file start.

```
GEOPalette      u32 version, u32 user data size, ptr user data, u32 descriptors, ptr table
GEODescriptor   ptr display object, ptr name
DOLayout        ptr position hdr, ptr colour hdr, ptr texture hdr, ptr lighting hdr,
                ptr display hdr, u8 texture channels, u8, u16
array header    ptr array, u16 count, u8 quantize (GX type << 4 | fraction bits), u8 comps
                texture header adds: ptr palette name ("ban_0.tpl"), ptr runtime palette
DODisplayHeader ptr primitive bank, ptr state list, u16 states
DODisplayState  u8 id, u8, u16, u32 setting, ptr GX display list, u32 bytes
```

State ids: 1 = texture (setting `0x1111000N` / `0x1511000N`, N the image index in the
palette); the vertex descriptor is id **2** on `0x005bbc61` files and **3** on
`0x00b749e0` ones (the other id is the matrix load) - two bits an attribute in GX order
(position matrix, position, normal, colour 0, colour 1, texcoord 0-7): 2 index8, 3 index16.
A state's display list (when it has one) runs under the states set so far; corners hold
one index per indexed attribute.  Harvest Moon's `0x005bbc61` files interleave positions
and normals in one 12-byte array (both headers say 6 components, the normal header 6 bytes
in); the `0x00b749e0` files keep separate arrays.  Colour arrays: GX colour type in the
quantize nibble (1 = RGB8, 5 = RGBA8, 0 = RGB565, 3 = RGBA4).

Textures: the palette named in the texture header, nearest copy first; Harvest Moon's
characters name a palette that does not exist (`ban_0.tpl`) and split the images over the
`.tpl` files beside the model (`ban_0_b0`, `ban_0_f0_e` ...) - the indices count through
those in name order.

## Results

Harvest Moon `ban_0` (a villager): 4 draws, 2,515 triangles, 1.6 m tall in a T-pose, all
four textures bound.  Doshin `bil50`: a building, 130 triangles, 4 textures.  Def Jam
Vendetta's wrestlers are one `.gpl` a body part in bone space (`s004b_m3-R_hand_N`).

## Open

* `.act` actors: 28-byte bones (orientation control, prev / next / parent / child, u16 bone
  id, u16 display object id, inheritance, priority) placing the display objects - Def Jam's
  parts and Harvest Moon's skins rip in bind pose without them.
* Lotus Challenge's palettes start `version, materials, material table, user data size, user
  data, descriptors, table` with a 7-pointer display object; refused with a clear error.
