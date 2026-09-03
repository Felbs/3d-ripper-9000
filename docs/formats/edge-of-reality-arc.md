# Edge of Reality `index.ind` + `.arc` - The Sims, Shark Tale, Over the Hedge - CRACKED

Three discs with **fourteen to nineteen files each**, almost all of the bytes sitting in a
handful of unnamed `.arc` blobs that open with zeros. All three reported **two textures** and
no models, because nothing opened an `.arc`.

Read by `gcrip/formats/edge_ind.py` + `gcrip/plugins/edge_arc.py`.

| disc | files on disc | `.arc` | MB |
|---|---|---|---|
| Over the Hedge | 15 | 5 | 1,196 |
| Shark Tale | 14 | 4 | 1,032 |
| The Sims | 19 | 7 | 410 |

The directory for every archive is the single `index.ind` beside them - 223 KB, 133 KB and
123 KB respectively. It is read through the `NEEDS_SIBLING` / `expand_with` hook, the same one
Eurocom's `Filelist.000` uses.

## The index

Big-endian. A flat list of segments:

    +0    u32 count
    +4    (count + 1) u32 offsets into this file, ascending; the last is the file length

`offsets[0]` is exactly the end of the offset table and `offsets[-1]` is exactly the file
length, which is what identifies the format - the archives themselves have no magic at all.

The segments alternate a short printable **category name** and that category's **table**, and
the names say precisely where everything lives:

    Levels  QuickDatas  Graphs  QDMetadatas  Characters  Models  Occluders  Animations
    BonePositions  Havoks  Fonts  Movies  PclEffects  Shaders  Textures  Sounds  Binaries
    Samples  AudioStreams  Programs  DataBuilders  Datasets        (Over the Hedge, 21 of 22)

## The table is a sorted hash array, not a record array

    u32 count
    count * u32           name hashes, strictly ascending
    count * (u32 offset, u32 size)

`4 + count * 12` is the same length either way, so it *measures* as an array of twelve-byte
records - and read that way it yields three columns of entirely plausible 32-bit numbers, none
of them ascending and all of them meaningless. What gives it away is that the **first `count`
words are sorted**: it is a binary-search table with the payload locations after it. The reader
requires that sort, which is the only thing separating the two readings.

## Which archive a category lives in

**Its own name, truncated to eight characters** - `AudioStreams` to `audiostr.arc`,
`QuickDatas` to `quickdat.arc`, `RleTextures` to `rletextu.arc`. That is a guess, and it is
made safe by an exact check: the category's `max(offset + size)` has to account for the
archive's length.

Eleven of the sixteen category/archive pairs across the three discs land **on the byte**:

    Over the Hedge   Levels 2,894,207   Movies 574,376,316   Samples 61,154,604
                     AudioStreams 216,477,632   Datasets 399,527,193
    Shark Tale       Movies 444,219,776   Samples 33,133,851   AudioStreams 344,887,680
    The Sims         Movies 101,379,296   Samples 113,860,974   AudioStreams 150,309,798

The other five stop 156 to 64,357 bytes short of a padded tail - the worst being 0.73% of an
8.7 MB archive. **Demanding an exact match rejects two of the three discs outright**, and
Over the Hedge is precisely the disc that hides it, because all five of its archives are exact.
The allowance is still a real check: a wrong pairing misses by a different order of magnitude,
Over the Hedge's `Models` ending at 73 MB against a 399 MB `datasets.arc`.

A category with no matching archive - `Models` and `Textures` on Over the Hedge, which ships no
`models.arc` - is left alone rather than pointed at the nearest file.

## Results

Audio and video categories are skipped rather than carried: `Movies` alone is 574 MB on Over
the Hedge and none of it is geometry.

