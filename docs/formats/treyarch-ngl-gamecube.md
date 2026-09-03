# Treyarch NGL on the GameCube - Ultimate Spider-Man and Spider-Man 2 (2026-09-03)

Discs: Ultimate Spider-Man (GUTE52, `amalga_gc.pak` 332 MB) and Spider-Man 2 (GK2E52,
`amalga_gc.pak` 202 MB).  The whole game - city districts, characters, levels, cutscene
packs - sits in that one file, which no plugin opened; both discs reported under a thousand
triangles.  Implemented: `gcrip/formats/ngl_gc.py`, `gcrip/plugins/treyarch_pak.py`
(container), `gcrip/plugins/ngl_mesh.py` (models).

## How it was read

Ultimate Spider-Man ships `symbolgc-final.map`: a binary `SYM1` table of 26,808 symbols
(address, name range, size) covering the whole DOL.  With it every loader was read by name:

| what | function |
|---|---|
| the archive | `resource_manager::load_amalgapak`, `resource_amalgapak_header::verify` (five version words), `get_pack_file_stats` (entry offset + header `delta`) |
| a pack | `resource_pack_streamer::finish_data_read` -> `parse_generic_object_mash<resource_directory>` -> `resource_directory::un_mash_start`, `mashable_vector<tlresource_location>::custom_un_mash` (the mash pointer rules), `resource_directory::constructor_common` (offsets rebased per part), `tlresource_type_to_vector` |
| resource types | `resource_key::resolve_extension` - four platform tables of 70 extensions (`.GCT`, `.GCMESH`, `.GCMAT`, `.GCPACK`, ...) |
| mesh files | `nglLoadMeshFileInternal`, `nglRebaseMesh`, `nglRebaseSection` (every pointer in a mesh, section and draw block) |
| textures | `nglLoadTextureGCT` / `nglLoadTextureGCTv3` |
| skinning | `nglSkinSection`, `FastSkinS16` (a bytecode interpreter over paired-single loads) |
| name hash | `tlFixedString::tlFixedString(char *)` - `h = h * 33 + lower(c)` |

Spider-Man 2 has no map; its build is one engine generation earlier and differs only in
the directory records (28-byte names inline) and header word counts, told apart by the
first version word (`0xe` USM, `0xb` SM2).

## The archive

```
header   versions (5 words USM / 4 SM2), [USM: u32], u32 delta, u32 dir offset, u32 dir bytes,
         u32 locations offset, u32 locations bytes, ...
entry    USM 80: u32 id, u32 type (0x19 GCPACK), u32 offset, u32 size, 4 x u32, u32 index,
         u32 1, 2 x u32, char name[32]
         SM2 56: char name[28], u32 type (0x13), u32 offset, u32 size, 2 x u32, u32 index, u32 1
```

A pack is at `delta + offset`.  USM: 618 packs (194 two-letter city districts, `CITY_ARENA`
6 MB, `ULTIMATE_SPIDERMAN`, `VENOM`, `PK_*` mission packs, `S10_P2` level pieces).  SM2: 586.

## A pack

```
header   versions, u32 0, u32 dir offset (0x30), u32 data base, u32 part-1 end, u32 part-2
         bytes - the two parts are contiguous in the file
mash     u32 id, u32 flags, u32 bytes, u16 0xffff, u16 0, then the resource_directory object
         (0x2bc bytes USM, 0x20c SM2): mashable_vectors {u32 ptr, u16 count, u8 flags, u8}
         - parents, resources, one per tlresource type (11 USM / 8 SM2), [USM: groups, pools]
         - whose contents follow the object in order, each aligned to 8 and closed to 4
records  USM resource 16: hash, type, offset, size; tlresource 12: hash, size << 8 | type, offset
         SM2 resource 40: name[28], type, offset, size; tlresource 40: hash, name[28],
         size << 8 | type, offset
```

tlresource types: 1 texture (`GCNT` rasters and `.IFL` frame lists share it), 2 mesh file,
3 mesh, 6 material file, 7 material.  The container emits `<PACK>/<hash>[_<name>].gct`,
`.ifl`, `.gcmesh`, `.gcmat`.

## `GCNM` mesh files

Version 0x1f (USM) / 0x1d (SM2); every pointer is a file offset (the base word is 0):

