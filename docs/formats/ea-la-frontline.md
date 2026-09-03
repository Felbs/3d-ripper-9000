# EA Los Angeles 2002 - Medal of Honor: Frontline `.msh` / `.cpt` (2026-09-03)

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

## Rising Sun and GoldenEye: Rogue Agent

The 2003 / 2004 discs keep the same file names but their `.msh` (version 0x12) and `.cpt`
(0x25) wrap **EAGL** objects (`EALA::EAGLLoader::LoadFromMemory`, `EAGL::Model`), and their
`level.viv` also ship 744 / 841 plain `.o` EAGL objects.  `gcrip/formats/eagl.py` finds the
packets but not their streams: the packet threads `__COORD4` light-block externs, the TAR
and the GeoPrimState between the streams, the positions are S16 (6 bytes), texcoords S16,
normals f32 x 4, a per-vertex u8 matrix-slot stream, and the display list opens with a u32
primitive count before the first 0x98 - corners are `u8 slot, u8 position, u16 normal,
u8 uv`.  Open: an EAGL "EA LA 2004" packet path.

## Open

* `.dmf` skinned meshes (`CDMesh::Init`: s16 position / normal / uv arrays at +0x60 /
  +0x68 / +0x70, parts at +0x3c, cluster matrices) and `.skl` skeletons.
* Rising Sun / GoldenEye EAGL packets (above).
* Medal of Honor: European Assault (2005) is different again (`.rez`, `.hab`).
