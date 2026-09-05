# Ubisoft on GameCube - engine map (census 2026-08-29, nothing decoded yet)

## Unreal Engine 2 (Ubisoft Shanghai / Montreal / Red Storm GC builds) - 10 discs

Status 2026-08-29: `gcrip/formats/unreal.py` + `gcrip/plugins/unreal.py`.

- **Packages**: standard UE2 header `u32 magic 0x9E2A83C1 | u16 licensee << 16 | u16 version |
  u32 flags | name count / offset | export count / offset | import count / offset | GUID |
  generations`.  Byte order follows the magic (`9e 2a 83 c1` big-endian, `c1 83 2a 9e`
  little-endian).  Compact index = first byte sign 0x80 / more 0x40 / 6 bits, then 7-bit
  bytes with more 0x80 (the umodel convention; getting the two flag bits swapped makes every
  table look like garbage after the first entry).  Tagged properties: `name | u8 info (type
  low 4 bits, size code bits 4-6, array / bool-value bit 7) | [struct name] | size | value`;
  bools carry the size field (0) but no payload.
- **Versions seen**: Splinter Cell 1 / Pandora Tomorrow v102 licensee 33; Ghost Recon 2 v129
  licensee 26 (Red Storm, little-endian); XIII v100 licensee 58 (big-endian).
- **Pandora Tomorrow** (GT7E41) ships `dataGCN/Staticmeshes/*.usx` (28, 96 MB) and
  `dataGCN/Textures_TF/*.utx` (74, 55 MB) uncompressed and little-endian = PC-layout data.
  StaticMesh export = properties (`Materials` array of {EnableCollision, Material},
  `OnlyForCollision` on hulls) | bounding box f32[6] + u8 | sphere f32[4] | `index n` vertices
  of 32 bytes `f32 pos[3] | f32 normal[3] | f32 uv[2]` | `u32 2 | index n` u16 triangle-strip
  indices (degenerate repeats) | `u32 4 | index n` u16 wireframe edges | `u32 2 | index n`
  sections `u32 | u16 first index | u16 min vertex | u16 max vertex | u16 faces | u16 strip
  triangles | u32 | index material (import)` | collision tree.  Texture export = properties
  (`Format` 0 P8 / 3 DXT1 / 5 RGBA8 / 7 DXT3 / 8 DXT5, `USize`, `VSize`, `Palette` object) |
  `index mips` x (`u32 skip | index size | data | u32 usize | u32 vsize | u8 ubits | u8
  vbits`); DXT blocks are PC order (`gcrip/formats/dxt.py`), P8 palettes are `index count`
  BGRA colours.  Materials resolve through the import's package name -> `<package>.utx`
  anywhere on the disc.  Disc census: 28 .usx -> 4,798 static meshes / 445k triangles, 74 .utx -> 11,675 textures, 5,507 of 7,032 materials bound (the rest are Shader / Combiner materials, open), 6 s.
- **`.umd` / `.lin` archives** (SC1 `System/warlins.umd` 197 MB = 36 maps, Chaos Theory /
  Double Agent / Rainbow Six 3 / Ghost Recon 2 `.lin`, XIII `warlins.umd`): segments of
  `u32 0x18000 (uncompressed block size) | u32 compressed size | zlib`, each segment ended by
  a `(0, 0)` pair and the next starting 2 bytes later (not 4-aligned); Chaos Theory / Double
  Agent blocks are `u32 0 | u32 csize | zlib`.  A segment inflates to entries `u32 hash |
  FString name (0_0_2.unr, Index.unr, Abstract.u, Engine.u ...) | 0x6818-byte level summary
  | package`.  `plugins/unreal.py` expands them to the member packages.
- **Loose `.tga` loading screens** (Chaos Theory 462 on disc 1, Double Agent the same
  layout: `screens/<lang>/*_loading*.tga`, `SaveLoadScreens/*.tga` - type-1 color-mapped
  TGA, 256 x 24-bit palette, 8 bpp, 640x448/640x96): real Truevision TGA, decoded by
  `gcrip/formats/tga.py` + `gcrip/plugins/tga.py` since 2026-09-04.  Before that nothing
  claimed them and the `gx` fallback scanned their pixel data into 51 noise meshes per
  disc - the GCJE41 quality-audit finding (see
  [quality-audit.md](quality-audit.md)).
