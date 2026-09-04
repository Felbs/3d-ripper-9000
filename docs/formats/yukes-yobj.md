# Yuke's `YOBJ` meshes - the `.ymg` files of the WWE discs

WrestleMania X8 carries 732 of them (31 MB) and WrestleMania XIX 1,464 (28 MB); the two Day of
Reckoning discs have 1,099 and 207, though nearly all of theirs are `DUMY` wrappers rather
than `YOBJ` (see the note).  All four discs produced no models at all.

Big-endian:

    +0    char magic[4]   "YOBJ"
    +12   u32 table offset
    +16   u32

The table holds one record per mesh, but **the record length is not constant** - it drifts by
four bytes between records because the trailing float block varies - so records are found by
the constant word `0x0a000000` that every one contains rather than by a stride.  Relative to
that marker at `m`::

    m-8   u16 vertex count
    m+4   u32 -> positions
    m+8   u32 -> normals
    m+16  u32 -> the index block

**Every offset in this format points eight bytes before its data.**  That is the whole trick:
read the arrays at the offset itself and the first normal comes out with a length of 7.05
instead of 1, while the other eleven are exactly 1 - which reads like an off-by-one in the
count rather than a block header.  At `offset + 8` all of them are unit vectors.

Positions and normals are `count` triples of big-endian `f32`, and `normals - positions ==
count * 12` has to hold.  The index block is a run of `u32 count` followed by that many
`u16` triangle-strip indices, packed with no padding, starting at `C + 16` - the extra
eight bytes past the usual `+8` being a small header the strips follow.

## How well it checks out

The positions and normals are confirmed on both variants and are not in doubt: **981 of 981
records** in X8's `dummy_x8.ymg` and **10,445 of 10,445** normals in XIX's `0_2.ymg` come
out unit length at `+8`, which no wrong layout does.

On X8 the index lists read too - 8,104 meshes, 125,428 vertices and 47,090 triangles from ten
files, with an unsigned normal agreement of **0.983 and 98% of meshes above 0.9**.  Winding is
inconsistent as it is in Terminal Reality's `_smf` and A2M's `.gc`, so triangles are flipped
to agree with their own stored normals and the figure quoted is the unsigned one taken before
the flip.

**XIX's index block is laid out differently** and is not read here: it opens with a table of
eight-byte entries (`u16`, `u16`, `u32` pointer) rather than going straight into strips.
A reader for that was tried and produced 97 triangles at 0.451 agreement while also cutting
X8 from 8,104 meshes to 5,480, so it is left out and the files are declined instead of being
turned into rubbish.

## Results

| disc | sampled | meshes | vertices | triangles | unsigned agreement |
|---|---|---|---|---|---|
| WrestleMania X8 | 10 of 732 | 8,104 | 125,428 | 47,090 | 0.983 (98% > 0.9) |
| WrestleMania XIX | 10 of 1,464 | declined | - | - | - |
| WWE Day of Reckoning | `000_0.ymg` (one wrestler) | 3 meshes, 39 groups | 2,478 | 3,542 | 0.908 signed, textured from its `.tex` |

Ten files of 732 on X8, so the disc total will be far larger.

## Still open

* **XIX's index block**, described above - the geometry arrays read perfectly there, only
  the primitive lists do not.
* ~~`DUMY`~~ - **read 2026-09-03**, see the Day of Reckoning section below.  The text that
  follows is the earlier dead end, kept because the `.pms` nesting it describes still stands.
* **`DUMY`**, which is what nearly every `.ymg` on the two Day of Reckoning discs is
  (147 of 150 sampled, and all 166 `.pms` and 150 sampled `.ypc`).  It is **not** a thin
  wrapper around a `YOBJ`, which is the first thing to try and the first thing to rule out.

  `3s01A.pms` (2,688,516 bytes) opens `DUMY`, `u32 16`, sixteen zero bytes, then a **`POF0`**
  chunk at +24 with a `u32` size of 2,688,064.  `POF0` is a pointer-relocation table, and the
  two chunks account for the file exactly: `24 + 8 + 2,688,064 = 2,688,096`, then a second
  `POF0` of 412 bytes runs to the final byte.  Inside the first payload are five more `DUMY`
  chunks (10,252, 60,208, 186,932, 252,772, 330,372), so it nests.

  There is **exactly one `YOBJ`** in the file, at 2,678,040, and it is a 10 KB tail that the
  reader here declines - so the geometry on those discs is not simply `YOBJ` behind a wrapper.
  The relocation tables suggest the offsets inside are meant to be fixed up at load, which
  would explain why a `YOBJ` lifted out on its own does not resolve.  That is where to start.


## XIX's index block, read (2026-09-03)

