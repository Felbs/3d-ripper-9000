# Acclaim `.GDF` / `.SKN` meshes - All-Star Baseball 2002 / 2003 / 2004 (2026-09-02, `.SKN` 2026-09-04)

Acclaim ``.GDF`` / ``.SKN`` meshes - All-Star Baseball 2002, 2003 and 2004.  `.GDF` is the
rigid props (bats, stadium pieces); `.SKN` is the skinned characters - player bodies,
hands, mascots - cracked 2026-09-04, section at the bottom.

``docs/OPEN.md`` recorded this as blocked on the index data: ``StickBat.GDF`` ended in ordinary
GX display lists but ``brewers.GDF`` had "none at any stride".  It has 182 of them.  They were
being looked for in the wrong place, because the attribute block was located by
``len(file) - attributes - trailing`` - right on the small files by coincidence, and landing in
the middle of the vertices on the big one.

Big-endian::

    +0    char name[20]
    +20   u32 materials
    +24   u32
    +28   u32 meshes
    +32   u32 groups
    +36   u32 attribute bytes
    +40   u32 display-list bytes
    +44   materials x char name[32]
          meshes x { char name[16]; u32 flags; u32 first group; u32 groups;
                     u32 vertices; f32 radius; u32 code; u32 offset }
          groups x 88 { ...; u32 material; u32 offset; u32 size; u32 vertices; u32 triangles }
    base  the attribute block
    base + attributes   the display lists

with ``base = 44 + materials * 32 + meshes * 44 + groups * 88`` - 340, 340 and 448 on the three
samples, the first two matching the offset the old note reached another way.

**The identity that settles the vertex layout is the radius.**  Each mesh record carries a
bounding radius, and the largest ``|v|`` over the decoded positions equals it to the last digit
on 5 of 5 meshes - 30.5068, 43.9925, 15.9865.  One number fixes the offset, the stride and the
byte order together, and a wrong reading cannot satisfy it.

The vertex stride comes from the mesh's ``code``:

===== ======  ====================================================
code  stride  layout
===== ======  ====================================================
1     12      ``f32`` position
2     32      ``f32`` position, ``f32`` normal, ``f32`` uv
3     24      ``f32`` position, packed ``u32`` normal, ``f32`` uv
===== ======  ====================================================

and the number of ``u16`` indices a display list spends per vertex follows it: **one** for the
position-only code and **three** for the others - and where there are three they hold the same
value every time, so the attributes are interleaved rather than separately indexed.

The second identity is the declared triangle count: summed over the groups it is what the
display lists actually produce, **1,274 of 1,274** on ``brewers.GDF`` and exact on the other two.

## Measured

| file | meshes | triangles | radius identity | declared triangles |
|---|---|---|---|---|
| `StickBat.GDF` | 2 | 44 | 2 of 2 | 44 of 44 |
| `BroomBat.GDF` | 2 | 76 | 2 of 2 | 76 of 76 |
| `brewers.GDF` | 1 | 1,274 | 1 of 1 | 1,274 of 1,274 |

## What the old note had wrong

* **The attribute block is not at `len(file) - attributes - trailing`.**  That gives 340 on the
  two small files - which is right - and 18,976 on `brewers.GDF`, which is 18 KB into its
  vertices.  The base is `44 + materials * 32 + meshes * 44 + groups * 88`, and it reproduces
  340, 340 and 448.
* **`brewers.GDF` is not missing its display lists.**  It has 182, at 34,912, all `0x98`
  triangle strips, and the largest index they use is 1,435 against its 1,436 vertices.
* **The word at +40 is the display-list size, not a trailing block.**  It is the sum of the
  groups' own sizes - 2,912 + 2,880 + 4,608 = 10,400 - and what follows on `brewers.GDF` is a
  separate `C8` texture.

## `.SKN` skinned characters (2026-09-04, `gcrip/formats/acclaim_skn.py`)

The old note below was right that the `.GDF` shape does not fit; the reason no mesh table
satisfied the radius identity is that `.SKN` has **no radius and no f32 anywhere** - it is
all s16 fixed-point behind a different header.  Big-endian:

    +0x00 char name[36]
    +0x24 u32 materials, bones, objects, geoms
    +0x34 u32 0
    +0x38 u32 tail_pad            # zero bytes between the geom records and section A
    +0x3c u32 0, u32 0
    +0x44 u32 sizeA, u32 sizeB    # attribute arrays / display lists
    +0x4c materials x char[32]
          bones     x char[32]    # ROOT, L_UP_LEG, ... names only - NO transforms
          objects   x 76 { char name[64]; u32 1; u16 first_geom; u16 geoms; u32 0 }
          geoms     x 52 { u32 flags; u32 dl_size; u32 blend_dl_size;
                           u16 verts, w1, w2, w3; s32 offs[8] }
          tail_pad zeros
    A = size - sizeA - sizeB      # the attribute arrays
    B = A + sizeA                 # the display lists