- **Open**: the big-endian map packages (SC1 `.unr`, Pandora `.lin`, XIII) parse names fine
  but their import / export tables are not the standard layout (regular 8-byte-ish records
  such as `fd 34 ff ce fe 07 00 00`; not compressed - entropy 6.1); Ghost Recon 2's
  `gcngame.umd` is script-only, its geometry is inside the `.lin` maps; Chaos Theory / Double
  Agent `.lin` need the single-block variant checked; SkeletalMesh / Mesh (LodMesh)
  serialisation for characters.

## OpenSpace / CPA (Ubisoft Montpellier) - Rayman 3, Rayman Arena (ripped 2026-08-29)

`gcrip/formats/openspace.py` + `gcrip/plugins/openspace.py`; layouts from raymap
(github.com/byvar/raymap: GeometricObject.cs, GeometricObjectElementTriangles.cs,
SuperObject.cs, TextureInfo.cs, LVL.cs) verified on the discs.

- Files: `<level>.lvl` (big-endian memory image, one header u32 then the image; pointer
  positions are relative to lvl + 4), `<level>.ptr` = `u32 count | count x (u32 target file,
  u32 position)` then 16-byte fill-in records; target file 0 = `fix.lvl`, 1 = the level, 2 =
  `transit.lvl`.  A pointer value is an offset into the target file (+ 4).  `*kf.lvl` =
  keyframe animations, `*_vb.lvl` = empty vertex-buffer stubs, `transit.lvl` = tiny.
- Level header: texture table = pointers to TextureInfo records (`u16 height +0x1c | u16 width
  +0x1e | ... | name +0x4a` e.g. `knagrott\dead_head.tga`) followed by one u32 per texture =
  TPL file id: Rayman 3 2 -> `<level>_lvl.tpl` (94 of 94 entries in knaar_10), 6 ->
  `<level>_trans.tpl`; Rayman Arena keeps every entry in `<level>.tpl` preceded by two
  extra images.  The plugin aligns table order to TPL order by image size (DP) because a few
  textures are downscaled on the console.
- SuperObject (0x3c): `u32 type (1 world, 2 perso, 4 sector, 8 physical object, 0x20 / 0x40
  IPO) | data | first child | last child | u32 children | next | prev | parent | matrix |
  static matrix | i32 | u32 draw flags | u32 flags | u32 | bounding volume`.  Matrix = `u32
  type | f32[16] row-major with the translation in row 3 (row-vector convention) | f32[4]
  scale`; global = local @ parent.  Rayman 3 knaar_10: 373 super objects (190 perso, 140
  IPO, 22 sectors, 21 worlds).
- IPO: `physical object | radiosity | 4 x u32 | portal camera | 3 x u32 | name[0x32]`;
  PhysicalObject: `visual set | collide set | bounding volumes`; visual set: `u32 0 | u16 LOD
  count | u16 type (0 = GeometricObject) | LOD distances | LOD data pointers`.
- GeometricObject (Rayman 3 GC): `vertices | normals | blend weights | i32 | element types |
  elements | i32 | parallel boxes | u32 look-at | u16 vertex count | u16 element count | u16 |
  u16 boxes | f32 sphere radius | f32 centre[3] | i32 | i32 | i16`; Rayman Arena has no i32
  after the blend weights.  Vertices / normals f32 x y z, Z up (exported as x, z, -y).
- Triangle element (type 1, 0xb8 bytes on GC): `material | u16 triangles (0 on GC) | u16 uvs
  | u16 uv maps | i16 lightmap | triangles | u32 (Rayman 3 GC only) | uv mapping | normals |
  uvs | 3 x u32 | u8 visible | u8 | u16 mapping entries | mapping vertices (u16) | mapping uvs
  (u16) | u16 strip length | u16 disconnected triangles | strip (u16) | disconnected (u16 x
  3) | name[0x34]`; strip / disconnected indices address the mapping arrays.
- VisualMaterial: `u32 flags | colours ... | u32 texture count +0x64 | texture entry +0x68 ->
  TextureInfo`.  TPL images decode through `gcrip/formats/tpl.py` (Nintendo SDK TPL, magic
  0x0020AF30; CMPR mostly).
