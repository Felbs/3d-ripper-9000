# EA Canada EAGL objects on GameCube (verified 2026-08-28 on FIFA Soccer 2004, GXFE69)

Applies to the EA Sports / EA Canada engine family on GC: FIFA 2003-06 + FIFA Street 1/2,
NBA Live 2003-06, NHL 2004-06, MVP Baseball 2004/05, Def Jam FFNY, Fight Night Round 2, SSX
(3 / Tricky / On Tour: `.mnf` manifests + gsh), GoldenEye Rogue Agent, Medal of Honor
(`.ord` present in 16 library discs, `.o` in 20, `.gsh` in 33). Implemented in
`gcrip/formats/eagl.py` + `gcrip/plugins/eagl.py`.

## Containers and files
- Everything sits in BIG/VIV archives (`ea_big`), often BIG inside BIG. Models are
  `<name>.ord` + `<name>.orp` pairs: `.ord` = ELF header + `.data`; `.orp` = u32 (BE) size
  of the .ord, then the rest of the ELF (`.shstrtab .strtab .symtab .rel.data`). Rebuild:
  `ord + orp[4:]`. Player bodies e.g. `player__hibody4__model52__.ord` (437 KB),
  stadiums `mestallacd__mestalla_cd__model...ord` (790 KB).
- `.o` files are the same ELF trick for GUI (APT) objects, skeletons (`!skel.o`, symbols
  `__Bone`, `__Skeleton`) and animation banks (`!eagl`, `__AnimationBank`).
- ELF: little-endian header, e_type 1 (REL), e_machine 8 (tagged MIPS regardless of
  platform), 5 sections. `.data` payload is big-endian GameCube data. Pointers inside
  `.data` are LE u32 patched by `.rel.data` entries (type 2) against symbol 1 (= the section)
  or against externs (shaders, textures, render state, `EAGLAnimationBuffer`,
  `gpModelViewMatrix`).
- Symbols name everything: `__Model:::<file>.o_temp.variationN` (25 per player - all point
  at the same packet run; variations differ in bone/visibility tables, not geometry),
  `__Bone:::<model>.<bone>` (51 bones for a player: Hips, LowerSpine, ..., LLid, RupLip -
  facial bones), `__Skeleton`, `__BBOX`, `__EAGL::TAR:::RUNTIME_ALLOC::UID=n;SHAPENAME=Xxxx,25;
  GCEXTOBJ_SetClampMode...` (textures, 4-char shape names like Accs/Lnme/tp00 resolved in
  sibling `.gsh` SHPG files by entry name), `__EAGL::GeoPrimState:::...SetPrimitiveType=
  EAGL::PT_TRIANGLESTRIP...`, shaders as undefined externs `Gouraud_Skin`,
  `LitTexture2Irrad_Skin`, `LitTextureEnvIrrad2x_Skin`, `EAGL_TOOLLIB_VERSION-3`.

## Render packet (one per mesh part x shader), ~200 per player
Layout from the shader pointer (packet base = shader ptr - 0x1c; base starts with two LE
floats 1.0 = SphereMapScaleOffset):
`P shader | P self+0x10 | (1,P0) | (1, EAGLAnimationBuffer extern) | (nslots, P skin table)
| (1, __const MATRIX4 extern) | (V, P pos) | (V, P attr1) | (V, P attr2) | (V, P uv)
| (bytes, P displaylist) | (1, TAR) | (1, TAR sphere) | (1, GeoPrimState) | (1, P self) | (0, ..)`.
The counts precede their pointers. P0 = 32-byte header (u32 display-list vertex count, rest
zero / runtime). Streams for V vertices: positions s16 xyz (scale 1/256 works), attr1 2 B/vertex
constant 0x77 0x7f (not weights), attr2 s8 xyz normals (3 B/vertex), uv s16 pairs (/256 ->
0..1). Display list: GX strips 0x98 with stride 2 + 2*nstreams: `[posmtx u8][texmtx u8][u16
idx per stream]`; posmtx is a multiple of 3 (GX position-matrix slot 0..27 = 10 slots).
Static objects have no matrix bytes.

