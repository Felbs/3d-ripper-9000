# EA Los Angeles 2002-04 - Medal of Honor: Frontline / Rising Sun, GoldenEye: Rogue Agent `.msh` / `.cpt` (2026-09-03)

Disc: Medal of Honor: Frontline (GMFE69): 1,918 `.msh` static meshes (50 MB) and 247
`.cpt` level compartments (180 MB) inside the per-level `level.viv` / `comp.viv`, plus 608
`.dmf` skinned character meshes and their `.skl` skeletons.  The disc reported 2,347
triangles (the gx scanner on a few `.asf`).  Implemented: `gcrip/formats/ea_la.py`,
`gcrip/plugins/ea_la.py`.

## How it was read

`Moh2RelGC.elf` ships 5,005 named functions.  `CStaticMesh::Init` and `CCompartment::Init`
walk their tables with `offsetPtr<T>` (every pointer is a file offset), build each chunk's
GX display-list header in place (CP array bases and strides for positions, normals, colours
and texcoords - the 0x34 bytes ahead of the corner records are zero on disc) and initialise
the materials' textures from the `SHPG` shape embedded at material +0x60
(`GXInitTexObj` from the shape's block code: 0x1e CMPR, 0x16 RGBA8, 0x17/0x18 paletted).
The vertex formats come from `CMSHMatBin::Link` / `CCPTMatBin::Link`: positions F32,
normals S8, colours RGBA8, texcoords F32.

## `.msh` (version 9)

```
u32 9, u32 bytes, u32 materials A, count, u32 materials B, count, u32 chunks, count,
u32 nodes, count, u32 attach nodes, count
material 0x70   +0x60 SHPG offset, +0x64 flags, +0x6c shared index (flags bit 1)
chunk 0x20      u32 node, u32 material, u32 data
data            u32 flags (bit 0 u8 indices, bit 2 strip), u32, u32, u32 vertices,
                u32 positions, colours, normals, uvs, display list
display list    0x34 zero bytes, then vertices x (position, normal, colour, uv) indices,
                u16 or u8 each
node 0x60       chunk list, bounds - no transform; meshes are in model space
```

## `.cpt` (version 0x11)

The same shape with a 0x14-byte chunk (`node, _, material, data, _`) and a data block of
`u16 flags (bit 0 u16 indices), u16 vertices, u32 positions, colours, normals, uvs,
display list`; strips only.  A level's `<n>_ART.cpt` in `level.viv` carries the materials
and no chunks; the `<n>_ART_c<k>.cpt` compartments in `comp.viv` carry the geometry, in
level space, and their materials point back into the art file's tables (flags bit 1, index
at +0x6c into the same table, A or B).  The plugin looks the art file up by level name.

Level 1_1 sampled: `level.viv` 59 meshes / 30,177 triangles, `comp.viv` 7 compartments /
101,833 triangles; 1,172 of 1,289 materials textured (a U-boat, a village with terrain).

## Rising Sun and GoldenEye: Rogue Agent (closed 2026-09-03)

The 2003 / 2004 discs keep the file names but their `.msh` (version 0x12) and `.cpt` (0x25)
wrap **EAGL** objects (`EALA::EAGLLoader::LoadFromMemory`), and their `level.viv` also ship
744 / 841 complete `.o` objects (characters, hands, weapons).  Implemented in
`gcrip/formats/eagl.py` (`_decode_packet_la`, chosen by the `Moh3_` shader prefix),
`gcrip/formats/ea_la.py` (the wrappers) and `gcrip/plugins/ea_la.py`; the `.o` objects go
through `gcrip/plugins/eagl.py`, which now accepts `.o` and indexes `.csf` shape files.

### The wrappers

