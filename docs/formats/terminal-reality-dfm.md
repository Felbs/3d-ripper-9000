# Terminal Reality `_dfm` header and part table (2026-09-02)

Terminal Reality ``_dfm`` meshes - the header and part table.

Cluster 6.  The geometry itself is still unread; what this settles is the part table, and with
it **the per-part bounding box that the vertex work was missing**.  ``docs/OPEN.md`` recorded
that "both bounding-box tests come back empty" and that every normal-agreement fit was
planar-degenerate.  There is a box per part, sitting in plain sight in the table.

Little-endian::

    +0    u32   version        2 on every sample
    +8    u32   part count
    +12   u32   bone count     equal to the paired `.SKL`'s
    +24   char  skeleton file name, NUL then `BAADF00D` fill
    +104  count x { char name[30]; u32 bone; f32 box[6] }   stride 58

As in the skeletons (:mod:`gcrip.formats.tr_skl`), short names are padded with ``BAADF00D``
rather than zeroes, which is what made these records look variable-length.

Three checks agree across two meshes of very different sizes - 59 parts in ``soldier.dfm`` and
23 in ``mentor.dfm``:

* **every name decodes**, 59 of 59 and 23 of 23 - ``binoculars2``, ``canteen``, ``gasmask``,
  ``Lbladehilt``;
* **every bone index is inside the skeleton**, 59 of 59 and 23 of 23;
* **every box has `min <= max` on all three axes**, 59 of 59 and 23 of 23.  Six floats in a row
  satisfying that on every record is not something a wrong stride produces.

And the mesh names its skeleton twice over: the string at +24 is ``SOLDIER_DEFAULT.SKL``, and
the bone count at +12 is 82, exactly what that file holds (68 and ``MENTOR.SKL`` for the other).

**What is still open** is the geometry, which follows a material table - the first record after
the parts carries ``1.0, 1.0, 32.0`` and the texture name ``SOLDIER.TIF``.  The tail is only
9.9% plausible ``f32``, so the vertices are quantised, which agrees with the 20-byte vertex the
size arithmetic implied.  The boxes here are what a candidate layout should now be tested
against: decode a part's vertices, scale, and they must land inside that part's box.

## The parts name the bones they hang off

Resolving each part's bone index through the paired `.SKL` gives a result that reads like
English, which is the strongest check of the pair together:

| part | bone |
|---|---|
| `binoculars2` | `Bip01 L Hand` |
| `waist` | `Bip01 Spine` |
| `chest-open` | `Bip01 Spine2` |
| `holster` | `Bip01 foldedblade` |
| `pouch1` | `Bip01 SheathR` |

Binoculars in the left hand and a waist on the spine are not what a mis-read table produces.
All 59 and all 23 bone references resolve inside their skeletons.