**The identity that settles it is tiling**: `0x4c + materials*32 + bones*32 + objects*76 +
geoms*52 + tail_pad == A`, exact on **17 of 17** samples (hands, five player bodies, ten
mascots), and it is what `is_skn` sniffs on - a `.GDF` cannot pass it.  Object records are
the mesh names (`whitehead`, `glove_L`, `hat_throwback`, `player`); `offs[7]` is the geom's
material index (`jersey`, `face`, `shadow`, `EnvMap`, ...).

**Everything is model space.**  A geom holds up to two copies of the same piece, and neither
is bone-local - the runtime XF matrices must be `boneWorld x inverseBind`.  That is the
opposite of the Darkened Skye lesson and it is what defeated the flat scans anyway, because
neither copy is a flat array of positions:

* **rigid copy** (`offs[0]` in B): GX strips of 7-byte vertices `{u8 pnmtx, u16 pos, u16
  nrm, u16 uv}` - indices unified, `pos == nrm == uv` per vertex and `max == verts-1` -
  over a 12-byte `{s16 pos[3], s16 nrm[3]}` array at `offs[2]` and u16 uv pairs at
  `offs[5]`.  `0x20`/`0x28` indexed-XF loads map each PNMTX slot (vertex byte / 3) to a
  bone, so every vertex carries one bone.  `flags & 1` inserts a texmtx byte after the
  pnmtx byte (8-byte vertices, `0x30` loads - the env-mapped heads and helmets).
* **blended copy** (`offs[1]` in B): strips of 6-byte vertices `{u16 pos, u16 nrm, u16 uv}`
  with `pos == nrm` and **`uv == pos + verts`** (both copies share one uv array: the first
  `verts` entries belong to the rigid copy, the rest to this one).  Rows are 16 bytes at
  `offs[3]`: `{s16 pos[3]; s16 nrm z-first; u8 w0, w1; u16 aux}`, sorted by weight count -
  `w1/w2/w3` in the geom record count its 1-, 2- and 3-weight vertices and `w1+w2+w3 ==
  rows == max pos index + 1` (held on every geom of every sample).  1-weight rows carry the
  sentinel `ff 00`; 2-weight rows have `w0 + w1 == 255`.  **Which bones blend is not in the
  file** - the CPU-skinning tables live with the animation data - so this copy is a baked
  bind pose, which is exactly what it renders as: T-posed players, mascots, a hand with
  fingers.
* **position-only copy** (`offs[4]`, the `shadow` material): 4-byte vertices
  `{u8 pnmtx, u16 pos, u8 0}` over bare `{s16 pos[3]}`.

Scales: positions s16/256, normals s16/16384 (unit to 0.03%), uvs s16/4096.  A geom whose
XF loads all name bone `0xffff` is a placeholder (unused accessory slot) and its indices
are garbage - skipped, not an error.  The five player-body files carry every accessory
stacked (three head skin tones, four glove variants, open/closed hands, catcher gear).

Fixed-point positions, two same-space copies per geom, weight-partitioned rows, no rest
transforms: none of it is the `.GDF` layout, which is why the radius sweep found nothing.

### Measured

| file | geoms | triangles shipped | notes |
|---|---|---|---|
| `Anim/HandL.SKN` | 1 | 204 | renders as a hand, fingers attached |
| `Anim/SkinRegH.SKN` | 65 | 10,920 | T-posed player, 63 named meshes, 2 placeholders |
| `Anim/SkinHevH.SKN` | 65 | 11,546 | the heavy body + catcher gear |
| `Mascots/MLB/montreal.SKN` | 1 | 718 | full T-posed mascot from one blended geom |
| `Mascots/Exp1/beluga.SKN` | 6 | 869 | body + rigid head at model-space height |

All four identities (`gcrip/formats/acclaim_skn.py::IDENTITIES`) hold on 17 of 17.

## What the pre-crack note had wrong (kept for the record)

`.SKN` uses a 36-byte name and carries a **23-bone skeleton** - 32-byte name slots, `ROOT`,
`L_UP_LEG_DUM`, `L_UP_LEG`, `L_LOW_LEG`, `L_FOOT`, `L_TOE` - between the material names and
whatever follows.  Read with the `.GDF` shape those bone names land where the mesh records
belong and the file claims four billion triangles.  Searching every 4-byte offset from 76 to
4,000 for a mesh table whose radius identity holds finds **nothing** in any of the three
samples, so the skinned vertex record is not the one above.  (It was looking for f32
records in a fixed-point file.)  The `.GDF` reader still refuses them, and its plugin now
defers to `acclaim_skn.is_skn` first because the loose `(36, 76)` shape accepted the five
player-body files by accident.