The block that "opens with a table of eight-byte entries" is a **group table**: an entry a
group, `u8, u8, u16 strips, u32 ptr`, the pointer landing 8 bytes before the group's strips;
a single-group record is one entry pointing at itself.  Each strip is `u32 corners` followed
by that many **10-byte corners**: `u16 vertex index, RGBA8 colour, s16 u, s16 v` (/ 32768).
The earlier attempt produced 97 triangles at 0.451 because it read the entry's count as
corners and the pointer as the data start; read as strips from `ptr + 8`, `0_2.ymg` gives
every one of its 6 records - 6,545 triangles at **0.989** unsigned agreement, with uvs and
vertex colours the X8 variant never had (its strips are bare indices).  The group's leading
bytes (0, 1, 2, ... 16, 26, 65, 68) are material indices into a table not yet tied to the
`.tex` files, so the meshes come out with uvs but no texture bound.  **Tied since the Day
of Reckoning read (2026-09-03)**: version 3 carries the same header tables at +0x18 (20-byte
materials) and +0x20 (16-byte texture names), the group byte is the material index, and the
material's TEV stages name the texture - `0_2.ymg`'s arena is 59 primitives over 53
materials (`tekin_01`, `yuka_01`, `kabe_02` ...), each looked up as `<name>.tpl` in the
sibling `.tex` pack.


## Day of Reckoning, read (2026-09-03)

The `.ymg` on both Day of Reckoning discs **are** thin wrappers after all: `"DUMY", u32 16,
sixteen zero bytes`, then a `YOBJ` whose `u16` at +8 is **4** (X8 and XIX say 3), then a
`POF0` pointer-offset table.  What made the earlier attempt fail was the assumption that a
version-4 YOBJ shares version 3's f32 arrays: it does not.  The layout was read against the
renderer in DoR's `main.dol` (no symbols, but the strip-drawing loop at `0x800bdb2c` is
unmistakable: `GXBegin(GX_TRIANGLESTRIP, 0, count)` then, per corner, the same `u16` written
twice - position and normal index - and `s16 u, v`; four corner layouts by two flag bits, the
others adding an RGBA8 colour or dropping the uvs, which is exactly XIX's 10-byte corner).
Every pointer again lands eight bytes before its data.

```
+0x08  u16 4, u16 meshes, u32 0x40
+0x10  u32 bones, ptr        64 B: char name[16], i32 parent, f32 t[3], f32 r[3], f32 length, 0
+0x18  u32 materials, ptr    20 B: rgba diffuse, rgba, rgba, u16 flags, u16, ptr TEV block
+0x20  u32 names, ptr        16 B texture names ("face" NUL "bmp" - the dot is written as NUL)
+0x28  u32, ptr              hair / accessory records, 0x68 bytes
+0x48  mesh records, 0x30 B: u16 vertices, u16, u8, u8 skin runs, u8 groups, u8,
                             u32 0x0a000000, ptr data, u32 0, ptr runs, ptr groups,
                             f32 centre[3], f32 radius, u16[4]
data    vertices x 12 B: s16 position[3] / 64, s16 normal[3] / 4096
groups  8 B: u8 material, u8 strips, u16 strips, ptr -> strips of u32 corners then
        6-byte corners: u16 index, s16 u, s16 v (/ 1024)
runs    16 B: ptr weights, u32, u8 bone[3] (0xff none), u8 bones, u32 vertices
TEV     u16 stages, u16, u8[4], u8[16], ptr, ptr, then 20 B a stage, its last byte a
        texture-name index (0xff none)
```

Three things worth writing down:

* **The normal is stored rotated.**  The triple at +6 is unit length in every record, but read
  as (x, y, z) it agrees with the face normals at 0.37; as `(n1, n2, n0)` at 0.97-0.998, and
  the five other orders sit below 0.6.  So the file holds (nz, nx, ny).  With that order the
  strips want the opposite of the usual parity (the signed agreement is -0.97 with the
  usual one), which the reader takes as the winding rule.
* **One group is one material**, and the group's first byte indexes the 20-byte material
  table (a wrestler's 39 groups use materials 0-38 in order across its three meshes).  The
  material's TEV stages name the textures: a face is `g_skin, m_face, face, blood`, hair
  `g_skin, hair_00`, the mouth just `mouth`.  The plugin binds the first stage without a
  `g_` / `m_` / `n_` prefix (gradient, mask, normal-ish helpers) and looks the name up as
  `<name>.tpl` inside the sibling `.tex` pack - the same directory and stem first
  (`000_0.ymg` -> `000_0.tex`), any other pack after.
* **Vertices are in the bind pose, y down**: the head sits at y = -175, the `Bip` root at
  -102.  The plugin turns the model half a turn about x so it stands up without mirroring.
  The 16-byte skin runs (consecutive vertex ranges, up to three bones each, weights behind
  the pointer for two- and three-bone runs) are parsed for their counts but not applied, and
  no joints are exported yet; the bone table (parent, translation, Euler rotation, length)
  is read and listed in `extras.bones`.

`000_0.ymg` (a wrestler): 3 meshes - head (11 groups), hair strands (13), body (15) - 3,542
triangles, 18 of the 39 materials with a picture bound, signed agreement 0.908; the head's
`mouth` group is the low one at 0.68.  `m_body.ymg` and `mu0_024_l1.ymg` from `edit_data`
read the same way (0.95 / 0.93).  `camera.ymg` in `debug/viewer` is a bare version-3 file.
