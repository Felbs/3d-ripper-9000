# Mass Media `BOLT` archives and "distill" models (2026-09-03)

Discs: Muppets Party Cruise (GM9E6S, 89 `.BLT`), Shrek Super Party (GSYE6S, 38), Pac-Man Fever
(GPMEAF, 3 in the FST), Namco Museum 2002 (GNMEAF, one 321 MB `Data0.blt`).  All four are Mass
Media's GameCube engine ("BOLT", `MMI::` namespace); Namco Museum 50th Anniversary is Digital
Eclipse and not this.  Implemented: `gcrip/formats/bolt.py` (archive + codec),
`gcrip/formats/bolt_model.py` (node tree, meshes, material lists), `gcrip/plugins/bolt.py`
(container), `bolt_model.py`, `bolt_mat.py`.

## How it was read

Muppets Party Cruise ships `Muppets.elf` with 65 MB of DWARF 1.  `tools/dwarf1.py` prints the
struct layouts (`BOLTHeader`, `BOLTGroupEntry`, `BOLTMemberEntry`, `MMIFILE`), and the symbol
table names every loader: `MMI::Decompress(void*, int, short)`, `MMI::MATERIALLIST::LoadNode`,
`MMI::MESH::Load`, `MMI::MATERIALLIST::LoadMaterials`, `MMI::TEXTURE::CreateBuffer`.  The
Shrek and Pac-Man DOLs carry the same functions unnamed; they were located by their read sizes
(the `0x200` / `0x20` palette reads) and by the `ERROR! Old distill MATERIAL file` strings.

## Archive (`BOLT`)

```
BOLTHeader (16)       "BOLT", u8 hours, mins, secs, sec100, u8 month, day, year, u8 NGroups, u32 Size
BOLTGroupEntry (16)   u8 Flags, Init, Term, NumberMembers, u32 Size, u32 Offset (member table), u32
BOLTMemberEntry (16)  u8 Flags, Init, Term, Type, u32 Size (unpacked), u32 Offset, u32 hash
```

Group entries follow the header; each group's member table sits at its `Offset`.  A board
archive is two groups (24 tiles + 2), Namco Museum's `Data0.blt` is 42 groups / 931 members.
A packed member has no stored packed length: it runs to the next member's offset.

