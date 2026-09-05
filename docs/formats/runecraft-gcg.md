# Runecraft `.gcg` / `.gct` / `.gcm` - Mat Hoffman's Pro BMX 2 (GMHE52)

Cracked 2026-09-05 from the quality-audit work list (GMHE52 was #13: 472 of 533 exported
models flagged).  Reader `gcrip/formats/gcg.py`, plugin `gcrip/plugins/gcg.py`, tests
`tests/test_gcg.py`.

## What was wrong

Every model on the disc is a `gcg\0` file - 4,730 of them under `TRACKS/<park>/geometry/`,
`GLOBAL/riders/`, `GLOBAL/bikes/` (50 MB) - and nothing claimed them, so the `gx` fallback
scanned them.  The scanner's platform-neutral pass found the f32 position arrays (the
extents of the exports were right: a park chunk at 1110..1290) but paired them with the
wrong u16 run as indices, so 76-81% of the edges were zero-length; the props it exported
through the inline-s16 path (`sf_bridge_cable01`, extent 99,204) were reading the wrong
stride.  Root cause: an unclaimed private format, not a bug in a reader.

## Layout (big-endian)

```
"gcg\0"  u32 version = 3  u32 nnodes
nnodes x 224-byte node record:
    char name[64]   pad[64]
    f32 matrix[16]     row-major, translation in row 3, parent-relative
    f32 pivot[3]  f32 maxabs[3]  f32 radius      maxabs = largest |coordinate| per axis
    s32 parent         -1 = root
one mesh section (skinned vertices bind to nodes through the display list, see below):
    u32 nmat   nmat x char material[64]           "<name>.gcm" next to textures/
    u32 1  f32 lod_distance (FLT_MAX)  u32 nsub
    nsub x submesh:
        u32 material index                        0xFFFFFFFF = none (po_col* collision)
        u8 flags   0x80 = explicit vertex format block follows
        u8 attr mask   1 pos  2 nrm  4 col  8 uv  0x40 per-vertex matrix index
        u8 1  u8 0xFF  u8 0
        f32 radius   u16 nverts
        [flags & 0x80]  u32 pos comp (3 s16 / 4 f32)  u8 pos frac
                        u32 nrm comp (1 s8)           u8 nrm frac
                        u16 0  u8 uv comp (0 u8 / 1 s8 / 2 u16 / 3 s16)  u8 uv frac
        u8 pos element size (6 / 12)   nverts x position
        [mask&2]  u8 size  nverts x normal    3 = s8/64      12 = f32
        [mask&4]  u8 size  nverts x colour    4 = RGBA8      2 = RGB5A3
        [mask&8]  u8 size  nverts x uv        2 = u8/2^frac  4 = s16/2^frac  8 = f32
        u32 nbatch   nbatch x u32 draw count   u32 dl_size
        GX display list (dl_size bytes)
[nnodes > 1]  u32 1  u32 n  u8 node order[n] (4-aligned)  u32 nnodes
```

- The display list is plain GX: `0x80` quads / `0x90` tris / `0x98` strip / `0xA0` fan,
  u16 count, then **one u16 index per set attribute** per vertex in attribute order
  (pos, nrm, col, uv); `0x00` pads to 32 bytes.  Strips are stitched with repeated
  vertices - the plugin drops the zero-area triangles.
- s16 positions are `value / 2**frac`.  Pinned by the node header: `po_vdeck12` (frac 11)
  stores z = 27368 -> 13.363 = `maxabs.z`; `po_col57` (frac 12) 23001 -> 5.615 =
  `maxabs.x`.  The comp-type / frac bytes are GX `GX_CompType` / `GX_CompSize` values.
- The implicit format (flags 0x00, 3 files in the cache) is all f32: positions, normals
  (12 bytes), UVs.
