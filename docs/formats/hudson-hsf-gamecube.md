# Hudson Soft HSF models and Mario Party .bin archives (Mario Party 4-7, GameCube)

Verified 2026-08-29 on Mario Party 4 `files/data/mario.bin` (236 LZSS members -> Mario
T-pose, 107 objects, 15 meshes, 4.7k tris, skinned, CMPR/RGB5A3 textures). Reference:
github.com/KillzXGaming/MPLibrary (`MPBIN.cs`, `HSF_Parser.cs`, `Sections/*`). gcrip:
`gcrip/formats/mpbin.py`, `gcrip/formats/hsf.py`, `gcrip/plugins/mpbin.py`,
`gcrip/plugins/hsf.py`, tests/test_hsf.py.

## .bin archive (big-endian)

`u32 count | u32 offsets[count]`; member = `u32 unpacked size | u32 compression | data`
(packed size = next offset - offset - 8). Compression 0 stored; 1 LZSS (1024-byte ring
starting at 0x3be, flag byte LSB-first, 1 = literal, 0 = `u8 lo, u8 hi` with offset =
((hi & 0xc0) << 2) | lo, length = (hi & 0x3f) + 3); 2/3/4 "slide" (Yaz0-like: u32 BE flag
words MSB-first, 1 = literal, 0 = `u8 a, u8 b`: distance = ((a & 0xf) << 8 | b) + 1, length
= (a >> 4) + 2, 2 -> next byte + 18, 4-byte header skipped); 5 RLE (`u8 code`: bit 7 = raw
run of code & 0x7f, else repeat next byte); 7 zlib after an 8-byte size header. MP4 uses
LZSS everywhere. Members have no names (gcrip: `NNN.hsf` / `NNN.dat` by content).

## HSF (`HSFV037`, big-endian)

Section table at 0x08, 20 x `u32 offset, u32 count`: fog, colour, material, attribute,
position, normal, texcoord, face, object, texture, palette, motion, cenv, skeleton, part,
cluster, shape, map attribute, matrix, symbol; `u32 string table, u32 size` at 0xa8.

- Vertex sections: `count` components `u32 name, u32 n, u32 data offset` (relative to the
  end of the table). Positions f32 xyz; normals f32 xyz in MP4 (MPLibrary also reads s8 -
  pick by the byte span between components); colours RGBA8; texcoords f32 uv.
- Faces: components of 48-byte primitives `u16 type (2 tri, 3 quad, 4 strip) | u16 flags
  (material index = & 0xfff) | 4 x (s16 pos, s16 nrm, s16 col, s16 uv) | f32 nbt[3]`;
  strips keep 3 groups then `i32 count, u32 index` into the extension table that follows
  all primitives (index * 8 bytes) - strip = first 3 groups + extension groups. -1 = unused.
- Objects (0x144): `u32 name | i32 type (0 null, 1 replica, 2 mesh, 3 root, 4 joint, 5
  effect, 7 camera, 8 light, 9 map) | i32 const | i32 render flags | i32 parent | i32
  children | i32 symbol | f32 T[3] R[3] S[3] | f32 current[9] | f32 cull[6] | f32 base
  morph | f32 morph[32] | i32 unknown | i32 face | i32 vertex | i32 normal | i32 colour |
  i32 texcoord | i32 material data | i32 attribute | u8[4] | i32 shape count | i32 shape
  symbol | i32 cluster count | i32 cluster symbol | i32 cenv count | i32 cenv index | i32
  cluster positions | i32 cluster normals`. Rotations are Euler XYZ in DEGREES (values up to 360 occur;
  MPLibrary feeds them to radian matrix builders, which looks wrong).
- Materials (0x3c): name, flags, colours, `i32 texture count @0x34, i32 first symbol
  @0x38`; symbols[first + i] = attribute index; attribute (0x84) has `i32 texture index`
  at +0x80.
- Textures (0x20): `u32 name, u32 max lod, u8 fmt, u8 bpp, u16 w, u16 h, u16 palette
  entries, u32 tint, i32 palette, u32 pad, u32 data offset` (relative to the table end);
  fmt 0 I4/I8 (by bpp), 1 I8, 2 IA4, 3 IA8, 4 RGB565, 5 RGB5A3, 6 RGBA8, 7 CMPR, 9/10/11
  C8 (C4 when bpp 4) with palettes `u32 name, i32 fmt, u32 count, u32 offset` (u16 entries).
- Cenv (skinning, 36-byte rigs: name, single/double/multi bind offsets, counts, vertex
  count, single): single bind `i32 bone, s16 pos idx, s16 pos count, s16 nrm idx, s16 nrm
  count`; double `i32 bone1, i32 bone2, i32 count, i32 weight offset` -> `f32 weight, s16
  pos idx, s16 count, s16, s16` (bone1 = w, bone2 = 1-w); multi `i32 count, s16 pos idx,
  s16 count, s16, s16, i32 weight offset` -> `i32 bone, f32 weight`. Bone = object index;
  weights start right after the bind tables. Rest pose = object TRS hierarchy.
- Motion section = animations (not ripped yet).