| disc | archive | members |
|---|---|---|
| The Sims | `models.arc` | 901 |
| | `rletextu.arc` | 377 |
| | `datasets.arc` | 309 |
| | `quickdat.arc` | 5 |
| Over the Hedge | `datasets.arc` | 153 |
| | `levels.arc` | 62 |
| Shark Tale | `datasets.arc` | 106 |

**1,913 members** on discs that had none. This closes the `Over the Hedge datasets.arc` entry
that had been sitting in `docs/OPEN.md`.

## What the members are - first pass

None of the 1,913 is a TPL, so nothing decodes them yet, but each category has a legible shape:

**`models.arc` (901 on The Sims) - named.** Four zero bytes, then a NUL-terminated name from
+6: `the_terrain_for_neighborhood_screen(derived_from_rev46)`.  After the name the payload is
dense and unaligned - one string in the first 20 KB, no plausible float or offset columns - and
**`gxscan` finds nothing in any of the six largest**, so the geometry is not GX display lists.

**`datasets.arc` (309 / 153 / 106) - nested containers.** A member opens with its own name
(`RD_TRAINSET_-_CHEAP_A`), then a count, then a sub-category name - `Textures` - so a dataset
repeats the index's own name-then-table idea one level down.  That is the most promising thread:
it is the only category that says in plain text what it holds.

**`rletextu.arc` (377) - a palette then RLE indices.**  The first 1,024 bytes are **256 ARGB
entries**, alpha first.  That byte order is not a guess: read from offset 0 the first column
takes only **three distinct values** across all 256 entries (255 on 217 of them, 0 on 36, 190 on
3) while the other three take 150, 144 and 122 values over a smooth ramp -
`(255,199,170,130) (255,205,175,135) (255,212,182,142) (255,221,192,151)`.  A colour channel
does not behave like that; an alpha channel does.  The remaining ~62 KB is the RLE stream.

## Inside a dataset - the structure is solved, the pixel format is not

A dataset member is the index's own idea one level down, and it walks cleanly:

    char name[]        NUL-terminated: "RD_TRAINSET_-_CHEAP_A"
    u32  sections
    then per section:
        char name[]    "Textures", "RleTextures", "Animations", "Samples", "Binaries"
        u32  count
        then per entry:
            u32 hash
            u32 size       from the start of the name to the end of the entry
            u32 0
            char name[]    "LFXTstrings_theory_stereo", "LFXTmusic_note_particle"
            u16, u16 width, u16 height
            12 bytes
            the pixels

**Entries are interleaved with their payloads and the stride closes exactly**: the first entry
of `0fcf8afd` sits at 47 with `size` 2094, and `47 + 12 + 2094 = 2153` is precisely where the
second entry's hash begins.

**270 of The Sims' 309 datasets parse**, and the dimensions are the proof: every pair is a
power of two - 32x32 (72), 64x64 (45), 128x64 (37), 128x128 (36), 512x512 (24), 16x16 (12),
64x32 (11), 512x256 (9), 256x256 (8), 256x128 (8).  A layout read at the wrong offset does not
produce powers of two 270 times.

**This is where the missing texture dimensions live**, which is what `rletextu` needs - no
member of that archive states its own size.

### The flag byte identifies the depth, and the pixels still resist

Walking the whole dataset tree gives **5,092 entries** across every section - Animations 2,708,
Textures 752, Shaders 738, RleTextures 371, Models 343, Characters 96, ParticleTypes 64,
QuickDatas 6 - so the container reading is not in doubt.

The two bytes before the dimensions are a format flag, and bits-per-pixel separates them
cleanly (payload bytes * 8 / (width * height)):

| flag | n | bpp min / median / max | reads as |
|---|---|---|---|
| `81 04` | 455 | 4.000 / 4.016 / 4.250 | 4 bpp, no palette |
| `89 04` | 109 | 4.002 / 4.516 / 6.062 | 4 bpp plus a small palette |
| `8a 08` | 188 | 8.125 / 10.004 / 136.250 | 8 bpp plus a 512-byte palette |

