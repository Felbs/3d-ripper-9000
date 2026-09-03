# A2M `.ghr` levels, HG objects / worlds and `.htd` dictionaries - Scooby-Doo! Unmasked, Scaler (2026-09-03)

Discs: Scooby-Doo! Unmasked (G5DE78, 121 `.htd`, 79 `.as`, the `.ghr` levels) and Scaler
(GKUE9G, 18 `.ghr`, 144 `.htd`), Artificial Mind & Movement 2004-05, the engine after
Mystery Mayhem's RenderWare one ([a2m-gcr.md](a2m-gcr.md)).  The discs reported 1,409 and
2,811 triangles.  Implemented: `gcrip/formats/a2m_hg.py`, `gcrip/plugins/a2m_hg.py`.

## How it was read

Both discs ship `engine_ret.elf` with a symbol table (no map).  The level archive is the
same `DTStreamFAT` as the `.gcr` (`EFResourceMgr::LoadLevel`), class ids from the
`RegisterDynamicClass` calls in the `__sinit_*` functions: 24 `EFStatic3dObj` (the world),
91 `EF3dObjRes` (objects), 79 `EFHAnimRes`, 69 `EFLogicCodeLib`, 100 `EFDynamicGeometryMgr`.
The records are `DTBinaryPersistStream` serialisations - every field goes through the
stream's virtual `LoadData` slots (`__vt__21DTBinaryPersistStream`: +0x0c char, +0x14 s16,
+0x18 s32, +0x20 u8, +0x24 u16, +0x28 u32, +0x30 f32, +0x6c bytes), packed big-endian - so
the reader is a transcription of `EF3dObjRes::Load3dObj`, `EF3dObjLODRes::Load3dObjLOD`,
`EFSkinSurface` / `EFRigidSurfaceGroup::LoadFromStream`, `HGDynamicSurface_SP::LoadFromStream`
/ `ImportMaterials` / `ImportSubSurfaces` / `ReadMaterial` / `ReadVertex`,
`EFStatic3dObj::LoadFromStream`, `EFSpace::LoadPVSFromStream`, `EFEnvCloneMgr::LoadFromStream`,
`HGStaticSurfaceContainer::LoadFromStream` / `ImportMaterials` / `ImportSurfaces`,
`HGStaticSurface_SP::LoadFromStream` / `ReadVertex`, `HGTextureDictionary`, `HGTexture_SP` and
`HGPalette::LoadFromStream`.

## Records

```
object   u8 n, path (z:\...\sd_scoobydoo_ref); u8[12]; u16; u16 bones; u16 LODs; u16 has
         matrices; u8[16]; bones x (f32[16] local matrix (row vectors, translation in row 3),
         u16 parent, u16 child, u16 sibling, u16, u32); [bones x f32[16] inverse bind];
         [(LODs - 1) x f32 distance]; u16; LODs x (u16 skins x (u16 n, u16[n] bone list,
         dynamic surface), u16 rigid bones, [u16[n] bone list, dynamic surface])
dynamic  u32; u32 materials x (u8[4] colour, f32[3], u32 vertex flags, u32 pipeline, u32
surface  textures x (u32, char[32])); u32 sub-surfaces x (u32, u32 material, u32 vertices x
         vertex; rigid: u32 strips, u16[strips] lengths, f32[4] a strip, u16 n, u16[n]
         corner order, u32 bytes, GX list; skinned: either the same strips + order, or u16 n
         triangles x u8[20] (three u16 corners), u16 m, u8[8 m]); u32 n, u8[8 n]
vertex   by the material flags: 1 f32 xyz, 2 f32 normal, 4 RGBA8, 8 f32 st, 16 f32 st
         (dropped), 32 f32[4] weights + u8[4] bone slots into the surface's bone list
world    u8[12]; u16 nodes, u16 leaves, u32; PVS: u32, u8[0x38], u8[(nodes - leaves) x
         leaves], u32; env clones: u16 a, u16 b, (a + b) x (u32, f32, f32, dynamic surface),
         u16 c, u16 d, u8[0x50 c], u32[3 d]; nodes x (f32[6] bounds, u8[4], u16); static
         container: u32 materials, u32 surfaces, materials (as above, the pipeline word
         unused), surfaces x (u32 groups, u32, groups x (u32 material, u32 n, n x (u32 skip
         | rigid sub-surface)))
.htd     u32 palettes, u32 textures; palettes x (u32 entries, u32 words an entry, entries);
         textures x (char[32] name, u32 w, u32 h, u32 GX format (6 RGBA8, 14 CMPR), u32,
         tiles)
```

The GX list of a rigid sub-surface repeats one index for every attribute, so the strips
over the corner-order list are the triangles for both forms.  Positions are metres in bind
pose; skins carry weights and bone slots, rigid groups list the bone they hang from.  The
skin pipeline with triangle records (`HGPipelineMgr` flags) is told from the strip form by
whether the strip lengths sum to the corner count that follows.

## Results

Unmasked W1L3 (Chinatown): 80 scenes, 59,833 triangles, 378 of 399 materials textured -
Shaggy 1.7 m in a T-pose with 32 bones, a 42k-triangle world with its skydome.  Scaler
LEVEL01: 60 scenes, 67,535 triangles, 109 of 121 textured.  Textures: `gen/TEXDIC.htd`
beside the archive first, then the language folders' `LoadNTSC.htd` / `FONTDIC.htd`.

## Open

* The environment clones inside the world (31 / 34 dynamic surfaces) parse but their
  placements (the 0x50-byte records) are not read, so they are not exported.
* `EFDynamicGeometryMgr` (class 100) models and the `.as` files (`u32 0x58`, then s16 runs
  - animation streams by their `Cut_*` / `Zombintr` names) are not read.
