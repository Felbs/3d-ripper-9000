# The `.gc` resource files - Teen Titans, Monster House, Ed Edd n Eddy, The Ant Bully, Happy Feet

**Five discs, all producing nothing at all**, and no note anywhere on the format.  Found by
censusing what the 204 empty discs actually contain: `.gc` appears on nine discs, six of them
empty, and the five above share one engine.  Happy Feet is the same engine with the files
stored compressed as `.cp`.

    Teen Titans      1,368 .gc   236 MB
    The Ant Bully      732 .gc    97 MB
    Monster House      633 .gc   167 MB
    Ed, Edd n Eddy      96 .gc    74 MB
    Happy Feet         684 .cp    93 MB  (zlib)

`.as`, `.sbk` and `.str` on the same discs are audio - cutscene streams, sound banks and music.
They are the bulk of the bytes and none of it is geometry, which is worth writing down because
they are the first thing an extension census points at.

## `.cp` is a `.gc` behind zlib

    u32 uncompressed size (big-endian), then a chain of zlib streams

Happy Feet's `dr_final.cp` inflates to a block that opens exactly like a `.gc` - the name
`dr_final` at +16.  Each stream in the chain decodes to 53,248 bytes, so it is block
compression rather than one stream.

## The file

Big-endian throughout.

    +0    u32 version        0x0301081f (Teen Titans) / 0x03020bc2 (Monster House)
    +4    u32, u32, u32
    +16   char name[12]      "ppdusk", "lu_ch10"
    +28   char project[16]   "tt06", "mhouse"
    +44   f32                +48 u32 1, u32 0
    +56   char "Build"
    +64   the type table: 256 slots of 8 bytes
              u32 count
              u32 offset     0xffffffff when the type is absent
    +2112 (0x840) the first payload

The table is exactly 256 slots on both discs and the first data lands at 0x840, so the table's
length is fixed rather than derived.  A slot's index **is** the resource type: 22 of the 256 are
populated on both files sampled.

Each populated slot points at `count` entries of eight bytes:

    u32 handle    (type << 24) | (file id << 8) | index
    u32 offset    absolute; 0xfffffffb means the resource has no payload

The handle's top byte repeats the slot index and its middle two bytes are constant per file
(`0670` on `ppdusk.gc`, `3e80` on `lu_ch10.gc`), which is what confirms the reading.

## A resource

    +0    u32 guard      0xabababab or 0
    +4    u32 version    the file's version again
    +8    u32 subtype
    +12   u32 handle     matches the table entry
    +16   char name[32]  "crate_big", "barrel_explosif", "fx_barrel_hit", "proxy:movieplayer"
    +48   16 bytes of 0xef  - a guard
    +64   the payload

Every resource is named, so models come out under the artists' own names.  Records inside a
payload are 32-byte aligned and padded with `0xef`, which makes the structure easy to walk by
eye.  `ppdusk.gc` holds **972 named resources** across 22 types, covering 4,780,800 of its
4,792,544 bytes.

Types seen (counts from `ppdusk.gc`): 19 the level itself, 23 effects (86), 24 the environment
(one resource, 1.29 MB), 34 props (185, `crate_big`), 40 proxies (164), 41 (97), 42 (158,
`dome`), 60, 67, 69, 70, 79, 89, 90, **91 geometry (83, 1.38 MB)**, 95 a transformation matrix,
99 (4).

## The geometry - verified on one mesh, not yet located reliably

Type 91 carries the meshes.  `gxscan` finds nothing in these files, and that is not because the
geometry is unusual: it is an ordinary **GX indexed triangle strip**, but the vertex array lives
elsewhere in the resource and the scanner has no way to find it.

A mesh header, taken from `barrel`:

    u32 vertex count      76
    u32 0xffffffff        a sentinel
    u32 vertex offset     592
    ... 44 bytes
    u32 display list start   5088
    u32 display list end     5792

The vertex is **56 bytes**, all big-endian:

    +0   f32 x, y, z
    +12  RGBA8 colour        0x5d5d5dff, 0x8f8f8fff - six distinct greys on this mesh
    +16  f32 nx, ny, nz
    +28  f32 u, v
    +36  f32 1.0, then 16 bytes of zero

The display list is `0x98 | u16 count | count * 8 bytes`, each vertex being **four u16
attribute indices** (position, normal, colour, texcoord - equal on every vertex seen, so the
array is already unified).  The list is padded with zeros to a boundary, so the walk finishes a
few bytes before the declared end rather than exactly on it.

**How well it checks out on `barrel`:** 76 vertices whose stored normals are all unit length
(mean 0.99991), a bounding box of 0.69 x 1.01 x 0.68 - a barrel - 8 strips giving 68 triangles
with **0 degenerate, mean normal agreement 0.9985, 100% within 0.7 and none inverted**, and
`592 + 76 * 56 = 4848`, which is exactly where the next `0xef` guard run begins.

## What is not done

**Locating the mesh headers generally.**  They are not at a fixed offset: reading `barrel`'s
offsets as constants finds 11 meshes in 972 resources and mean normal agreement falls to 0.62.
Scanning for the header's shape instead - the `0xffffffff` sentinel with a plausible vertex
count and offset either side, then requiring the display list to walk to a padded end - finds
**49 meshes and 5,462 triangles, but only 45% of them agree with their own normals above 0.9**
and 24 are below 0.5.  So the scan is finding the real meshes plus a similar number of false
positives.

Filtering those out by the normal-agreement score would make the number look excellent and
would be circular - the metric would no longer be evidence for anything, because it had been
used to select the meshes.  So nothing is shipped from this yet.

**The way in is the pointer chain, not a scan.**  The resource header carries offsets at +96 to
+124 that lead to the mesh block: on `barrel`, +104 holds 0x140, and 0x140 -> 0x160 -> 0x180 ->
0x1a0 -> 0x1c0/0x1e0, with the mesh header sitting at 0x1e0 + 52.  Walking that chain gives the
mesh headers exactly instead of guessing at them, and it is the next step.

Textures are also still open - no type has been identified as image data yet.