`81 04` sitting on 4.000 to 4.016 across 455 entries says the payload is **raw and fixed-size**,
not compressed - a compressor does not land on exactly four bits per pixel 455 times.

**And yet it does not decode as an image in any of the obvious readings.**  Scored as the
median ratio of a shuffled copy's roughness to the decode's - every texture genuinely cracked
in this project scores 3x to 69x:

    8a 08  GX I8 tiles      2.91x        89 04  C4, palette last     1.78x
    8a 08  C8, palette last 1.49x        89 04  C4, palette first    1.39x
    8a 08  C8, palette first 1.35x       81 04  GX CMPR              1.09x
    81 04  GX I4 tiles      0.98x        81 04  linear 4 bpp         1.20x
    8a 08  linear 8 bpp     1.73x

Nothing clears 3x, and the largest group is indistinguishable from noise either tiled or
linear.  So the depth is known, the dimensions are known, and the pixel order is not.

**PS2 swizzle was the obvious next guess and it is wrong.**  These are PS2-era multiplatform
titles, so the standard `PSMT8` unswizzle was the first thing to try on the 8 bpp group: it
scores **1.32x**, *worse* than reading the same bytes linearly (1.73x).  Ruled out.

That leaves a per-block encoding as the likeliest answer - the sibling category being called
`RleTextures` says this engine does encode its textures.  Nine readings are now eliminated;
the next attempt should start from the payload's own structure rather than from a layout guess.

## Still open

* the pixel format inside a dataset's `Textures` entry - the structure around it is solid, so
  this is now a question about one blob with known dimensions rather than about the container;
* the RLE scheme for `rletextu`, whose dimensions can now be looked up by hash in the datasets;
* the `models.arc` payload, which is not GX.

## The Sims 2 and The Sims 2 Pets - models, textures and shaders read (2026-09-03)

The Sims 2 GameCube (`G4ZE69`) is the same engine (its `eorwb.log` is the Edge of Reality
WorkBench log) and ships `u2_ngc_release_dvd.elf` **with its linker map**, so every loader has a
name: `ERModel::LoadModel`, `ESubModel::Read`, `ESubModelShader::Read` with `ReadPositions` ..
`ReadIndices`, `ERTexture::LoadFromMemory` + `ENgcTexture::Create`, `ERShader::CopyShedData`,
and `ENgcRenderer::InitGXVertexFormats` for the vertex attribute formats.  Read by
`gcrip/formats/edge_model.py` with `plugins/edge_model.py` (models) and `plugins/edge_tex.py`
(textures); `plugins/edge_arc.py` now also opens `textures.arc` and `shaders.arc`.

On these two discs the index is flat: `Models` (3,631 / 5,475), `Textures` (11,443 / 16,049)
and `Shaders` each in their own archive.  Pets writes the category tables with a 20-byte
header (`u32 0, u32 count, u32 table bytes, u32 capacity, u32 0`) before the sorted hashes;
`edge_ind` reads both.

### Members

Every member is an `EDataHeader`: `u32 version, char[4] tag, u32 -1, u32 n, name[n], u32 size,
payload`.  Tags: `MODL` (version 0x3a on The Sims 2, 0x3e on Pets), `TXFL` (9), `SHDR` (0x16),
`DTST` (10), `CHRC`.

**Model** (`ERModel::LoadModel`, versions 0x39-0x3e):

