# Treyarch NGL stashes (`.ST2`) - Kelly Slater's Pro Surfer (GKSE52), 2026-09-05

Cracked from the quality-audit work list: GKSE52 had **36 of 42 library models garbage
and 6 suspect** - the worst garbage share of any disc.  Root cause: not a reader bug but
an *unclaimed format*.  Every asset on the disc is a Treyarch "stash" (209 `.ST2`, 174 MB)
that no plugin recognised, so the `gx` fallback scanned each 5 MB stash whole and its
platform-neutral pass (f32 array + u16 run) exported the stashes' bounding-box / entity
tables as meshes: the same ±7760 / ±400 / ±9700 symmetric boxes on every beach, 93-100%
zero-length edges, no real geometry at all.  The one honest find (`FRONTEND.gltf`'s
`gx000_f32`, 256 vertices) was a menu prop.

Three years later the same engine ships Spider-Man 2 / Ultimate Spider-Man
([treyarch-ngl-gamecube.md](treyarch-ngl-gamecube.md)); the `GCNT` texture chunk is
byte-for-byte that generation's version 3 (`gcrip/formats/ngl_gc.py` decodes both), the
mesh chunk is an earlier, unrelated layout (version 0xA against 0x1D-0x1F).

Modules: `gcrip/formats/treyarch_st2.py`, `gcrip/plugins/treyarch_st2.py` (`st2`
container + ordinary claim), `gcrip/plugins/ngl.py` (`GCNM` 0xA / stash `GCNT` members),
`tests/test_treyarch_st2.py`.

## The stash

Big-endian.  Header 0x40:

| off | field |
| --- | --- |
| +00 | `u32 data_end` - the directory offset; file length is `data_end + count * 64` |
| +04 | `u32 0x5AFE0004` |
| +08 | `u32 count` directory entries |
| +0C | `u32 0x40, u32 0x40` |
| +14 | `u32 a_end` - section A `[0x40, a_end)`: meshes + textures |
| +18 | `u32 c_off, u32 c_size` - section C: more textures (the beaches' 212-chunk wave sets), `ANMX` animation |
| +20 | `u32 b_off, u32 b_size` - section B: entity / script text (`spawn surfing_entity ...`, `TREYARCH_DATA_TYPE = ENTITY`) |
| +38 | `DEADF00D DEADF00D` |

Directory entry, 64 bytes: eight words of packed name (a 6-bit-per-character hash the
runtime keys on), `u32 offset` **relative to the entry's section**, `u32 size`, `u8 kind`
(4 mesh, 6 texture, 5 anim, 1 text), `u8 sub`, then little-endian *runtime pointer slots*
(`48 7f 2f 00`) that overwrite the first twelve characters of the name, so only
`name[12:24]` survives (`dtop.gct`, `hadow.gcmesh`, `S_TRN_BOTTOM`).  The reader does not
trust the section-by-kind rule: an entry is resolved by finding a `GCNM` / `GCNT` tag at
`base + offset` over the three section bases, each chunk once.  Members come out as
`NNN_<surviving name>.gcmesh` / `.gct`.

Section A of `FRONTEND.ST2` also holds untagged text (`scrobjs`, `MESH_CLIP =
PERFECT_TRICLIP`, ...) between chunks - the reason a tag-walk alone cannot tile it.

## `GCNT` textures

`GCNT, u32 3, u16 pixel_offset (0x20), u16 palette_flag (0), u32 pixel_bytes, u16 w, u16
h, u8 gx_format, u8 tlut_format, u8 mips, ...`; pixels at +0x20; C4 / C8 palettes follow
the pixels (32 / 512 bytes) in the header's TLUT format (1 = RGB565, 2 = RGB5A3 - the
deck textures are RGB565 and opaque; reading them as RGB5A3 punches alpha holes).  Formats
seen: 14 CMPR (menu plates, 512x512), 9 C8 (boards, skins), 8 C4, 5 RGB5A3.  The dir
`size` is `0x20 + pixels + palette`; the file leaves 0x38-0x58 bytes of zero trailer after
each chunk.

## `GCNM` meshes (version 0xA)

```
+00 GCNM, u32 0xA, u32 1, u32 size, u32 flags (0x01000222 / 0x01000002), 0, 0, u32 size-16
+20 name[32]                          "personalityks_lo000", "ksp_board_lo000", "beach000"
+40 f32 cx cy cz 1.0 radius, 0, 0
+5C u32 nbones, u32 bones_off, u32 nparts, u32 parts_off, 0
```