## Skinning (verified on the FIFA 2004 player body, 2026-08-28)
- Skin table = the counted pointer right before the `__const MATRIX4` tag: one row per GX
  matrix slot (<= 10), each row 4 big-endian f32 weights that sum to 1 (up to 3 used).
  **The bone index is packed into the low mantissa byte of each weight float** (0x3f068f03 =
  weight 0.526, bone 3). Mask the low byte off to get the weight, `& 0xFF` for the bone.
  Rows are sorted by first weight; identical tables are shared by several packets.
- Per vertex: slot = posmtx / 3 -> that row's (bones, weights). Positions are in model
  (bind) space, so glTF needs only the inverse-bind matrices from the skeleton.
- `__Skeleton:::<model>` symbol -> 16-byte header `c0da 01fe c0da 0000 | u32 bone count |
  0` then one 112-byte record per bone: `f32 scale[3] | i32 parent (-1 root) | f32 quat
  x y z w | f32 translation[3] | i32 id (a permutation - animation channel order?) | f32
  inverse_bind[4][4]` (row-vector convention, translation in row 3). Local TRS composed
  child-in-parent reproduces inv(inverse_bind) to 0.006 units. `__Bone:::<model>.<name>`
  symbols are 4-byte cells holding the record index of the bone they name.
- Player rig: 51 bones (Hips > LowerSpine > MiddleSpine > UpperSpine > Neck > Head,
  collar/arm/twist/forearm/hand + fingers, legs, LLid/RupLip/... facial bones); a body model
  uses 40 of them.

## Variations are kit toggles, not LODs
The 25 `__Model:::x.o_temp.variationN` structs share one render list (7 packets always on)
and differ only in a 40-entry (index, on/off) table over named toggles - the `__Model`
struct's +0xa0 pointer lists them: `enable_body_Sleeves_Long_r/_Short_r/_l/_c`,
`enable_body_hand_open_l/r`, `enable_body_glov_open_*`, `enable_body_HSocks/LoSocks/SSocks
(_Slim)`, `enable_body_RCollar/SCollar/VCollar/SRCollar`, `enable_body_line_flag_L/R`
(linesman flags), `enable_body_Left/RightYellow/Red` (cards), `enable_accs_bracelet/earring
/fingertape/goggles/kneesock/necklace/wristtape/anklesock`, `sortgroup1`. Model struct:
+0 P parameter list, +4 u32 3, +8 u32 25 (variation count), +0xc identity 4x4, +0x4c bbox
floats, +0x9c toggle count, +0xa0 P toggle names, +0xb4 P name, +0xc4 P (index,on) u16
pairs, +0xcc P render list (u32 0, u32 n, n P packet-shader-field), +0xe0.. TAR name table.
- The `const MATRIX4` data (16 floats) is a runtime placeholder, NOT a decode transform.
- Result on the player body: 197/201 packets decode, 8.4k verts / 9.3k tris, T-posed
  footballer with boots; UVs in range. gxscan missed these because packets are tiny
  (83 verts) and positions are s16.

## Textures
- `.gsh` = EA shape files. Magic `SHPG` (FIFA) handled by `ea_shape`; NBA Live 06 uses a
  lowercase `ShpG` variant with a different layout: header `ShpG | u32 LE file size | u32 BE
  count | entries...`, image block at 0x60 = 0x20 header (`19 00 40 01 | size 0x420 | w 32 |
  0x400 | ... | 32 | 32`) + 32x32 8-bit pixels (I8 decode gives a plausible button glyph;
  code 0x19 unconfirmed) + 0x120 mip block; not implemented yet.
- NBA Live/NHL `.ebo` = `EBO\0` v0x11 binary objects (7 games) - not reversed yet.