- Disc census 2026-08-29: Rayman 3 113 .lvl -> 59 levels / 5,751 placed instances / 1.65 M triangles / 1,495 textured materials (6 s); Rayman Arena 53 .lvl -> 33 levels / 2,754 instances / 336k triangles / 205 textured materials.
- Open: characters (Perso super objects -> families / object lists with bone hierarchies and
  `*kf.lvl` animations), textures that live in `fix.tpl` (file id 0 in Rayman 3), `.hxg` /
  `.hxd` sound.

## Jade (Ubisoft Montpellier)

Beyond Good & Evil and Prince of Persia: Sands of Time / Warrior Within / The Two Thrones
already rip through the jade plugin (`files/prince.bf` BIG file -> ~2.5k `.bin` members;
Warrior Within check 2026-08-29: 301 members -> 3,067 scenes / 4.19 M triangles). Peter
Jackson's King Kong (GWKE41) is textures-only: its later Jade build is not decoded yet.

### PoP SoT GC display lists: the lightmap point layout (fixed 2026-09-04)

The quality audit ranked GPTE41 #5 (214 garbage / 316 suspect of 10,624): level
architecture (`*_mur`, `*_VIS`, `Aviary_FenceDoor`, `Colonnes_mur` ...) came out as
spike-balls.  Every PoP GEO carries both the platform-neutral triangle list and a
GameCube copy (`GEO_GeoObject_GC_Content`: `DEADBABE | u32 flags | per element u16
strips, u16 | per strip u16 length + points`), and the exporter prefers the strips.  A
point is `index, [normal if flags & 1], colour, uv` (u8 each with `Index8Bits` = bit 20,
else u16) **then, with `HasLightMap` = bit 21, two u16 lightmap indices per point**
(Ray1Map `DisplayList_Point`: Index / Normal / Col / Tex / LM1 / LM2).  `parse_geo` had
skipped the lightmap data as one `4 * length` block after the strip: same byte budget
(so the exact-size check passed) but every point after the first was read 4 bytes
early, giving out-of-range indices that the exporter's `np.clip` silently folded onto
vertex 0 / the last vertex.  Affected GEOs are the ones with GC flags `0x?08084`
(bits 2, 7, 15 + 21 - lit level geometry); plain `0x4` / `0x100004` props were right all
along.

Proof on 7 level packs read from the disc (6101_Tour, 2201_Aviary, 0103_Colonnes,
3101_TowerExit, 3501_HaremAccess, 1401_Cour, 2101_Start; 557 GEOs with strips, 135
lightmapped): with the per-point layout the strips triangulate to exactly the GEO's own
triangle list for 557 / 557 (before: 422, and all 135 lightmapped GEOs indexed past their
vertex pool); `gcrip.quality` on the same GEOs goes 53 garbage / 43 suspect -> 0 / 26.
The 26 left are non-lightmap grass / ivy alpha cards (`*Gazon*`, `*Herbe*`, `*Liere*`,
`*ALPHA*`) whose strips already matched their triangle list - faithful vegetation
billboards, an audit false positive.  The 86 "GEOs" that fail to parse per pack are
21 / 30-byte keyed lists that merely start with the type word 1.  Open: the lightmap
UV pool the LM1 / LM2 indices address (not exported), and the 859 untextured models.
GPTE41 needs a re-rip.

## Level assembly (2026-08-29)

The "big-endian map tables" were a red herring. Pandora Tomorrow's `.lin` files are plain
load-order indexes: `u32 0 | u32 0 | u32 1 | u32 name length | "../datagcn/Maps/x.unr" |
package ...` repeated per entry, and every entry is a package with header + name table +
import table + export table stored *sequentially* (the header's table offsets are the
original file's, not the bundle's; export data offsets stay relative to the original file).
The map / texture / static-mesh entries carry no object data (only `animations/*.ukx` do) -
the real packages are the standalone `.unr` / `.utx` / `.usx` files, all little-endian,
standard v102/33 layout.

