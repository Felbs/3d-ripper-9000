# Next Level Games GL - Super Mario Strikers `.glg` / `.glt` (2026-09-03)

Disc: Super Mario Strikers (G4QE01): 149 `.glg` models (23 MB) and 164 `.glt` texture
bundles (42 MB) under `art/` - characters, stadiums, crowd, gameplay props - on a disc that
reported 376 triangles.  Implemented: `gcrip/formats/nlg_gl.py`, `gcrip/plugins/nlg_glg.py`.

## How it was read

The disc ships `MarioSoccerR.elf` (40 MB: DWARF 1 with 740k entries, a symbol table) and
three linker maps.  The `main.dol` is a different build from all three maps (2% of function
starts coincide), so the ELF itself was disassembled with its own map:

| what | function |
|---|---|
| chunk walk, chunk types, fixups | `glxLoadModelFromDisk` |
| packet -> GX display list | `dlMakeDisplayList` (one u16 index a vertex, written once per stream) |
| stream id -> GX attribute, vertex formats | `glx_SwitchStreams`, a 16-entry id table and the primitive table in `.sdata` |
| structs | `glModel` (16), `glModelPacket` (74 in DWARF; 70 or 74 on disc), `glModelStream` (6), `GXTextureHeader` (32) |
| bundles | `glplatLoadTextureBundle`, `glx_MakeTexture`, the format table at `0x8030cc98` |

## `.glg`

A chunk stream, big-endian `u32 id, u32 size`, payload at +8; an id with bits 24-30 set
aligns its payload to `1 << n`.  A `0x8001b100` level holds units; a `0x8001b000` unit is
one model set:

```
0x1b001   u16 2, u16 2
0x1b002   user data: 4x4 f32 placement matrices (row vectors, translation in row 3)
0x1b003   models: u32 packets, u32 id, u32 0, u32 packet-table byte offset
0x1b004   packets (70 or 74 bytes - divide the chunk by the model table's packet count):
          u32, u32 index-buffer offset, u16 vertices, u8 primitive, u8 streams,
          u32 stream-table offset, state (+0x14 matrix offset, +0x18 texture hash,
          +0x28 second texture hash), u32 material set
0x1b005   streams, 6 bytes: u32 vertex-data offset, u8 id, u8 stride
0x1b006   vertex data       0x1b007   u16 indices
0x8001b008 skin data, 0x1b00f texture animation, 0x1b011 vertex animation,
0x1b012   material list (id, count, {material id, packet index, packets})
```

Every stream of a packet is indexed by the same u16 per vertex.  Stream ids: 0 position
(stride 12 F32, 6 S16 / 256), 1 normal (12 F32, 3 S8 / 64), 2 colour RGBA8, 3-8 texcoords
(8 F32, 4 S16 / 1024 - Mario's coordinates run to 1023), 0xc matrix index (a 0xff byte in
the list, replaced at draw time).  Primitives: 0 triangles, 1 strip, 2 fan, 3 quads.
Characters are one unit with an identity matrix (Mario: 11 packets, 4,909 triangles,
1.4 units tall on Z); a stadium is 323 models placed by 311 matrices (Mario Stadium:
45,366 triangles, 75 of 75 textures bound - a dome with the field and stands inside).

## `.glt`

`PTLG`, u32 count; the dictionary of `u32 hash, u32 offset, u32 bytes, u32 0` at 0x20 (a
few older bundles at 0x10 - both are tried and the one whose entries fit wins); offsets
count from the dictionary's end.  A texture is a 32-byte `GXTextureHeader` - u32 mip
levels, u32 format, u32, u8, u8, u16 width, u16 height, u32 palette entries - then the
tiles of every level, then an RGB5A3 palette.  Format enum: 0 RGB565, 1 RGB5A3, 2 CMPR,
3 RGBA8, 4 I8, 5 I4, 6 I8, 7 IA8, 8 C8.  Materials bind by the packet's texture hash,
the bundle beside the model first.

## Open

* Skinning: `_blend.glg` files carry `0x8001b008` skin chunks (`glx_MakeSkinMesh`); the
  meshes are already in bind pose, so the rip is the T-pose without joints.
* The second texture slot (lightmaps on stadium packets) and the material list.