```
header    "GCNM", u32 version, u32 entries, u32 directory (0x20), u32 base
entry     u8 kind (1 material, 2 mesh, 3 morph), u24 bytes, u32 object, u32 name
name      u32 hash, char[28]
material  u32 name, u32 shader name, u32, u32, u32 kind, ... texture-name pointers at
          kind-dependent offsets (the diffuse first: +0x18 for `usperson`, +0x60 for
          `smsimple` / `us_grunge`, ...) - any word past the shader that lands on a name
mesh      u32 name, u32 flags, u32 sections, u32 table {u32, u32 section}, u32 bones,
          u32 bind matrices (4x4 f32, row vectors, translation in row 3), u32 lods, u32 lod
          table, f32[4] centre, f32 radius
section   f32 radius, f32[4] centre, u32 vertices, u32 triangles, u32, u32, u32 draw block,
          u32 skin block, u32, u32 vertex def, u32 material name, ...
draw      u32, VAT A/B/C x 2, u16 extra lists, u16 attributes, u32, u32 attribute table
          {u8 GX attribute, u8, u16 stride, u32 array}, u32 rebase table {u32 count,
          u32 records (slot << 24 | base index)}, u32 list offsets, u32 list sizes,
          u32 VCD pairs {lo, hi} - one per display list
```

The display lists are plain GX (0x98 strips, 0x90 lists); the VAT gives the array formats
(positions F32 or S16 with fraction bits, colours RGBA4 / RGBA8 / RGB565, texcoords S16 /
U16 / F32).  A section past 256 array entries carries extra lists: before list *k* the
game rebases the CP array pointers by the record for *k* (slot = index into the attribute
table) and loads that list's own VCD pair - some lists switch an attribute to index16, which
is why the pair is per list.  Arrays interleave (a 24-byte record holds position, normal,
binormal, tangent), so element counts come from the corners, never from the gap to the
next array.  Materials in a district's mesh file are stubs (name + shader); the textures
are named in the district's `.gcmat`.

## Skinning

Characters keep no GX position array: the section's skin block lists 32-byte descriptors,
`u16 kind, u16 vertices, u32 source, u32 weights, u32 program, u32 GQR, ...`, and kind 6 is
`FastSkinS16`: 12-byte source records (s16 position with the GQR's fraction bits - 13 for
Spider-Man - and s16 normal / 16384) run through a program of u16 opcodes into the output
array the display list indexes:

| op | meaning |
|---|---|
| 1 `hh ll` | A <- bone `hh`, B <- bone `ll` |
| 2 / 3 `n` | A / B <- bone (low byte) |
| 4 / 5 `n` | the next n records by A / B |
| 6 `n` | the next n records blended A / B, one `u8 wA, u8 wB` a record from the weight stream |
| 7 / 8 / 9 `n` | n records *added* to an earlier output vertex: `u8 pair, u16 target` each |
| 0xa | end; 0xb / 0xc / 0xd / 0xf move locked-cache blocks |

The source records are already in model space (the bind matrices are inverted at load), so
the output positions are the T-pose; the program's bookkeeping gives every vertex its bones
and weights (up to four, sums of 1.0 on 2,028 of Spider-Man's 2,032 vertices).  Kind 1
descriptors are static attributes converted at load in place.  Bones become a flat skeleton
of the bind transforms.

## Textures

`GCNT` v3: `u16 data offset (0x40, 0x20 on SM2), u16 palette flag, u32 data bytes, u16 w,
u16 h, u8 GX format, u8 palette format (GX TLUT), u8 mips` at 8; the tiles at the offset,
the palette (16 / 256 entries) after them, or at 0x28 with its count at 0x20 when the flag is
set.  An `.IFL` is a text list of `name.tga` frames; the plugin binds its first frame by
name hash.

## Results (pulled packs)

| pack | scenes / triangles | textures |
|---|---|---|
| `ULTIMATE_SPIDERMAN` | 5 mesh files, 9,520 triangles, three LODs skinned over 66 joints, T-pose confirmed | 19 of 21 (`fake_shadow`, `generic_white` live in another pack) |
| `VENOM`, `PK_V02_WOLVERINE` | 12,352 / 11,009 | eyes through `.IFL` |
| `CITY_ARENA` | 266 mesh files, 46,141 | 606 of 643 (the rest `.IFL`) |
| districts (first 4 MB) | 36,355 | all in-pack materials bind; `uslod` materials are vertex-lit, no texture |
| SM2 `B10`..`E40` (first 4 MB) | 145 scenes, 51,754 | in-pack textures bind; shared ones resolve at rip time |

Every section of every sampled mesh lies inside its mesh's bounding sphere.  Both discs
are on the pass-7 title list (wave 41).

## Open

* City buildings are procedural (`SMProcBlgShader`, `lod_building_info`): the district packs
  hold facade textures and materials, not building meshes.  Not rippable as models.
* Morph entries (kind 3), animations (`.GCANIM`), skeleton hierarchy (`.GCSKEL` - the mesh
  carries only bind matrices).
* Skin kinds 2-5 and 7 (`Skin*Vecs32Norms32`, `FastSkinF32`, `FastSkinNBTF32`) were not met
  in the samples; they warn if they appear.