Map package (`dataGCN/Maps/4_3_1_B_TV.unr`, 912 KB): 2,924 exports - ReachSpec 950,
StaticMeshInstance 447 (per-instance lighting), StaticMeshActor 333, PathNode 249, Model /
Polys 120 (BSP), CollisionMeshActor 113, Brush 91, SpriteEmitter 81, Light 71.  Actor exports
have `RF_HasStack` (0x02000000): the data starts with the state frame `index node | index
state | u64 probe mask | u32 latent action | index offset (if node)` (15 bytes here) and only
then the tagged properties.  Placement properties: `StaticMesh` (object -> import
`<usx package>.<group>.<mesh>`; `Col` groups / `COL*` names and CollisionMeshActor are
collision), `Location` (Vector), `Rotation` (Rotator pitch/yaw/roll, 65536 = 360 deg, UE's
FRotationMatrix with row vectors: world = local @ M), `DrawScale`, `DrawScale3D`, `PrePivot`.
Other placed classes: Mover, ESwingingDoor, ELgtSpot, ELgt1Lamp, EGamePlayObjectLight,
ELightSwitch.  Unreal is X forward / Y right / Z up left-handed -> glTF by (x, z, y) with the
winding flipped (`plugins/unreal.py: _yup`, applied to standalone `.usx` scenes as well).

Census (plugins/unreal.py `_level`): 34 maps, 11,830 actors placed, 0 missing meshes, 818,993
triangles, 1,633 of 2,287 materials textured, 7 s for the disc.  Open: BSP world geometry
(`Model` exports: UModel Bounds / Vectors / Points / Nodes / Surfs / Verts; brush `Polys`
FPoly arrays), sky-dome actors are placed as-is (huge), Shader / Combiner materials.

Bundles of the other titles (same day): SC1 `warlins.umd` (190 MB, chunks `u32 usize 0x18000
| u32 csize | zlib`, segments end with (0, 0)) and Chaos Theory `.lin` (chunks `u32 csize |
zlib`, 416 chunks -> one 13.6 MB segment) start with an entry name (`0a "0_0_2.unr"`) followed
by raw object data (state frames + tagged properties) and only later the package headers
(SC1 seg0: 107 headers from 0x681c, CT: 172 magics from 0xa84c, versions 100/119 and
396/114).  Object data blocks are interleaved with header groups; which block belongs to
which package is the open question (the first entry's 26 KB cannot hold the map's 279 KB).

SC1 `warlins.umd` mapped further (2026-08-29 evening): 36 zlib segments = one linearized pack
per level (`0_0_2.unr` ... `menu.unr`, 11-22 MB inflated each, 443 MB total), each holding
~110 package headers (sequential tables) interleaved with data blocks (after packages 36, 45,
63, 106 in `0_0_2`).  `Sounds/MAPS.SM3` / `.LM3` / `*.LS3` are sound bundles (level names +
`.wav` names), so meshes and textures live in the `.umd` data blocks.  The map's actors sit in
the block after package 106 (state-frame signatures `[80-bf][80-bf] ff*8 00000000` from
0x4fb101): the first three objects match export order and sizes exactly (LevelInfo0 211,
PhysicsVolume4 85, EZoneInfo1 147) but the stream then diverges - the bundle stores objects
in its own order with its own sizes, so export offsets / sizes / cumulative sums do not
locate objects.  Viable next step: scan the block for state frames and parse tagged
properties with the map package's name table (Location / Rotation / StaticMesh come out),
then find the StaticMesh objects (props start with the `Materials` array) in the same or
earlier blocks and test whether they follow their package's export order for name binding.
Chaos Theory `.lin`: chunks `u32 csize | zlib` (416 chunks -> one 13.6 MB segment), versions
100/119 and 396/114, 172 headers - a different engine build, not yet examined further.

### Splinter Cell 1 bundle geometry (probe 2026-08-29 night)

The inflated SC1 segments DO contain Pandora-Tomorrow-style StaticMesh vertex arrays - 32-byte
records `f32 position[3] | f32 normal[3] | f32 uv[2]` (big-endian) followed by a `u32 marker |
u32 | u16 strip` index run - but only a handful: scanning all eight 4-byte alignments of
`0_0_2.unr`'s 7 MB segment finds 20 runs totalling 2,836 vertices (largest 852).  A whole
level pack cannot be that small, so the v100/119 GameCube build must keep most of its geometry
in another (quantised or platform-specific) form; finding that layout - not the package
tables - is what stands between this family and a rip.