`nbones` 4x4 f32 bind matrices at `bones_off` (row vectors, translation in the last row -
the surfer's spine joints climb y = 0.13, 0.275 ...); `nparts` 88-byte records at
`parts_off`, offsets relative to the chunk:

```
[hdr_off, radius, cx, cy, cz, 1.0, nbones, 0,
 nidx, idx_off, nslots, slots_off, hdr2_off, ?, ntris, remap_off,
 nverts, verts_off, nnormals, normals_off, nslots2, slots2_off]
```

Part header 232 bytes (`u32 id`, name at +0x10: `ks_p_trso`, `ks_p_flame`, `teahupoo03`,
`cabin_wall`).  Slots are 12 bytes: `RGBA8 colour, s16 u, s16 v, pad`, uv with **9
fractional bits** (the surfer's range is exactly 0..512).

Two vertex layouts, told apart by `remap_off`:

- **rigid** (boards, beaches, the cabin's 95 parts): `nverts` f32 xyz at `verts_off`,
  `nnormals` s16 xyz / 16384, `nslots2` slots at `slots2_off`; the index stream is
  `(position, normal, slot)` u16 triples forming one triangle strip with doubled-index
  restarts (`113 113 112 112`).  A part may share one normal (`reefa`: 81 positions, 1
  normal, 49 slots).
- **skinned** (surfers, their shadows): `nslots` slots, a u16 `remap` slot -> record, and
  `nverts` 28-byte records `f32 xyz, s16 normal xyz, u16 nbones, u8 bone[4], u8 weight[4]`
  (weights sum to 255).  Vertices are model-space; the strip of slot indices is **several
  per-bone GX batches laid out back to back with no bridging degenerates** - the 176-byte
  second header at `hdr2_off` is a 41-word table, word *i* = indices in the batch bound to
  bone *i* (`452 + 14 = 466`; `463 + 9 + 34 + 74 + 35 + 81 = 696`), followed by three words
  that split the record's `?` count.  Triangulating the stream as one strip adds exactly
  two bridge triangles per batch boundary; per batch it lands on `ntris`.

Degeneracy is decided on *positions*, not indices: a restart double repeats a position
whose slot (uv / colour) may differ, and the game's `ntris` counts it that way.

## Identity

- Every part's arrays tile its chunk: `hdr (232) -> [hdr2 (176)] -> indices (padded to 4)
  -> slots -> remap -> records | -> positions -> normals -> slots`, the last part ending on
  the chunk's `size`.  All 44 meshes in the seven cached stashes tile.
- Declared triangle count: **every mesh reproduces its own `ntris` sum** (surfer 1858,
  shadow 856, board 168, cabin 4900 -> 4899 is one zero-area triangle the game counts).
  181 of 183 rigid parts match exactly, all skinned parts do.
- Textures: 575 of 575 `GCNT` in the cached stashes decode (219 FRONTEND, 315 beach, 20
  SYSTEM, 16 + 5 board sets).

## Before / after

| | models | garbage | suspect | ok |
| --- | --- | --- | --- | --- |
| library rip (gx fallback over the stashes) | 42 | 36 | 6 | 0 |
| seven cached stashes through `st2` + `ngl` | 44 meshes (13,646 tris) + 575 textures | 0 | 0 | **44** |

Renders (`scratchpad/hishare/renders/GKSE52_*_after.png`): the surfer is a full A-posed
body with head, hands and feet; `ksp_board` is a surfboard (pointed nose, rounded tail,
rocker); `cellphone000` a flip phone; `beach000` the reef arc around the break; the old
`MUNDAKA.gltf` was a dot inside an 8000-unit empty box.

## Scanner side

The same audit signature (77-100% zero-length edges, or all vertices on a line) came from
three unrelated formats this pass (`.ST2`, Gusto `.fab`, Runecraft `.gcg`), so
`gcrip/gxscan.py` now refuses such finds outright (`_degenerate`, `MAX_ZERO_EDGE_SHARE`
0.30, `MIN_AXIS_RATIO` 0.01), and `plugins/gx.py` no longer scans `sys/fst.bin` and the
other disc system files.  On the cached noise sources the scanner now yields nothing;
the synthetic-grid and salvage tests are unchanged.

## Open

- Texture binding: the part header carries an id (`0x149810`) but no texture name; the
  directory names are clipped; the board's `dtop / dbot / bl / bld / whd` textures sit in a
  *different* stash (`KS_0_BRD.ST2`) from the mesh (`KSP_AUX.ST2`).  Meshes ship untextured
  beside textures-only scenes.
- Bone hierarchy (flat skeleton exported), `ANMX` animations (section C), the entity text
  (placement of props in the beach scenes), the packed name words.
- Re-rip: **GKSE52** (only disc with stashes in the library).
