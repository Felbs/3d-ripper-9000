# Point of View engine on GameCube: Smashing Drive `PHM` / `TIM` / `TG_` (2026-09-03)

Smashing Drive (Namco, Gaelco's arcade taxi game ported by Point of View) keeps its whole game
in inline `.wad` record streams (`gcrip.formats.toc_wad`, the Scorpion King variant: `name[16]
type[4] u32 size u32 user`).  The disc reported zero triangles: 4,517 `PHM` models and 2,290
`TIM` records across `COMMON.WAD`, `EXIBI.WAD` and ten `FASE_xx.WAD` phases.

The disc ships `smash.elf` with DWARF 1, and the loader keeps the file image as the runtime
struct - every pointer is a file offset (`ModelRemapHeader` adds the base).  The model comes
straight from `s_model`, `s_model_mesh`, `s_model_vertex`, `s_model_command`, `s_draw_material`,
`s_model_bone`, `s_texture_def` and `s_texture_header`.

Implemented: `gcrip/formats/pov_model.py`, `gcrip/plugins/pov_model.py` (models),
`gcrip/formats/pov_level.py`, `gcrip/plugins/pov_level.py` (phase layouts).

## `PHM` - `s_model` (256 bytes, the file header)

```
+0x08 u16 vertex flags, u16 vertex size (44)   +0x0c f32 radius
+0x10 centre[4]  +0x20 min[4]  +0x30 max[4]     (f32)
+0x40 u32 vertices, +0x44 ptr vertex list       s_model_vertex 44: f32 u, v; f32 coord[4];
                                                f32 normal[4]; u8 RGBA
+0x60 u32 materials, +0x64 ptr                  s_draw_material 144: 4 colours, f32 shininess,
                                                u32 flags, i32 maps[15] = texture-def indices
+0x6c u32 bones, +0x70 ptr                      s_model_bone 96: char[16] name, f32[16] local
                                                matrix, i32 parent, sibling, child, mesh
+0x74 u32 meshes, +0x78 ptr list of pointers    s_model_mesh 80: centre / min / max, u32 flags,
                                                f32 radius, u32 polygons, ptr u32 index list,
                                                u32 collision faces, ptr, ptr commands
+0xac u32 texture defs, +0xb0 ptr               s_texture_def 20: char[16] name, ptr
```

The commands are 8-byte `s_model_command` records - `u8 type, u8 parm8, u16 parm16, u32
parm32`: type 1 selects material `parm8`, type 4 draws a triangle strip of `parm32 + 2`
corners starting at index `parm16` of the mesh's **u32** index list (fans are strips with the
hub repeated, so the degenerate triangles drop), 0 ends the list.  Meshes take the name of the
bone that points at them (`RootBone`, `Bone0001` - the wheels of `TXHR_09`).

The index width was the trap: read as u16 every triangle touched vertex 0 and the taxi's wheels
came out as fans from the origin.  No magic either - `is_model` accepts zeros at 0..8, vertex
size 44, a finite radius and ordered bounds, all inside the 64-byte sniff (the vertex count at
+0x40 is outside it, which is why the first plugin build detected nothing).

## `TIM` - `s_texture_header`

64-byte headers at `64 * i`, the count sharing the first header's word 0: `u16 flags` at +4
(the low nibble of byte 5 is the GX format), `u16 width, height, depth`, `u32 image bytes`,
`u32 CLUT entries`, `ptr image`, `ptr CLUT`, `u32 CLUT format`, then the tiles and palettes.
`gcrip.formats.toc_tim` (Spawn) reads the same header as 16 bytes plus pixels; the POV reader
follows the pointers so palettes and second images resolve.  Materials bind by texture-def
name = `TIM` record stem, nearest wad first: 1,657 of 1,657 materials over `COMMON` + `FASE_11`.

## `TG_<phase>` - the layouts (no symbols: Gaelco's game code)

`SmashLoadPhase` asks the phase wad for `TG_%s` (`TG_FASE_11`); `RemapPmxObject` stores every
loaded `PHM` in a table keyed by the record id in the wad wrapper's fourth word
(`(word >> 16) & 0x3fff`).  Two headers:

```
phase   +0 u32 0x10, +4 ptr cells, +8 ptr extras, +12 0, +16 u32 sections,
        +20 (u32 route distance, ptr placements) a section
scene   +0 0, +4 u32 0x10, +8 ptr extras, +12 0, +16 u32 cells, +20 the cells
        (TG_INTRO_11, TG_FIN_11, and the last phase TG_FASE_41)
cell    f32 centre[3], f32 radius squared, ptr bounding boxes (32 bytes: min, max, 0, 1.0),
        ptr placements
list    u32 count, then 40 bytes a record: u16 kind, u16 sub, u16 record id | flags << 14,
        u16 param, ptr extras, f32 position[3], f32 axis[3], f32 angle
```

Cells place the props (lamps, containers, pedestrians - 607 in phase 1-1, all ids resolving);
sections place the traffic along the route (94 cars).  The buildings and road pieces
(`F11_230E`, 354 of the wad's 379 models) are never placed: they are already in world
coordinates, so the phase scene is every model of its wad nobody places plus the placed ones.
The rotation is axis-angle in row-vector form; with it 80% of the traffic faces along its
route (61% with the transpose).  Intro / ending / smog layouts export their placements only.

## Results

Phase 1-1 (`TG_FASE_11`): 133 cells, 55 sections, 701 placements, 354 world models, 63k
triangles, 349 textures, no warnings - a coherent street grid with skyline backdrops.  Phase
4-1: 248 cells, 1,932 placements, 627 world models, 196k triangles.  All ten phases parse.

## Open

* Spawn: Armageddon and The Scorpion King run the same engine with other `s_model` versions
  (Spawn's vertices are 64 bytes; the Scorpion King's pointers sit elsewhere) - the existing
  `plugins/phm.py` reads those by arithmetic; this layout could pin its header table.
* The `_A` `BIN` records are the animations (`s_hanim`), and `POL01` / `UNV01` the collision.
