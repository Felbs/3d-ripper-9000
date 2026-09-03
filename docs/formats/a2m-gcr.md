# A2M `.gcr` level archives + `TEXDIC` dictionaries - Scooby-Doo! Mystery Mayhem (2026-09-03)

Disc: Scooby-Doo!(tm) Mystery Mayhem (GC3E78), Artificial Mind & Movement 2003, over
RenderWare 3.4 (`rwcore.a`, `rpworld.a`, `rpskin.a`, `rphanim.a` in the link map).  66 `.gcr`
levels (385 MB) and 115 `TEXDIC_*.txd` (130 MB); the disc reported 9,532 triangles.
Implemented: `gcrip/formats/a2m_gcr.py`, `gcrip/plugins/a2m_gcr.py` (container), texture
hooks in `gcrip/plugins/renderware.py`.

## How it was read

The disc ships `engine_ret.elf` and its CodeWarrior `engine_ret.MAP` (6,013 functions).
`EFRessourcesMgr::LoadLevel` opens the level file with `DTStreamFAT` and walks a
`DTVector<DTFatRecord>`, creating each record's object through
`DTDynamicInstanciator::GeInfoByClsID`; the class ids come from the `__sinit_*` calls to
`RegisterDynamicClass(factory, name, id, type)`:

| id | class | id | class |
|---|---|---|---|
| 24 | `EFStatic3dObjRW` - the level, a RW WORLD | 91 | `EF3dObjRes` - a RW CLUMP |
| 79 | `EFHAnimRes` (RpHAnim) | 69 | `EFLogicCodeLib` - PPC ELF objects (`apitext`, `debug`) |
| 36 | `EFCollisionMap` | 39 | `EFLogicCodeGC` |
| 48 | `DTWaypointGrp` | 73 | `EFAnimRes` |
| 45 | `PLTypeRW` (particles) | 34 | `EFTextureDict` |

## `.gcr`

```
u32 0x1dbb4, u32 records, u32, u32 first data offset
record (16)   u32 offset from the table's end, u32 class id, u32 resource id,
              u32 memory size (not the extent: a record runs to the next offset)
```

Records are handed out sorted by offset; the world (class 24, resource -1) comes first and
the RW members are cut at their own chunk size.  Level EP1L01: 471 records - 1 world,
101 clumps, 294 animations, 41 + 11 code objects.

## `TEXDIC_*.txd`

Not an RW texture dictionary: a run of `RW IMAGE (0x18)` chunks, each followed by
`u32 name length, name`.  The image struct is `u32 width, height, depth, stride` (little
endian), then `stride x height` pixel bytes and, for 8-bit images, a 256 x RGBA8 palette
(4-bit: 16 entries); 32-bit images are RGBA rows.  The RenderWare plugin's texture index
recognises the form and, for members of a `.gcr`, looks across the level folder
(`level/EP1/L01/gen/EP1L01.gcr` -> `level/EP1/L01/EN/TEXDIC_0.txd`).

Level EP1L01: 102 scenes, 77,715 triangles, 188 of 240 materials textured (the rest name
HUD art from other dictionaries).

## Open

* Scaler (GKUE9G) and Scooby-Doo! Unmasked (G5DE78) are the next A2M engine: `.as` assets
  and `.htd` dictionaries, no RenderWare; their `engine_ret.elf` carries symbols but no map.
