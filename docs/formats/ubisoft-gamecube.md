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
- **Open**: the big-endian map packages (SC1 `.unr`, Pandora `.lin`, XIII) parse names fine
  but their import / export tables are not the standard layout (regular 8-byte-ish records
  such as `fd 34 ff ce fe 07 00 00`; not compressed - entropy 6.1); Ghost Recon 2's
  `gcngame.umd` is script-only, its geometry is inside the `.lin` maps; Chaos Theory / Double
  Agent `.lin` need the single-block variant checked; SkeletalMesh / Mesh (LodMesh)
  serialisation for characters.

## OpenSpace / CPA (Ubisoft Montpellier) - Rayman 3, Rayman Arena

`.hst` (sound), `.lvl` + `.ptr` (level + pointer relocation), `.hxg`/`.hxd`, `.tpl` (GC
textures, 139 files). Reference implementation: github.com/byvar/raymap (C# Unity loader for
Rayman 2/3/Arena incl. GC). Parked.

## Jade (Ubisoft Montpellier)

Beyond Good & Evil and Prince of Persia: Sands of Time / Warrior Within / The Two Thrones
already rip through the jade plugin (`files/prince.bf` BIG file -> ~2.5k `.bin` members;
Warrior Within check 2026-08-29: 301 members -> 3,067 scenes / 4.19 M triangles). Peter
Jackson's King Kong (GWKE41) is textures-only: its later Jade build is not decoded yet.