**Flags bit 3 (`0x08`) means stored**: `MMI::Decompress` copies when it is set and inflates
otherwise.  The 2003 archives also set `0x40` on packed members; the 2002 ones (Namco Museum,
Pac-Man Fever's fonts) leave it clear, so `0x40` cannot be the test.

The codec is a byte-oriented LZ with prefix bytes that widen the next copy:

```
b < 0x80     copy: length = (len << 3) + ((b >> 4) & 7) + prefixes + 2, offset = (off << 4) + (b & 15) + 1
0x80..0x8f   literal run of (len << 4) + (b & 15) + 1 bytes
0x90..0x9f   len = b & 3, off = (b >> 2) & 3, prefixes += 1
0xa0..0xbf   len = (len << 5) + (b & 0x1f), prefixes += 1
0xc0..0xff   off = (off << 6) + (b & 0x3f), prefixes += 1
```

Verified: every member of `BBoard0`, `BCommon`, `BMG00` (Muppets), `DataBNTO`, `DataTEST`
(Shrek), `DataBum`, `DataHUD` (Pac-Man) inflates to its declared size and parses to its last
byte.

## Members

Every model / material member opens on a four-byte version: `01 09 00 15` is 1.9 revision 21.
Muppets is 1.9.21, Shrek 1.9.18, Pac-Man Fever's DOL wants 1.9.12 and its two FST archives are
**1.3.10** - an older exporter the DOL only warns about (`Old distill file`) and does not read
correctly, so those two archives are leftovers.  Pac-Man's real game data is opened by name
(`OpenBOLTLib(BoardGam)`, `DataHUD`, ...) from outside the FST: the disc is 1.46 GB, the FST
accounts for 1.15 GB.  A raw scan for `BOLT` headers is the way to it (open).

### Model member (1.9) - `MATERIALLIST::LoadNode`

```
tag, u8 n, name[n]          "Data_BBoard0_Board0_GCN"
node := u8 type, body, u16 children, children x node
  0 NODE         -
  1 ANIM         name[16], f32[16] matrix, 12, u16 channels, u8[3], u8 mode,
                 channels x (u16 keys, keys x 32 (mode 0) | 0x34 (mode 1))
  2 ANIMCONTROL  u16, name[16]
  3 BBOX         f32[6], 12, 4
  4 MESH         MESH::Load stream
  5 OBJECT       name[16], u8[4], f32[16] matrix, 12
  7 SKIN         u8
  8 LOD          -
```

Matrices are row vectors with the translation in the last row (`pos @ M[:3,:3] + M[3,:3]`);
a mesh is in the space of the nearest OBJECT / ANIM above it and those nest (a lever inside a
gear inside a tile).

**1.3** chains nodes with flag bytes instead of counts - `body, u8 child flag (+ subtree),
u8 sibling flag (+ subtree)` - ANIM has one flag byte and no mode, ANIMCONTROL has no body,
OBJECT has one flag byte, and type 6 LIGHT is 16 bytes plus a single next-node flag.  Settled
by a grid search over the byte grammar against exact member consumption (65 of 65 members),
then confirmed in the Pac-Man DOL's LoadNode.

### Mesh stream - `MESH::Load`

```
u16 faces, u16 material (& 0xfff; 0xffff none), u16 n, name[n], u16 flags, u16 vertexType,
u8 vertexSize, u8 posFrac, u8 nrmFrac, u8 texFrac,
u16 npos,  npos x (f32[3] if VT & 1 else s16[3] / 2^posFrac)
u16 nnrm,  nnrm x (s8[3] if VT & 2, s16[3] if VT & 4, else f32[3]; / 2^nrmFrac)
u16 nclr,  nclr x (2 bytes for VT & 0x70 in (0x10, 0x20), 4 for 0x60)
u16 ntex,  ntex x (s16[2] if VT & 8 else s8[2]; / 2^texFrac)
u32 size,  GX display list: u8 opcode (0x80/0x90/0x98/0xa0 | VAT), u16 count, count x corner
u8 skinned; if 1: u16 n x f32[3]; u16 n x f32[3]; u8 weights; n*4*weights; n*(weights+1)
```

A corner is `pos index, nrm index (when nnrm), colour, tex index (when ntex)`; the colour is
an index when the mesh has a colour array and otherwise **direct** (two bytes RGB565 for
`0x10`, four for `0x60`) - the board tiles carry their lighting that way.  An index is a byte
unless its array has more than 256 entries; `vertexSize` declares the width and is checked
(the reader tries the 255 threshold when 256 disagrees - no sample has exactly 256).

The mesh name is the material's name: 204/204 (Pac-Man), 45/45 (Shrek), 160/160 (Muppets)
match the indexed material, which is the check that the material index and list line up.

**1.3**: `u16 faces, u16 material, u16 n, name, u16 vertexType, u16 npos x f32[3],
u16 nnrm x f32[3], u16 nclr x RGBA8, u16 ntex x f32[2], u32 size, display list, u8 skinned`.
`VT & 1` widens every index to u16; bits 2 / 4 / 8 flag normals / colours / UVs.

### Material list member - `LoadMaterials`

```
1.9.21  tag, u32 pool size, pool (NUL strings: list name, texture names, material names), u32,
        u16 nmaterials, u16 nlayers, u16 ntextures, textures, materials
1.9.18  tag, u32 pool size, pool, u32, u16 ntextures, textures, u16 nmaterials, materials
texture   u16 w, u16 h, u8, u8 type, u8 mips, u32 size, [u8 if type in 2 3 4], pixels (mip chain),
          type 3: u16, 512-byte palette; type 4: u16, 32-byte palette
material  1.9.21: u8, u8 nlayers, nlayers x (u8 flags, f32[3], u32, u32, u16 ntex,
                  ntex x u16 texture | f32[4] colour when ntex == 0)
          1.9.18: u8 flags, f32[4] colour, f32[4], u32, u32, u16 n x u16, u16 n x u16
1.3     tag, u8 n, name, u16 ntextures, textures (u16 n, name, u16 w, u16 h, u8, u8 type,
        [u8 for type 3 4], u8 mips, mip chain, [u16 size, palette]), u16 nmaterials,
        materials (u16 n, name, u16 ntex, ntex x u16)
```

Texture types from `TEXTURE::CreateBuffer`: 5 CMPR, 0 RGBA8, 2 RGB5A3, 3 C8 and 4 C4 over an
RGB5A3 palette (`GXInitTlutObj` format 2).  A 64x4 level is stored at its true 128 bytes, not
the tile-rounded 256.  Names repeat (`Map #4` several times) and are often Windows paths of the
source `.bmp` / `.avi` (animated textures are consecutive frames), so the exporter keys them
`tex<index>_<stem>`.

## Results

| archive | version | models | meshes | triangles | textures |
|---|---|---|---|---|---|
| Muppets `BBoard0.BLT` | 1.9.21 | 24 | 161 | 2,046 | 47 / 47 |
| Muppets `BCommon.BLT` | 1.9.21 | 187 | 338 | 11,448 | 274 / 274 |
| Muppets `BMG00.BLT` | 1.9.21 | 27 | 233 | 2,794 | 115 / 115 |
| Shrek `DataBNTO.BLT` + `DataTEST.BLT` | 1.9.18 | 4 | 61 | 2,490 | 29 / 29 |
| Pac-Man `DataBum.BLT` + `DataHUD.BLT` | 1.3.10 | 66 | 248 | 19,277 | 300 / 300 |

Every material in every sample resolved to its texture or colour.

## Open

- **Pac-Man Fever's real data is outside the FST** - scan the image for `BOLT` headers (the
  disc is idle-only work while the passes run) and feed them to the same plugins.
- **Skinned meshes** (`skinned == 1`): the bind arrays and weights are skipped; no sample
  archive had one (the Muppets characters are probably in `BChar*.BLT`).
- **Animations**: ANIM nodes carry keyed matrices (32-byte keys: time, position, quaternion);
  not exported.
- **Namco Museum 2002**: the archive reads (42 groups, 931 members) but holds arcade ROM
  images, palettes and 2D data - no model members.  Nothing to rip through this route.
- Colour kinds `0x20` (read as RGBA4) and `0x60` (RGBA8) are unobserved; only `0x10` (RGB565)
  is on the sample discs.
