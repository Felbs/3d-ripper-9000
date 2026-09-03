# RenderWare GameCube native geometry (2026-09-03)

RenderWare GameCube **native** geometry - the unchunked tail of a CLUMP.

Piglet's BIG GAME carries 936 CLUMPs and `plugins/renderware.py` returns a scene for 68 of
them, because most of the geometry is flagged ``rpGEOMETRYNATIVE`` and holds no vertex arrays
where RenderWare would put them.  ``docs/OPEN.md`` recorded the data as "a raw block inside the
clump ... at entropy 7.37 ... **with no GX display lists in it**".

It is GX display lists.  A CLUMP's chunk walk covers STRUCT and FRAMELIST and then stops, and
everything after that - 2,215,106 bytes of a 2,232,166-byte clump - is native data: display
lists and vertex arrays with no chunk framing at all.

A **group** is one mesh::

    0x98 strips, 8-byte vertices of four big-endian u16, zero padding between
    ... 16 bytes ...
    positions   f32 x 3 big-endian, N of them
    ... 16 bytes ...
    normals     f32 x 3 big-endian, N of them
    ... 16 bytes ...
    colours     RGBA8, N of them
    texture coordinates  f32 x 2 big-endian, N of them

Two identities carry the whole reader, and neither can be satisfied by accident:

* **the indices cover exactly 0..N-1** - every one of a group's strips indexes the same array
  and uses every entry of it, so `distinct == max + 1` both fixes the vertex count and says
  whether a candidate strip run is a group at all.  A false run found at 155,403 claims 53,054
  vertices with 100 distinct values and is refused by this alone.
* **the normals are unit length** - 3,252 consecutive `f32` triples of length 1.0 to 4.15e-08 on
  the first group.  This is what locates the arrays: search forward from the lists for the
  unit-length block, and the positions are then a fixed ``16 + N * 12`` before it.

That last relation is the reason nothing has to be fitted.  Searching for the *positions* by
triangle locality does not work and actively misleads - it finds index arrays, which have tiny
triangles in a wide box, and prefers them (see ``gcrip/oracles.py``).  Searching for the
*normals* cannot: no other array in the file is 3,252 unit vectors in a row.

Measured on the biggest CLUMP in the first 40 MB of ``PIGGCN.pkd``: **36 candidate groups pass
containment, 25 of them resolve to positions and normals, ~45,592 triangles**.  The eleven that
do not find a unit-length block are declined rather than guessed at.

## Measured

On the biggest CLUMP in the first 40 MB of `PIGGCN.pkd` - 2,232,166 bytes, native tail at
17,060:

| | |
|---|---|
| candidate groups passing containment | **36** |
| groups resolved to positions + normals | **26** |
| triangles | **35,568** |
| worst `|n| - 1` over the resolved groups | **8.48e-08** |
| time | **1.2 s** |

The ten groups that find no unit-length block are declined and counted in a warning, not
guessed at: the positions are located *from* the normals, so without them there is nothing to
read.

## Why the search runs forwards from the lists, not outwards from the normals

The first version scanned the whole gap after each group's lists for a unit-length block and
took 9.6 s a clump.  Trying instead the few offsets just past the lists as *candidate
positions*, and letting the normals at `+ N * 12 + 16` confirm each one, is the same test
applied in the other direction: **1.2 s, and one more group** - 26 rather than 25 - because a
group whose normals sit beyond the next group's start is still found.

Measured leading gaps between the lists and the positions are 1, 5, 13 and 21 bytes, so
`LEAD_SCAN = 64` covers them with room to spare.


## Across every clump in the slice, and the three things that were in `renderware.py`'s way (2026-09-03)

Running both readers over all **146 clumps** in the first 40 MB of `PIGGCN.pkd`:

| reader | clumps | triangles |
|---|---|---|
| `renderware.py` before | 3 | 1,198 |
| `renderware.py` after | **120** | **107,040** |
| `rw_native.py` | 15 | **182,771** |
| **total** | | **289,811** |

in 0.2 s.  The two readers overlap on 11 clumps and never on a triangle: a group is left to
`renderware.py` when its display lists fall inside a GEOMETRY chunk, and read here otherwise
(`owned_spans`).  The biggest clump needs both - 26 small geometries as GEOMETRY chunks, and a
154,856-byte STRUCT that is a 4,054-triangle native group with no GEOMETRY around it.

`renderware.py` was returning scenes for 68 of Piglet's 1,001 geometry assets because of three
things, each fixed in `rwstream.py` / `rwgc.py` and each with a test:

1. **A chunk's declared size can overshoot the next header** - FRAMELIST by 21 bytes, MATLIST
   by 70 - so the walk landed inside the next chunk and read garbage as an id.  The library-id
   stamp is unmistakable, so when the declared end is not on a header but one sits within 256
   bytes before it, the walk steps back.  A correct size is never second-guessed.
2. The EXTENSION under GEOMETRY was being read 9 bytes long - an artifact of (1).  With the walk
   right, BINMESH and NATIVEDATA are where RenderWare puts them.
3. **The native header is a different shape.**  Not the attribute table `decode_native` reads
   (it refused 139 of 139 with *attribute table out of range*) but array offsets declared at
   +24 and a mesh table at +68, arrays padded to 32, one index per attribute a byte wide up to
   256 vertices and two above.  `rwgc.decode_native_piglet` reads it; the identity is that the
   position array's declared span is `vertices * 12` rounded up to 32, and the mesh table's
   sizes sum to the first array offset.  Ten header shapes from 76 to 116 bytes, 1 to 6 meshes,
   both index widths, and the largest index never exceeded `vertices - 1`.
