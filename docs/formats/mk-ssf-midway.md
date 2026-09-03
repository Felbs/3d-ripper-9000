# Midway `SEC` archives (`.ssf`) - Mortal Kombat: Deception and Deadly Alliance (2026-09-03)

Discs: Mortal Kombat: Deception (GQNE5D, 147 `.ssf`, 554 MB) and Mortal Kombat: Deadly
Alliance (GMKE5D, 125 `.ssf`, 414 MB).  Both reported zero triangles: the archives are not a
known container and the RenderWare clumps inside them are written in a shape the stream reader
did not accept.  Implemented: `gcrip/formats/mk_ssf.py` (directory, texture members),
`gcrip/plugins/mk_ssf.py` (container: `<name>.mkdff` / `<name>.mktex` / `.bin`), and three
additions to the RenderWare stack (`rwstream.py`, `rwgc.py`, `plugins/renderware.py`).

## How it was read

Deception ships `mk6gc_release.elf` with a CodeWarrior linker map (`mk6gc_release.MAP`).
`mk_fileinfo.o` names the archive walker - `load_ssf`, `find_section_by_name`,
`get_ssf_dir_entry` - and the RenderWare setup calls `RpGameCubeVtxFmtSetTexCoord(S16, 11)`,
which is the texcoord quantisation the streams rely on but do not record.  Deadly Alliance has
no map; its directory differs only in the entry record and its RenderWare is 3.2.

## Archive

```
block     "SEC ", u32 4, u32 0, u32, u32 count, u32 names bytes, u32 data bytes
          count x (u32 type, u32 offset, u32 size, u32 name offset), names (NUL strings)
DA block  "SEC ", u32 4, u32 0, u32, u32 count, u32 data bytes
          count x (u32 type, u32 offset, u32 size), no names
```

Big-endian; offsets count from the block's own start.  The root block holds one nested block
(type 1, Deadly Alliance 6) at 0x800; the reader recurses to depth 4.  The two layouts are
told apart by the word at +24: the names-bytes count is at least 16 on a Deception block, the
Deadly Alliance layout has no such field.

| type | payload |
|---|---|
| 1 / 6 | nested block |
| 3 | texture: `u8 n, name[n], NUL, seven bytes`, then a RenderWare Texture Native `STRUCT` |
| 4 | eight bytes, then a RenderWare `CLUMP` stream |
| other | kept as `.bin` (animations, collision, sound tables - not decoded) |

Deadly Alliance members have no names: the plugin calls them `member`, `member_1`, ... and the
RenderWare plugin's same-archive texture lookup still binds them because the texture rasters
carry their own names.

## Midway's RenderWare

Three departures from stock RenderWare, all handled in the shared reader so any other Midway
disc gets them for free:

* **In-place geometry.**  The GEOMETRY `STRUCT` is declared as the *whole* geometry: after the
  16-byte header and the one morph target (40 bytes) the material list, the extension and a
  bare `STRUCT` holding the GameCube native data sit *inside* the declared size.  Stock
  readers see a geometry with no materials and no native data.  `rwstream._parse_geometry`
  re-walks the chunks at struct + 40 when a native geometry has no materials and a chunk
  header sits there.  The native block is the platform-6 `STRUCT` whose size is exactly
  `12 + header + data`; a second platform-6 `STRUCT` is the skin (`_parse_skin_gc`: numBones,
  numUsed, maxWeights, the used-bone list, per-vertex weights unless maxWeights is 1, the
  inverse bind matrices).  Deception's fighters are skinned with 56 joints and one bone per
  vertex, so the display list carries `PNMTXIDX`.
* **`PAD32` / `PAD128` filler.**  The data is aligned in the file with the text
  `PAD32PAD32PA...` (cut mid-word at the boundary).  The native data size counts the filler
  and the display-list / array offsets count from the padded start (`rwgc.skip_pad`).  The
  texture raster size counts its `PAD128` filler too: the pixels are the tail of the declared
  size (`_decode_one` skips `size - encoded_size` bytes when they begin with `PA`).
* **Fraction bits in code.**  The native attribute table gives S16 texcoords 0 fraction bits;
  the game sets 11.  `plugins.renderware` passes `MK_FRACS = {GX_TEX0: 11}` for `.mkdff`
  members and `rwgc.decode_native` uses it wherever the table says 0 (GX's fixed normal
  fractions - 6 for S8, 14 for S16 - still win).

Deadly Alliance is RenderWare 3.2 and not native: its vertex payload is **big-endian** with
`(v0, v1, v2, material)` triangles, where every other GameCube RenderWare stream is
little-endian with `(v1, v0, material, v2)`.  `_parse_geometry` decides by reading the
triangle indices both ways and keeping the reading whose vertex indices stay under the vertex
count.  Its textures use the old (pre-3.3) raster layout, chosen by the struct's version.

## Results

| archive | models | triangles | textures |
|---|---|---|---|
| Deception `kamidogu_earth.ssf` | 1 | 804 | 3 of 3 bound |
| Deception `thepit.ssf` | arena | 17,868 | 28 of 28 |
| Deception `scorpion.ssf` | 97 members; `COSTUME` 6,957 triangles, 56 joints, T-pose | | |
| Deadly Alliance `JourneyGrasslands.ssf` | arena | 14,806 | 9 of 9 |

Both discs are on the pass-7 title list (wave 40).

## Open

* The other member types (animations, collision, tables) and the `.msg` / `.mbg` files beside
  the archives (136 of each on Deception, 352 MB) were not looked at.
* Deadly Alliance's fighter archives were not sampled for skins; the reader takes the same
  in-place path if they use it.
