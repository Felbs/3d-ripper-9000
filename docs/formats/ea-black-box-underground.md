# EA Black Box: Need for Speed Underground (2003) on the GameCube (2026-09-03)

Disc: Need for Speed: Underground (GNDE69).  `gcrip/formats/ea_nfs.py` was worked out on
Underground 2 (and carries Most Wanted and Carbon - 3 to 7 million triangles each), but the
first Underground reported 962 triangles from 44 files: every car strip failed with
`strip needs 25 bytes, has 20 (fmt 0216)` or `indexes past its arrays`, and every texture
with `unknown GX format`.  The disc keeps its files loose (`CARS/<car>/GEOMETRY.BIN`,
`TEXTURES.BIN`, `VINYLS.BIN`, `TRACKS/*.BUN`), so the chunk reader already reached them.

## How it was read

`Speed.elf` (8 MB) ships **17,000 function symbols and DWARF 1** (`.debug` 4 MB).
`tools/dwarf1.py` gave the on-disk structs and the symbol table named the render path:

```
eSolid (152)            +12 Version, +14 Flags, +16 NameHash, +20 NumPolys, +22 NumVerts,
                        +24 NumBones, +25 textures, +26 light materials, +32 AABB min,
                        +48 AABB max, +64 PivotMatrix, +148 Name (a pointer; the string follows)
eSolidPlatInfo (36)     u16 Version (0x14), u16 StripFlags, u16 NumStrips, u16 NumIdxClrTable,
                        u32 SizeofStripData, u32 DataOffset0..3 (positions, normals, colours,
                        uvs), then two runtime pointers          = the 0x00134800 chunk
eStripEntry (16)        u32 DataOffset, u16 DataSize, u16 Flags, u8 NumVerts, u8 PolyGroup,
                        u8 TextureNumber, u8 LightMaterialIndex, u8 VertexDescription,
                        u8 VertexFormat, u16 DataDLSize        = the 0x00134801 rows
TextureInfo (124)       +12 DebugName[24], +36 NameHash, +56 ImageSize, +60 PaletteSize,
                        +68 Width, +70 Height, +74 ImageCompressionType, +76 palette entries
TextureInfoPlatInfo (60) +56 Format (the GX format)
```

The Underground 2 reader's names for the plat-info words ("flags, strips, verts, total")
were guesses over the same struct; only the strip semantics differ between the games.

## Strips - `eDataRender::Render` and `vsModel`

`LoaderPlatChunks` points the three chunks at their data in place (plat info aligned to
16, the strip table to 16, the strip data to 32).  Rendering (`epRenderStrips` ->
`eSubmitMesh` -> `eDataRender::Render`) sets the five GX arrays with fixed strides -
positions **F32** xyz (12), normals S8 (4), colours RGBA8 (4), colour 1 (4), uvs S16 (4) -
calls `vsModel(VertexFormat)`, which maps the format byte to a VCD / VAT pair
(`vsVtxAttrFmt`: seven formats, positions always F32, uvs S16 with 12 fraction bits), then
copies each corner into the FIFO itself:

* **VertexDescription 1**: 8-byte corner records of u16 - position, normal, colour, uv;
* anything else: 4-byte records of u8 in the same order.

The u8 / u16 choice is the whole meaning of the description byte; the format byte is not a
per-slot width mask as it is on Underground 2.  Colour indices run past the (usually
one-entry) colour array - the game feeds them an index-colour table
(`NumIdxClrTable`) - so the reader clamps them to the array's first colour instead of
dropping the strip.  Bit 0x4000 of the strip flags selects a software path with 20-byte
vertex records (f32 position whose low mantissa bytes carry two bone indices, s8 normal,
u8 weight, s16 uv) after the index list; the sampled files never leave room for those
records, so the index path covers them.

Supra: **399 parts, 30,633 strips, 76,109 triangles**, every position inside its part's
bounding box, the body a Supra in the wireframe; `GLOBALB.BUN` reads clean.

## Textures

The pack's `0x33310003` chunk holds **20-byte stream entries** (hash, absolute offset,
packed bytes, flags 0x100, 0) rather than Underground 2's 24-byte ones, and the streams
sit in `0x33320001`.  A stream is JDLZ and unpacks to the GX tiles then the palette
(RGB5A3) with **no trailer**: the 124-byte TextureInfo record (matched by hash) gives the
size, the palette size and the width / height, and the 60-byte platform record the GX
format.  `_parse_stream_records` / `_decode_described`; 51 of 51 Supra textures decode
(CMPR, C8 with 256-entry palettes).

## Open

* `NumIdxClrTable` - the per-vertex colour table the game uses in place of the colour
  array; the reader takes colour 0.
* The 0x4000 skinned-vertex path (car damage) if a file ever carries the 20-byte records.