The ELF inside a `.msh` / `.cpt` is the `.ord` half only - header and `.data`, no symbol or
relocation tables.  `CStaticMesh::Init` calls `TLT_GetRelocationTable(id)`, which looks the
`u32` at `.msh` +0x34 up in the level's `symbols.rtc` (`data\%d\%d_%d\symbols.rtc`,
`CRtcFile::GetRelocationTable`): `"RTC\0", u32, u32 2, u32 bytes, u32 count, u32 count`,
then `count x (u32 id, u32 offset, u32 bytes)` sorted by id.  Each entry is the rest of the
ELF - `.shstrtab`, `.strtab`, `.symtab`, `.rel.data` and the section headers - and joins by
plain append (`e_shoff + e_shnum * 40 == ELF + tail`).  A `.cpt` holds one or more ELFs
(scan for `\x7fELF`; header words 21-25 list them on some files, not all) whose tails are
entries 0, 1, ... of the `<name>.rtc` beside it in `comp.viv`; its words 2-3 point at an
embedded `SHPG` bundle - the level's `_Art.cpt` carries 83 textures that way, a compartment
sometimes its own.

### The packets

Same ELF packet entry list as FIFA's, threaded through `__EAGL::LightBlock` /
`__COORD4` externs, and the streams are indexed **separately** - positions, normals and
texcoords of one packet have different counts:

```
1 @header      u32 display-list corners (Rising Sun: as written; GoldenEye: of one merged
               strip = corners + primitives - 1), u32 normal count (GoldenEye), 0, 0
skin table     1 or 10 rows of 4 f32 weights, bone index in the low byte (as FIFA)
streams        counted pointers; element size from the gap to the next pointer (streams pack
               on 4-byte boundaries): 6 s16 positions, 3 s8 normals, 4 RGBA8 colours or s16
               texcoords (the first 4-byte stream is the colour unless the shader is a skin),
               16 f32 x4 normals (GoldenEye, lit on the CPU with pNrmMatrices), 1 the
               per-normal matrix slots
constants      count-1 pointers behind the GeoPrimState / TAR: COORD4 (the compartment
               origin on Cpt_ shaders), 16 zero bytes, u32, a 4x4 matrix
display list   not pointed at - it starts right behind the last stream / constant
```

Corners: Rising Sun `[posmtx slot u8 (skins)] [pos] [nrm] [clr] [uv0] [uv1 ...]`, GX order,
u16 where a stream has more than 256 entries; GoldenEye `[slot] [pos] [clr] [nrm u16] [uv
...]`, the normal index always two bytes, repeated on the `Skin_EnvMap` / `Skin_Specular`
shaders.  The decoder ranks the element-size assignments by padding, then takes the first
opcode behind the streams whose chain at some stride reads the header's corner count with
every index inside its stream.  Vertex formats from the shipped ELFs' `RenderMoh3_*`
(`SetAttributeFormat`): positions s16 with 8 fraction bits on `Msh_`, u16 / 8 plus the
origin on `Cpt_`, s16 / 10 on `Skin_`; texcoords s16 / 10; s8 normals / 64.

Rising Sun 1_16: 22 `.msh` / `.cpt` + 8 `.o` -> 30 scenes, 47,913 triangles, 571 of 610
primitives textured (the USS Oklahoma at 10.5k triangles, a 22k-triangle compartment,
heads and bodies at human scale); GoldenEye 1_99: 22 scenes, 7,671 triangles (the melee
hands, a grenade, shell casings).  Textures come from the level's `.gsh` / `.csf` shape files
and the `_Art.cpt` bundle, looked up across `level.viv` / `comp.viv` / `symbols.rtc` in one
level folder.

## Open

* `.dmf` skinned meshes (`CDMesh::Init`: s16 position / normal / uv arrays at +0x60 /
  +0x68 / +0x70, parts at +0x3c, cluster matrices) and `.skl` skeletons (Frontline).
* Rising Sun / GoldenEye skeletons: `Human.skel.o` is an EAGL object with a `__Skeleton`
  of another header (`0284 02b2 c514 ...`), the `.skel.o` beside a mesh is not an ELF; the
  skins rip in bind pose without joints.
* About half of a Rising Sun compartment's materials name shapes (`l~8G`) that are in
  neither the level's shape files nor its art bundle - a shared texture file elsewhere.
* Medal of Honor: European Assault (2005) is different again (`.rez`, `.hab`).