```
u32, 48 bytes, u8
u32 n, n x 64                         attachment vertices
u32 n, n x BSplineVolume              u32 tag (non-zero: nothing else), 0x80, u32, u32 nx, ny, nz,
                                      u32 sets, sets > 1: sets*nx*ny*nz x f32[3]
u32 n, n x ENDummy                    u32 tag, name[64], u32, u32 k, k x 0x50
u32 n, n x ENCamera                   u32 tag, name[64], u32, u32 k, k x 0x60
u32 n, n x 28                         SimsLightInfo
u8 flag, f32 scale, u32 nsubmodels
submodel: u32, u32 nshaders, shaders
shader:   u32 flags, u32 shader hash, u32 nstrips, nstrips x u8, u32, tokens until 6:
          0  strip: u32 nverts; positions s16[4] (flags & 0x10) or f32[4]; UVs (flags & 2;
             s16/4096 or f32, four components with 0x40); RGBA8 colours (flags & 4);
             normals s8[4] (flags & 8; s8[3] up to version 0x39); u8[4] weights while skinned;
             flags & 0x20: u32 corners, u8, u32 size, u32, a GX display list
          1  u16, u8 (bone)   2/4  skinned on   3/5  skinned off
f32[4] bound sphere, f32[6] bounds, f32[6] bounds, u8[4]
```

`flags & 0x10` is the packed vertex: `s16` positions with `scale` (2^-12 for characters,
2^-16 for objects: the bounds are in the same units), `s16/4096` UVs from GX vertex format 6
(`GXSetVtxAttrFmt(6, TEX0, S16, frac 12)`).  A strip with no display list is a **triangle strip
over its vertex array in order** (`CreateRCPrimitive` returns `nverts - 2`); with one, each
corner is a u16 index per attribute present (position, normal, colour, texcoords), and every
attribute indexes the same vertex.  Verified on 11 members that parse to their last byte:
NPC_catwoman (62 strips, 3,049 triangles, T-posed) and a double-basin sink drawn as wireframes
look exactly like their names.

**Texture** (`ETextureDef`, 32 bytes, then the mip chain, then the palette):

```
u32, u32, u32 flags, u32, u16 w, u16 h, u16 palette entries, u16 mips, u8 format, u8,
u8 bpp, u8 palette bpp, u32
```

`ENgcTexture::Create` maps the format byte: 0x81 CMPR, 0x82 RGB5A3, 0x83 C4 / 0x84 C8 over a
16-bit palette, 0x85 and 1 RGBA8, 0x89 C4 / 0x8a C8 over a 32-bit palette.  The pixels are
GX-tiled on disc.  **The 32-bit palette on disc (flags bit 7) is two IA8 TLUTs**, not RGBA
entries: `entries x (B, R)` words then `entries x (A, G)` - the C4_32 / C8_32 classes draw
with two TEV stages, one per TLUT, and `UpdateEnd` shows the byte order when the split is
done at load time.  Settled on colour-named textures (mohawk_red dark red, alien_green green,
blouse2_pink pink) after the two obvious orders gave the wrong hues.

**This answers the open question above.**  The old dataset `81 04` / `89 04` / `8a 08` flags
are this same `format, bpp` pair (CMPR, C4_32, C8_32); the C8 reading scored badly because the
palette was read as 4-byte entries.

