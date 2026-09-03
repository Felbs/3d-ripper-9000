# Acclaim `.GDF` meshes - All-Star Baseball 2002 / 2003 / 2004 (2026-09-02)

Acclaim ``.GDF`` / ``.SKN`` meshes - All-Star Baseball 2002, 2003 and 2004.

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

## `.SKN` is declined, and why

`.SKN` uses a 36-byte name and carries a **23-bone skeleton** - 32-byte name slots, `ROOT`,
`L_UP_LEG_DUM`, `L_UP_LEG`, `L_LOW_LEG`, `L_FOOT`, `L_TOE` - between the material names and
whatever follows.  Read with the `.GDF` shape those bone names land where the mesh records
belong and the file claims four billion triangles.  Searching every 4-byte offset from 76 to
4,000 for a mesh table whose radius identity holds finds **nothing** in any of the three
samples, so the skinned vertex record is not the one above.  The reader refuses them rather
than half-reading them.
