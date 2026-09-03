# Kalisto TotemTech `.dgc` / `.ngc` (2026-09-02)

Kalisto's ``TotemTech`` engine: the ``.dgc`` data file and its ``.ngc`` index.

Spirits & Spells, Jimmy Neutron: Boy Genius and SpongeBob: Revenge of the Flying Dutchman - 383
files, 525 MB.  ``docs/OPEN.md`` recorded the blocker as *"the file has no directory at all -
nothing anywhere references the verified vertex data"*.

**There is a directory, and it is the sibling file.**  Every ``.dgc`` has a ``.ngc`` of the same
stem - 225 and 225 on Spirits & Spells, sharing all 225 stems - and the ``.ngc`` is plain text::

    -853289997 "WORLD"
    854756687 "DB:>LEVELS>LEVEL07A>MAP>LEVEL07A.TWORLD"
    596819425 "LEVEL07A"
    -1989570394 "DB:>LEVELS>LEVEL07A>MAP>3DNODEFAMILY>ROOT_LEVEL07A.T3DNODE"

A signed 32-bit hash and the object's typed path, one pair per line.  `LEVEL07A.ngc` holds
**3,519** of them, 3,519 of 3,520 lines parsing, and the type suffix says what each object is:

===============  =====
``T3DNODE``      1,473
``TSURFACE``       116
``TGA``            108
``T3DNODE_UDEF``    87
``TBITMAP``         77
``TBITMAP_MAT``     77
``TVOLUME``         56
``TMESH``           52
===============  =====

**And the hashes are in the `.dgc`, big-endian.**  Of the first 400 index entries, **400 are
found verbatim** as big-endian `u32`; as little-endian, **0** are.  They begin at byte 2,056 in
the same order the index lists them, mostly packed four bytes apart, so the data file is a
reference graph keyed by the hashes the sidecar names.

That is what the note was missing.  A `TMESH` hash appears twice - once as a reference and once
at its definition - and the bytes after the definition are float-dense: 74% plausible big-endian
`f32` in the 4 KB following `O_ECHAFAUDAGE_MESH.TMESH`.

This module reads the index.  Walking the graph from a hash to its geometry is the next step and
is not done here.

## Verified on the real files

`LEVEL07A.ngc` parses to **3,519 entries**, 3,519 of 3,520 non-blank lines, and **all 52
`TMESH` entries are located in the 5.3 MB `.dgc`** by their big-endian hash.  Both declared
identities hold.

## The record chain

The `.dgc` is a flat chain of records, packed to the byte (not aligned):

    u32 size          bytes from here to the next record
    u32 class hash    hash("MESH"), hash("SURFACE"), hash("BITMAP") ...
    u32 self hash     the object the .ngc names
    u32 name hash     its short name
    ... payload ...

`size` is a **size identity**: 2,027 of 2,036 hops land byte-exactly on the next record's own
header and the other nine within 32 bytes, so the walk restarts rather than truncating.  On
LEVEL07A it yields **3,673 records** - T3DNODE 2,763, TSURFACE 116, TVOLUME 107, TGA 102,
TBITMAP 77, TMESH 52.

## The mesh payload

At a fixed `+116` from the record start, three streams then the strips:

    u32 count, count * (f32 x, y, z)     positions
    u32 count, count * (f32 u, v)        texture coordinates
    u32 count, count * (f32 x, y, z)     normals
    u32 strips, per strip:
        u32 count, count * u16 index, u32 tag, u8 mode
    strips * f32                         one value per strip

Two identities say this is read correctly, and both are in the PROVEN class:

* **unit length** - across all 52 meshes the worst normal is `|n| - 1 = 7.7e-07`.
* **containment** - every strip index of every strip lands inside the position array on
  **52 of 52** meshes (max 424 against 425 positions on the first).  Not the vacuous kind:
  these are absolute floats with an explicit count, not a dequantised box.

Both `mode` values are triangle **strips**, not fans: scored as strips, adjacent face normals
agree at 0.82 (mode 1) and 0.81 (mode 2); scored as fans, at -0.66 and -0.38.

Result on LEVEL07A alone: **52 meshes, 21,142 triangles, 13,559 vertices**, exported to glTF.

## What is left

Which stream indexes the texture coordinates and the normals.  Further index lists follow the
strips, but the first of them reaches 356 where the file declares 354 texture coordinates, so
the obvious reading is wrong and the reader ships positions only.  The `T3DNODE` transforms
that would place each mesh in the level are also unread - meshes come out in local space.


## In the census (wave 24, 2026-09-03)

The three discs were re-ripped with the reader and the result is uneven, which is worth
recording rather than averaging away:

| disc | models | triangles |
|---|---|---|
| Spirits & Spells | **2,167** | **528,859** |
| SpongeBob: Revenge of the Flying Dutchman | 105 | 87 |
| Jimmy Neutron: Boy Genius | 93 | 34 |

Spirits & Spells was 0 before and is now half a million triangles.  The other two produce
models with almost no geometry - 87 and 34 triangles across ~200 models - so whatever they hold
is being read as `TMESH` records that are nearly empty.  Either those discs really are mostly
sprites and triggers, or their `.dgc` are a different vintage of the format.  Not yet looked at.