- **Skinning (mask 0x40)**: riders, bikes and multi-node props (`chbridges`,
  `po_tree_bridge`).  The list interleaves `LOAD_INDX_A` (`0x20`, u16 node index, u16
  `addr | size<<12`) and `LOAD_INDX_B` (`0x28`, normal matrices) with the draws, loading
  node matrices into the ten position-matrix slots, and every vertex begins with a direct
  u8 `PNMTXIDX` (slot * 3).  Vertices are stored in the space of the node they bind to;
  one node per vertex, no weights.  World = local @ parent chain (row-vector
  convention), which is how the T-posed rider and the bike came out right.
- The trailer lists the node draw order (26 nodes on a rider, padded with zeros).

## Textures and materials

`.gct`: `u32 1  u32 paletted  u32 nmips  u32 ncolors  u32 w  u32 h`, then for paletted
files `ncolors` RGB5A3 palette entries, then per mip level `u32 w  u32 h  u32 size` +
tiled GX data - C8 when paletted, CMPR otherwise - **smallest level first** (an 8-level
128x128 stores 1x1 .. 64x64 before the base image).  RGB5A3 was decided by the alpha:
the `fir_lod` tree cut-outs and the `PO_rampcrack01` decal come out transparent where
they should.  231 of 231 cached textures decode; the renders were checked by eye
(Bigfoot's face, the fir tree sheet, the ecosystem sheet).

`.gcm` is an INI text material: `[ShaderPass_1] ShaderName = GCNVSDiffuse ...
TextureMap_1 = <stem>`, `BlendMode = GX_BM_BLEND` for alpha.  Lookup: `<name>.gcm` in the
model's folder, its `textures/` folder or the parent's `textures/`; the picture is
`<stem>.gct` beside the material.  Park chunks: `TRACKS/<park>/textures/`; riders and
bikes: `GLOBAL/riders/`, `GLOBAL/bikes/`.

## Identity

- 401 of 401 cached `.gcg` (the whole Portland park + the six worst + rider + bike) parse
  **byte-exact to EOF** with every display-list index below the vertex count, including
  the four multi-node skinned files.
- s16 scale reproduces the node header's `maxabs` exactly on every s16 file checked.
- 231 / 231 `.gct` decode.

## Before / after (same models, `gcrip.quality`)

| model | before | after |
|---|---|---|
| daytona `misc4drgn030x020x50` | garbage, 76% degenerate edges, 4756 tris | ok, 0%, 1844 tris |
| portland `poground21` | garbage, 79%, 2666 | ok, 0%, 1284 tris, 19 textures |
| chicago `chchunk19` | garbage, 81%, 1855, 9 components | ok, 0%, 912, 1 component |
| sf `sf_bridge_cable01` | garbage, extent 99,204 (s16 stride) | suspect: *shattered* only - 168 separate cable strands, extent 2,015 |
| austin `aubldg04` | garbage, 80%, 1461 | ok, 0%, 1813 |
| `GLOBAL/riders/big01` | (not in the worst list) | ok - a T-posed rider, 1764 tris, textured face |
| `GLOBAL/bikes/but01` | | ok - a BMX with spoked wheels, bars, pedals, 2868 tris |
| chicago `chbridges` (5 nodes) | | ok - four bridge sections at their park positions |

Whole Portland park: 393 files export (the 394th, `po_trackvert01b`, is a 252-byte
node-only file with no submeshes), 45,097 triangles, 321 files textured, quality scores
393 ok / 0 suspect / 0 garbage.  Renders: `scratchpad/hishare/renders/GMHE52_*_after.png`.

## Open

- The rider/bike hierarchy is baked to world space (rest pose); the `.MOT` motion files
  (966 of them, 8.8 MB) and the `Big01.Vut` / `.mir` sidecars (left/right bone mirror
  table) are not read, so no animation.  Emitting the nodes as glTF joints instead of
  baking would make the MOT work a drop-in.
- `.col` (4,158 collision files) are not decoded - not needed for the library.
- `nbatch x u32` draw counts and the 5-byte `01 ff 00` header bytes are parsed past, not
  interpreted.
- Disc needs re-ripping: **GMHE52**.  Check the manifest census for any other disc
  shipping `gcg\0` files (Runecraft's other GameCube title would be the candidate).