**Shader** (`EShaderDef`): `u8 textures, u8, u16, u32 x 3, 48 bytes, 9 x u32`, then 64-byte
layers whose first u32 is a texture's name hash.  A model's strip names its shader by hash,
the shader names its texture by hash, and the hash is of the *name*, so a shader and a texture
of the same name share it (NPC_catwoman -> shader 992eeb73 -> texture `missingshader`: the
Sims' skins are composited at runtime).

### The datasets - The Sims, Bustin' Out and The Urbz (same day)

The three older Sims discs keep their models inside `Datasets` members (Urbz and Bustin' Out
have *only* `Datasets` and `QuickDatas` in their index).  `gcrip/formats/edge_dataset.py` +
`plugins/edge_dataset.py` open them as a container, `<Category>/<hash>.eorm` / `.eort` /
`.eors`, and `edge_model` / `edge_tex` read the entries:

```
Sims / Bustin' Out    name\0, u32 sections, sections x (name\0, u32 count, entries)
Shark Tale / Hedge    12 zero bytes, u8 sections, name\0, sections as above
The Urbz              u32 9, name[64], u32 count, count x (category[32], entry)
entry                 u32 name hash, u32 size, u32 0, size bytes
```

Every dataset sampled on the five discs walks to its last byte.  The entry payloads are
wrapped per game:

* **textures** `LFXT` (Bustin' Out: `u32 7` + 12 zero bytes; Urbz: `u32 8, u32 size`), the
  name, then the header and the pixels.  The Urbz writes the 32-byte `ETextureDef`; the others
  a 20-byte `u8 fmt, u8 bpp, u16 w, u16 h, u8, u8 palette bpp, u16 palette entries, u32 flags,
  u32, u16 mips` - the same formats and the same split palette (`flags` has bit 7).  Sizes
  close on 20 of 20 sampled textures across the five discs, and the parrot sculpture is a
  parrot.
* **models** The Sims / Shark Tale / Hedge: `u32 0, u16 0, name\0` then the model *without*
  the node arrays (`u8 flag, f32 scale, u32 submodels, ...`), three-byte normals, no u32 after
  the strip count, five bytes after the bounds.  Bustin' Out: first word `0x00010000`, 16
  bytes after the name, and the u32 after the strip count is back.  The Urbz: an
  `EDataHeader` with an empty name (`u32 0x35, 0, 0, 0, u32 size`), the name as a string, then
  the whole Sims 2 layout.  The reader locates the body by its `f32 scale, u32 submodels,
  u32 id, u32 shaders` run rather than trusting the per-game zero fields.
* **shaders** The Urbz wraps the same `EShaderDef` behind its name (`shader_textures` reads
  it); the older discs' shader records are not decoded, and a strip's shader hash is then
  matched to the texture of the same name, which is how those discs are laid out (the spoon's
  texture, shader and model all hash to `01774b03`).

Sampled results: The Sims 6 models / 1,083 triangles, 6 of 6 textures bound; Bustin' Out
3 / 1,066; The Urbz 2 / 271 (its textures sit in other datasets, resolved at rip time).

### Shark Tale and Over the Hedge - the other strip record (same day)

The same datasets (twelve zero bytes and a section-count byte in front, and the third word of
an entry is padding - Over the Hedge pads its samples), the same 20-byte texture header, and a
model header that opens the shader record with the name hash instead of a flags word.  The
record is self-describing GX:

```
u32 name hash
u32 flags, u32 vertices, u32 strips, u32 block bytes, u32 offsets x 5 (position 0, normal,
    colour, colour 1, texcoord)
block                       the attribute arrays at their offsets, each running to the next
u32 n, n bytes              a display-list chunk of CP loads: array pointers (0xa0..) and
                            strides (0xb0..) - the strides say what the arrays hold
u8 k, k x (u8, u32)         an attribute table (constant across the discs)
u32 n, u32 corners, n bytes the primitive chunk: VCD lo/hi, an XF load, then the primitives
                            whose corners are index8 / index16 per attribute in VCD order
strips x u8, tokens, 6      0x45 carries two words, 0x46 three, 0x51 / 0x52 none
```

Strides seen: positions 6 (s16, frac 0 in every VAT the DOL registers) or 12 (f32); normals
4 (s8 + pad); colours 2 (RGB565) or 3 (RGB8); texcoords 4 (s16/4096).  The non-position arrays
are deduplicated and indexed separately.  Read by `parse_hedge_payload`; eight Shark Tale
models / 498 triangles, the kelp textured.  The Over the Hedge datasets sampled held no
models (its 1,647 sit in the level packs) - the wave will tell.

### Still open

* Over the Hedge texture format 0x88 (4 bpp, no palette, twice the bytes of a 64x64 4-bpp
  image; neither I4 nor IA4 nor two I4 frames) - 3 of 38 sampled textures.
* The Sims (2003) `rletextu.arc` (377 RLE textures) and every disc's `Characters` (skeletons)
  and `Animations`.