## Animation banks (`!eagl` objects, `__AnimationBank:::bank`) - not decoded yet
FIFA 2004 player face bank (44 KB .data): root struct `u32 0x18 | u32 count (39) | u32 0 |
P anim table (count pointers) | P name table (count pointers to C strings)`. Names are the
facial expressions the user wants: FACEBALL, FACEBLOW, FACECONR, FACEDFLT, FACEDMIT, FACEGTUP,
FACEHAHA, FACEHFIT, FACEHLCW, FACEHLYA, FACEKISS, FACEMOVE, FACEOEYE, FACEPPLE, FACESERF,
FACESONB, FACESTRK, FACETLK1..3 ... (suffix `_face`), plus `HML_hands`-style names. Each
record is ~0.9-1.4 KB, starts with magic `00 0f c0 da` then `40 02 00 00`, `00 01 00 aa`, a
pointer at +4 (-> a shared block at 0x240 that begins `00 00 00 01 00 01 00 01 1d 30 30 30
00 3c 08 00`) and one at +0xc; the payload is compressed (bit-packed floats, no plain f32
runs). A (P,P) pair + u16 table (0x0121, 0x013c, 0x0148 ... step 12) precedes each record.
Nothing here is decoded - park until the .ebo geometry is done.

## EBO objects (`.ebo`, EAGL 2005+: NHL 2005/06, NBA Live 2005/06, FIFA 05, 2006 FIFA WC, UEFA CL) - 2026-08-28
Little-endian header, big-endian payload: `"EBO\0" | u32 version 0x11 | u32 file size | u16 1 |
u16 1 | u32 data offset (0x60) | u32 type-table off | u32 import-table off | u32 export-table
off | u32 string-table off | u16 x4 | u32 count`. Type table = u32 string offsets naming the
serialised classes (geometry file: Geometry, BoundingInfo, Material, ptr, i32, i16, AssetName,
GcCommandBuffer, PointerArray, GcDisplayList, GCVertexStream, Float3, Short2, Colour,
GcIndexData, i8). Export table = (type idx, name string off, 0xffff<<16 | offset) triples, e.g.
`Geometry "clothShape1ShapeShape" @0x8f0`. Import table = external variables
(`gTexture_RMRuntime`, `Geometry::GetGeometryExternalVariable`) with fixup addresses.
Between header and tables: typed 16-byte relocation/field records `u32 off | u16 flag | u16
type | u32 count | u32` followed by the objects. The geometry payload for the NHL jersey:
GX display list (i8[30832]) at 0x284 -> Float3 positions (BE f32, 1975 = i8[23700]/12) at
0x7aec -> Short2 UVs (BE s16 / 1024, 2037 = i8[8148]/4) -> 16 B -> tables. Display-list
vertex = `u16 position idx | u8 (0) | u16 uv idx` (stride 5 - gxscan misses odd strides),
strips 0x98 with NOP padding, bbox matches the BoundingInfo floats at 0x12c. gxscan finds
nothing in these files; a real parser should walk the field records for the stream sizes.
`bodybank.ebo` (2.7 MB) is NOT geometry: it is an EaglAnim bank - types
`EaglAnim::TimeData_0, DeltaQConstData_0, Indices_0, DeltaF1ConstData_0, SkelAnim_0,
DeltaQAnimData_0, DeltaF1AnimData_0` and 987 exports of type SkelAnim named like
`chk05_benhit_f_0`, `cch05_1frame` (NHL check / hit / celebration clips) - the animation
format for every EBO-era EA Sports title, delta-quantised quaternions + floats.

## EBO geometry - decoded 2026-08-28/29 (gcrip/formats/ebo.py)
- Records = typed pointer fields, 16 B `u32 off | u16 flag | u16 type | u32 count | u32`.
  `i8` records with flag 1 are byte buffers at `record + off`. Vertex streams carry a
  12-byte big-endian header `{size, stride, data offset}` right before the bytes; command
  buffers (GX strip lists) do not - find the first opcode within 0x60 bytes and chain.
