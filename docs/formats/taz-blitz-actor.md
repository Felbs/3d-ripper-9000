# Taz: Wanted - the 2002 BlitzTech actor layout

Closed 2026-09-04 (evening), cracked entirely from a cached pack
(`tazhub_nocol.gcp`, 7.9 MB) with zero disc reads - the wave cascade held the drive.

The `.gcp` container and `.tbt` textures were already read (`plugins/blitz.py`,
`blitz_tbt.py`); only the `.tba` actor layout differed from the Bratz DWARF structs.
`gcrip/formats/taz_actor.py`; `plugins/blitz_actor.py` falls back to it when the Bratz
parse raises.

## Header (identity, 265/267 actors fit)

    +0x06 u8  1 (resource kind, same as Bratz)
    +0x0c u32 name hash (= the hash in the member filename)
    +0x80 u32 table offset (0xd0 = the 32-byte node/track records)
    +0x84 u32 node count
    +0x8c u32 mesh/batch count
    +0x9c f32 maxRadius            <- oracle
    +0xa0 f32 bbox xmin,xmax,ymin,ymax,zmin,zmax   <- oracle (pairs, not min[3]max[3])
    +0xbc u32 resource size (~ member length)      <- oracle

## Geometry

- Display lists: stride-8 vertices `u16 pos, u16 nrm, u16 clr, u16 tex`; every list opens
  with the CP load `08 50 00 00 7e 00` (the vertex descriptor) - **that signature is the
  robust enumerator**.  Lists carry inline CP (0x08) and XF (0x10) loads; the XF loads are
  the skin matrices.  Prims seen: 0x90 triangles, 0x98 strips (+0x80/0xa0 handled).
- **Rigid mesh record**: 6 words `pos nrm tex clr dl_off dl_size`; positions AND normals are
  f32 xyz (Bratz normals are s8/64), texcoords f32 st, colours RGBA8.  `dl_size` is the
  padded allocation and may overrun the member end - clamp to the arrays/end.
- **Skinned actors** (taztarzan, eggbird, littlepiano, 2 debris): one `(dl_off, dl_size)`
  pair table that is *entangled with the skin-influence table* before it (same shape,
  ascending offsets), so walk the signature hits instead: 496/496 on taztarzan.  The shared
  arrays are referenced by nothing - find them with the oracles (best window of
  max-index f32 triples inside the bbox for positions, unit-length window for normals,
  bounded-f32-pair window for texcoords).  Vertices are in model space (bind pose), so the
  static shapes are complete without the node tree.
- **Texture binding**: 16-byte batch records, rigid `{prim_count, crc, 0, 0}`, skinned
  `{crc, 0, 0, prim_count}`, CRC = the 8-hex hash in the `.tbt` filename; batches consume
  prims in order.

## Numbers (hub pack)

267/267 actors extract, 347 meshes, 8,847 triangles, 215 scenes with bound texture images,
all meshes with UVs.  Oracle floor 95%, mean 99.9%.  Geometry verified by wireframe render -
taztarzan is visibly a character (head, spread arms, legs).

## The lesson

The earlier note said "the whole header must be re-mapped from taz.elf first" - wrong.
The resources self-describe: radius + bbox + size gave the header, and the CP signature
gave the display lists.  Oracle-first beat symbol-first here.