- Stream kinds by stride: 12 Float3 positions, 6 Short3 positions, 3 Char3 positions
  (first) / normals (second), 12 Float3 normals (second stride-12), 4 Short2 UV (s16/1024)
  or RGBA colour (the smaller of two stride-4 streams), 8 Float2 UV, 2 R5G6B5 colour.
  Integer positions are normalised to the Geometry's BoundingInfo box (`-1, 0, min xyz,
  max xyz` floats): pos = raw/32767 (or /127) * half-extent + centre. Every list's
  (extent, -min) float pair is the whole-object box.
- Display-list vertex = optional `[posmtx][texmtx]` prefix (texmtx 30..57 = GX_TEXMTX0..9,
  posmtx 0..27 step 3) then one index per stream in GX order pos, nrm, col, tex; u8 when
  the stream has <= 256 entries else u16. Stride = prefix + widths.
- GcDisplayList object ends with `..., u32 0x1fe, P skin table, P stream header, P stream
  header, ...`. Skin table = one row per posmtx slot, 4 big-endian f32 weights with the
  bone index in the low mantissa byte (same trick as FIFA 2004's .ord packets).
- CORRECTION 2026-08-29: skinned lists are in MODEL space too (rest pose == bind pose);
  the "scramble" was several Geometry exports (jersey LOD2 + LOD3 + sticks + `geomSkel`
  = the lower body) drawn on top of each other. Normalise integer positions with the
  bounding box of the Geometry BLOCK that owns the list (each block = one export, opened
  by a `Geometry` record with offset 1 and the block size as count; the first
  BoundingInfo inside it), not the file's first box. Skeleton for the weights -
  `preload/gmisc.viv/bodyskel.ebo`, `faceskel.ebo`, `handskel.ebo` (EaglAnim::Skeleton_0:
  header `ea ea | u16 bones | u32 end`, 4x4 matrices from header+0x38, translation in row
  3; bone names `joint1..` in the string table via the Dictionary).
- NHL 2005 .ebo census: 1477 faces (faces.viv/FACEnnnn.ebo), 564 nis.viv (cutscene
  animation banks), 23 players.viv (player0-2, goalie0-2, R/S LODs, helmets, gloves, hands,
  visor, shadow), 20 per arena*.big (bowls, roof, jumbotron, banners), nisprops (mascots,
  pucks, trophies), crowdLOD1/2 (Float3/Float2/GcIndexData typed records, not decoded).

## EBO skeleton details (bodyskel.ebo: 32 bones, faceskel 24, handskel 21)
`ea ea | u16 count | u32 end` at the Skeleton_0 object; 4x4 matrices from header+0x38
are MODEL->BONE (inverse bind) in row-vector form (translation in row 3): the Hips row
maps world (0, 170.9, 0) to the origin. Right after the matrices: u16 parent per bone
(0xffff = root: RTAnchor > Hips > LowerSpine > MiddleSpine > UpperSpine > Neck > Head;
R/L CollarBone > Arm > ArmTwist > Forearm > ForearmTwist > Hand > HandEnd; Hips > R/L Leg
> LegTwist > Shin > Foot; Props_Puck, Props_Stick > StickHeel), then the Dictionary as
(u32 string offset, u32 bone index) pairs. Skin-table bone ids index this order directly.
Local rest TRS = inv(M_i) composed against inv(M_parent); ripcore then derives the glTF
inverse-bind matrices and the exported jersey bends correctly at the forearms.

## NBA Live 2005 EBO variant (2026-08-29, partly open)
- Same container; geometry described by typed inline records instead of `i8` buffers:
  per list `GcCommandBuffer, PointerArray, GcDisplayList(flag 1 -> command buffer, 0xab
  padded, opcode within 0x200), GCVertexStream, Short3[n](flag 1 -> stream data),
  GCVertexStream, Short2[n], GcIndexData[5]`. Stream headers `{size, stride, offset}` are
  identical to NHL's, so a scan for headers whose offset == header+12 finds all streams.
- Each list has a 15-word big-endian pointer table: `[nrm hdr, pos hdr, uv hdr, 5 tiny
  ptrs, 0x98, 0x2c0002, P floats, P ?, P DL object (= GcDisplayList target - 0x10), 0x1b4,
  P ?]`. The `- 0x10` rule also holds in NHL 2005 (its table ends with the stream headers).
- Vertex: `[posmtx][texmtx][pos u8][nrm u8][clr u8][uv u8]` (stride 6). Normals = the
  44-entry Short3 next to the list, s16 at 1.14 fixed point (raw/16384 -> unit). Positions
  = the Short3 array in the block's typed-record area (43 entries) - NOT box-normalised:
  raw x,y sit at -32768..-32052 / -32577..-29594 with z spanning the range; decode unknown
  (bone-relative? packed?). BoundingInfo here is `ffffffff, u32 (nonzero), min xyz, max xyz`
  in feet (coach 5.3 ft). Files: `sgsm/common/xplrgeo.viv/base_lod[BDRS].ebo` (player
  bodies), `player_<name>B.ebo` and `*_head.ebo` = Morph banks (Morph, MorphTargetNameArray,
  MorphStreamHeader, MorphData with coord/normal/uv/colour deltas), `sgsm/stadia/<team>.viv/
  <team>std.ebo` stadiums (300 KB), `crowd3d__lodB.ebo`, no `*skel.ebo` (skeleton elsewhere).
- Verified 2026-08-29 01:00: NBA Live 2005 Float3 objects decode correctly with the current
  code (`base_lodR.ebo` = a T-posed player, `atlastd.ebo` = the Atlanta stadium bowl, 74
  lists / 13k tris); only the Short3-positioned lists (base_lodB/D high LODs, coaches, guests,
  trophies, `atlacrt` court) still need their position format.

## EBO textures (2026-08-29 night)

The EA Sports `.ebo` games (NHL 2005 / 06, NBA Live 2005 / 06, FIFA 05, 2006 FIFA World Cup,
UEFA CL) ripped thousands of models at 0% textured because their shape files were rejected:
the tag is written in MIXED CASE (`ShpG`, not `SHPG`), and the file is a one-image variant of
the EA shape format rather than the usual name / offset table:

    char "ShpG" | u32 size (little-endian) | u32 count (1) | u32 | u32 data offset (0x40) |
    u32 data size | char name[8] ("REF_", "IGRL", "COCH") | "G427" | "Buy ERTS"

and at the data offset `u8 code (0x1e) | ... | u32 width (+0x18) | u32 height (+0x1c) | ... |
pixels (+0x30)`, where `data offset + data size == file size`.  The GX format follows from the
bytes per pixel (NHL's actor shapes are all 256x256 CMPR); `gcrip/formats/ea_shape.py`
detects the variant by `offset == 0x40 and offset + size == len(file)`.

Binding: the `.ebo` Material imports only name a runtime slot (`gTexture_RMRuntime`), so
`plugins/ebo.py` takes the `.gsh` that sits beside the model in the same archive - by stem
(`referee0.ebo` -> `referee.gsh`, `icegirl2005.ebo` -> `IceGirl.gsh`) or, when the folder has
exactly one shape, that one.  NHL 06 `gamedata/actors.viv`: 8 scenes, 9,308 triangles, 98 of
98 materials bound (was 0).  NHL 2005 decodes 8 of 8 shapes, NBA Live 06 5 of 7.


## `MMAP` format 11 is `C8` (2026-09-01)

GX leaves 11 undefined, and `decode_mmap` raised on it - **863 textures across four discs**,
847 of them on NASCAR Thunder 2003, the rest on NFL Street 2, NASCAR 2005 and NCAA Football
2003.

It is 8 bits a pixel, from the size field alone: both samples are 24x20 with `size` 480, which
is `w * h` exactly and matches no other depth.  What identifies it as *paletted* rather than
`I8` or `IA4` is the palette block it carries - **256 `RGB5A3` entries, every one populated
with a plausible colour**, and the pixels use all 256 index values.  A palette that complete is
meaningless unless the pixels are indices into it.

**Smoothness cannot settle this one and should not be quoted as if it had**: on 480 pixels
`C8` scores 1.54, `I8` 2.13 and `IA4` 1.11, all within the noise floor.  The palette is the
evidence.

A correction to the header note above while I was in there: the palette block's first `u16` is
**the texture's own format code**, not a constant 1 - it reads 11 on a format-11 MMAP.

Only 11 is mapped.  7 stays undefined and still raises, so the map does not become a licence to
guess at the next unknown code.


## The `.ord` tail comes in two forms, and nine discs use the other one (2026-09-01)

`gcrip` read only `.orp` - a `u32` holding the `.ord` size, then the rest of the ELF.  Nine
discs pair their `.ord` with **`.orl` instead: the same remainder with no size prefix**, and on
every one of them each `.ord` raised *section table outside the file (missing .orp?)*.

**9,732 models across nine discs**, and the manifests make the split unmistakable:

| `.ord` | `.orp` | `.orl` | failed | triangles | disc |
|---|---|---|---|---|---|
| 3,496 | 0 | 3,496 | 3,496 | 0 | MVP Baseball 2005 |
| 2,310 | 0 | 2,310 | 0 | 0 | G3VE69 |
| 1,919 | 0 | 1,919 | 1,919 | 0 | MVP Baseball 2004 |
| 1,511 | 0 | 1,511 | 1,521 | 0 | NHL 2004 |
| 1,485 | 0 | 1,485 | 1,483 | 165 | NHL 2003 |
| 971 | 0 | 971 | 971 | 1,872 | FIFA Street 2 |
| 521 | 0 | 521 | 521 | 1,272 | FIFA Street |
| 306 | 0 | 306 | 350 | 0 | Def Jam Fight For NY |
| 247 | 0 | 247 | 247 | 0 | Fight Night Round 2 |

against FIFA 07, FIFA 06, FIFA Soccer 2004/2005, UEFA and 2006 FIFA World Cup, which all carry
`.orp` 1:1 with `.ord`, fail nothing and produce over two million triangles each.  **A disc
carries one form or the other, never both.**

### What proves the join rather than assuming it

The ELF's own arithmetic.  `e_shoff + e_shnum * e_shentsize` is where the section table ends,
and on NHL 2003's `pane_lowerleft` pair that is **21,664 - exactly `len(.ord) + len(.orl)`**.
So the tail is appended whole, and `join` now detects the prefix instead of assuming it (a
leading word equal to the `.ord` length is one, anything else is not) and then **accepts the
result only if the table fits**.  A wrong pairing fails there rather than parsing to an empty
object, which is the failure mode worth guarding: `ord + orl[4:]` also "parses", into nothing.

### What this does and does not buy

NHL 2003 goes from 1,483 failures to **0 across 1,310 `.ord`** - but those objects hold no
models and no bones, so that disc gains clean records rather than geometry.  Whether models
appear is per-disc and the re-rip will show it; the fix removes the error, and only the discs
whose `.ord` actually carry `__Model` sections will gain triangles.

## FIFA 2003: the `.orp` prefix is an offset, and the objects are skeletons (2026-09-02)

FIFA Soccer 2003 recorded **994 failures, all `EaglError`**, 926 of them in `data/dplyrgeo.big`.
Two separate things were wrong, and the second corrects the first.

### The recorded errors are stale, and the join was wrong

Re-run today the sibling is found every time and nothing raises across 40 sampled `.ord`.  But
`eagl.parse` returned `models=0, skeleton=0` **with no warnings**, because the join was building
a broken ELF that still passed validation.

`join` read the tail's leading `u32` as *the `.ord`'s length* and appended the rest.  It is an
**offset**.  On FIFA 2003 it is **7,840** against a 27,232-byte `.ord`, and the tail belongs
*inside* the object, not after it.  Where the prefix happens to equal the `.ord` length an
overlay at that offset is the same bytes as appending - which is exactly why the length reading
worked on every other disc for so long.

Two identities confirm the offset reading, on **12 of 12** sampled pairs:

* `prefix + len(tail) - 4 == e_shoff + e_shnum * e_shentsize`;
* overlaid, the section table resolves - `.data` (7,776 bytes at 64), `.shstrtab` **at 7,840,
  exactly the prefix**, `.strtab`, `.symtab`, `.rel.data`.  Appended, every section name came
  back as `"ELF"` with size 0, which is what reading a table that is not there looks like.

`_table_fits` could not catch that: it is arithmetic only, and `11,920 + 6*40 = 12,160` sits
happily inside a wrongly-joined 31,556-byte file.  Joins are now accepted by `_table_reads`,
which requires the section *names* to resolve.

### Correction: these are not lost meshes

An earlier version of this note said 933 player objects were "being read as empty" and implied
their geometry was lost.  **That was wrong.**  The symbol table says what they are - 60 symbols,
one `__MATRIX4 *:::EAGLAnimationBuffer` and the rest `__Bone:::Player____model1020308739__0.<joint>`
- `RThumb1`, `TorsoChn`, `Jaw-DJ`, `LLowLeg-DJ`.

They are **skeletons and animation buffers**.  There is no `__Model` in them because there is no
mesh in them, so `models=0` is the correct answer and always was.  The container name
`dplyrgeo.big` and the `__model` in the filenames are identifiers, not a promise of geometry.

What the fix buys is real but narrower than it first looked: the ELF now parses instead of
pointing at zeros, so the bone data is reachable at all, and any disc whose prefix differs from
its `.ord` length was being joined wrongly.

### The display list is not always the last stream

With the join fixed, FIFA 2003's `static.big` / `pstatic.big` objects parsed and still produced
nothing.  `_decode_packet` was returning `None` on the first `return` it reached, silently.

The packet entries for `PitchDetail` read::

    [1] tag __const MATRIX4        <- the anchor
    [2] count 1584  ptr    32      attribute stream
    [3] count 1584  ptr 19040      attribute stream
    [4] count 7552  ptr 31712      **the display list**
    [5] count    1  ptr 39376      the __EAGL::TAR texture pointer
    [6] tag __EAGL::GeoPrimState

`streams[-1]` took entry 5 - a one-byte "display list" - and the opcode check then failed.  The
display list is now chosen by that same opcode test rather than by position, searching from the
end so the ordinary case is unchanged.

**Result on FIFA 2003: 14 of 22 `static.big`/`pstatic.big` objects now yield 10,567 triangles**,
against 0 before - `Player__HiBody4` 4,977, `Player__MedBody` 1,299, `Player__LowBody` 669,
`Player__Cards` 28.  Those are real player body meshes, and they reached the reader only because
their `.orp` lives in `ngccache1/2.big` rather than beside them, which is the cross-container
sibling fix.

So three defects were stacked on this disc, and all three had to go before a triangle came out:
the sibling lookup, the prefix-as-length join, and the display-list choice.

### Measured across the whole disc

Taking all six EAGL containers on FIFA 2003 together - `static`, `pstatic`, `staticps`, `disk`,
`ngccache1`, `ngccache2` - and running the old rule against the new one:

| display-list rule | objects with geometry | triangles |
|---|---|---|
| last stream (old) | **0 of 89** | 0 |
| first stream opening on a GX opcode (new) | **81 of 89** | **44,927** |

The old rule is simulated faithfully - the last stream, accepted only if it passes the same
bounds and opcode test the old code applied inline - so this is like for like.  Every EAGL
object on this disc carries the trailing texture pointer, which is why the disc reported
nothing at all.

**No regression elsewhere**: the new rule searches from the end, so where the display list *is*
last it is found first and the answer is unchanged - there is a test for that.  A check on MVP
Baseball 2004 came out 0 against 0, which confirms no regression but proves nothing about the
gain: its `.orl` halves live in containers that sample did not read.

### Every dropped packet now says why

`_decode_packet` had five `return None` paths and only two of them recorded a warning.  The
three silent ones are what let FIFA 2003 report a healthy zero for 89 objects: a packet that
returns nothing without saying so is indistinguishable, in the report, from a disc that has no
geometry.

All five now append a warning, and the effect is immediate.  Of the objects on FIFA 2003 that
*still* yield nothing after the three fixes, the reasons are no longer a mystery:

| warning | packets |
|---|---|
| `0 attribute streams, need at least 2` | 32 |
| `unknown header c61601fec6160000` | 4 |

Those are leads a future session can pick up from the report itself rather than by
instrumenting the parser by hand, which is how this one had to find them.

### A packet can bind more than one matrix

The very first thing the new warnings said was `0 attribute streams, need at least 2`, on 32
packets.  The cause is visible the moment the entries are printed - FIFA's shadow packets bind
**two** matrices back to back::

    [3] __const MATRIX4:::EAGL::ViewPort::gpModelViewMatrix   <- anchored here
    [4] __const MATRIX4:::EAGL::ViewPort::gpViewMatrix        <- and stopped here
    [5] count  56  ptr  352      attribute stream
    [6] count  56  ptr 1024      attribute stream
    [7] count 544  ptr 1248      display list

The collection loop requires an untagged entry, so anchoring on the first matrix and collecting
immediately found nothing at all.  Skipping the whole run of `__const MATRIX4` tags first takes
FIFA 2003 from **81 of 89 objects and 44,927 triangles to 85 of 89 and 45,647**.

That class of warning is now gone from the disc.  What is left is 27 warnings, all specific:
11 `unknown header c61601fec6160000`, 8 `display list does not chain at stride 4`, 5
index-out-of-range, 1 `no display list among 5 streams`, 1 other unknown header.  Every one of
those is a lead with an address attached, which is the whole point of having made the drops
speak.

### A vertex can carry one matrix byte, not just two or none

The next warning the disc gave up was `display list does not chain at stride 4`, eight times.
Printing the list settles it in one line - `98 00 07` is a seven-vertex strip and the records
that follow are **five bytes each**::

    98 00 07  2d 00 00 00 00  2d 00 00 00 00  2d 00 01 00 01  ...

One position-matrix byte, then a `u16` per attribute stream.  The code tried `2 + 2*nattr`
(both matrix bytes) and `2*nattr` (neither) and nothing between.

Two details made this a three-step fix rather than one:

* **Order.** A list that chains at `2*nattr` *also* chains at `1 + 2*nattr`, so trying one
  second re-read packets that were already correct and lost two triangles.  `MATRIX_BYTE_ORDER`
  is `(2, 0, 1)` and the constant carries that reason.
* **The attribute offset.** `f0` was derived from the stride - `2 if stride == 2 + 2*nattr else
  0` - which is only right when the choice is two-or-none.  With one matrix byte it read the
  indices a byte early and every one came out enormous: *"index 14592 outside 56 vertices"*.  It
  is now the matrix-byte count the search actually settled on.

**FIFA 2003 finishes at 89 of 89 objects and 46,251 triangles**, from 0 at the start of this
work.  The warnings that remain are 11 `unknown header` on *skeletons*, five index complaints
and one missing display list - none of them geometry being lost.

### The skeleton magic was a tag, not a magic

The last warning class on the disc was `unknown header c61601fec6160000`, eleven times, from
`_parse_skeleton`.  Set beside the constant it was checked against, the answer is immediate:

    _SKEL_MAGIC   c0da 01fe c0da
    FIFA 2003     c616 01fe c616

The same **shape** with a different tag - a `u16`, the marker `01 fe`, then the same `u16`
again.  The word that follows is the bone count, and it confirms the reading: **51, against
exactly 51 `__Bone` symbols** in the same object.

Checking the shape instead of the literal bytes gives FIFA 2003 **11 skinned scenes, the
largest carrying 51 joints**, where it had none.  The one header on the disc that is genuinely
not a skeleton - `0743 0050 c3d4`, whose marker is `0050` - is still rejected, and there is a
test holding both halves of that.

## Do the FIFA 2003 fixes generalise?  Partly - and the honest answer is no

Seven defects came off this reader in sequence, all found on one disc.  Checking a second,
**Fight Night Round 2**, answers the obvious question and the answer is not the flattering one.

Its 247 `.ord`/`.orl` pairs are found, joined, and read: 121 symbols each, 76 `__Bone`, 2
`__Model`, 275 shader references, section table valid.  And **0 objects with geometry**.

First, one more layer of silence, and the worst of them.  `extract` attaches `obj.warnings` to a
`Scene`; an object that produces no `Scene` therefore discarded *every* diagnostic it had
generated.  Fight Night lost 247 objects without a line of explanation, and the readers'
warnings - carefully added the commit before - never reached the report.  A barren object now
raises with a summary of its own warnings.

What it then says is: **`no display list among 3 streams`**.  Dumping the streams shows why, and
it is not a bug:

    count 125  ptr 1596   3e 6a ca 8e 42 2d 00 56 ...   op 0x38
    count 125  ptr 5348   02 e1 d4 a0 2e f7 fc ad ...   op 0x00
    count 125  ptr 7852   b9 2d 14 6e 3c 30 61 40 ...   op 0xb8

Three streams of **equal count**, all holding floats, none opening on a GX primitive opcode
(`0x80`, `0x90`, `0x98`, `0xa0`).  This generation stores parallel attribute arrays and has no
display list in the packet at all - the primitives must be described somewhere else.

So the seven fixes are FIFA-2003-shaped.  They take that disc from 0 to 89 of 89 objects, and
they do nothing for Fight Night, which needs its own reading.  What *did* generalise is the
diagnostics: the disc now says what is missing instead of reporting a healthy zero.
