# Kashmir `.dat` scenes (City Racer, Taxi 3, Speed Challenge: Jacques Villeneuve's Racing Vision)

Read 2026-09-04.  `gcrip/formats/kashmir.py`, `gcrip/plugins/kashmir.py`, `tests/test_kashmir.py`.

Three discs share a magic (`a4 0d 6d 71`) and a header string, `Created/Modified using
Kashmir` - the engine of a Romanian studio whose games were PC first.  The files are
**little-endian** and nothing in them is compressed; the "entropy 7.2 / gxscan finds
nothing" verdict in the open ledger was raw `f32` vertex data that no GX scanner would see,
because the meshes are not GX display lists at all.  Only the textures were converted for the
GameCube.

## The stream

Header: `magic, u32 2, u32 0, u32 1000, u32 0, u32 n, u32, u32, author\0, "Created/Modified
using Kashmir"\0, 13 zero bytes`; the chunk stream starts at `36 + n` (n = 46, 47, 49).  A
chunk is `u32 kind, u32 x, u32 length, payload`; kind 102 ends the stream.  Every object
begins its payload with an 8-byte id and a kind-8 chunk gives that id a name.

| kind | x | payload |
|---|---|---|
| 1 mesh | 101 | id, `u8` flags, `u32` vertices, `f32 xyz` x vertices, `u32` triangles, triangles x (`u16 v0 v1 v2, u16 uv0 uv1 uv2, u8 material`), `u32` uvs, `f32 uv` x uvs, then optionally `"TMAP" u8 u8` and a second `u16[3]` uv index a triangle (a lightmap set, unread) |
| 2 material | 0 | id, 28 bytes of colours and flags, `texture name\0` - 28-byte materials have no texture |
| 3 texture | 0 | the picture file: the GameCube form (`\0RPMOC3S` then **big-endian** `u32 width, height, bytes, GX format, 0, 0, 5, 1, 0`, `u16 7, u16 0`, tiled pixels with mips at +48) or a plain TGA |
| 4 node | 100 | id, parent id, mesh id, `u8 u8`, `f32 xyz` position, `f32 xyz` rotation (radians), `u32` materials, id x materials, `u32` colours, `argb` x colours (a vertex) |
| 8 name | 0 | id, `name\0` |

A texture chunk follows the material that samples it and is shared by texture name.  A
triangle's material byte indexes the **node's** material list (the Audi S3 body: fond, negru
crom, far spate, far fata).  The Audi body chunk is 84,513 bytes = 8 + 1 + 4 + 3,210 x 12 + 4
+ 3,444 x 13 + 4 + 150 x 8, exact; every mesh chunk on the six samples (472 on London 1) is
exact up to the optional `TMAP`.

The discs' standalone `.tga` (car skins `S1.tga`..`S7.tga`, menus) are the same GameCube
picture with the same 48-byte header - `plugins.kashmir` decodes those too.

## Placement

Meshes are referenced by nodes (once each on tracks; a few twice on cars), and nodes chain
through parents.  The rotation composes as `Rz(-z) Ry(-y) Rx(-x)`: under that reading 66 % of
London 1's 255 rotated pieces sit within 0.5 units of a neighbour against 48 % with the angles
un-negated (`scratchpad/kash/assemble.py`), and a top-down plot of the placed pieces is a
closed street circuit with a roundabout.  The angle *order* is the weak point - the pieces
are nearly all yaw-only, so the six orders score within 0.06 of each other.

## Results

| file | meshes | triangles | textures |
|---|---|---|---|
| City Racer `Cars/AudiS3/AudiS3.dat` | 15 (17 placed) | 4,976 | 7 |
| City Racer `Tracks/Lond1/Lond1.dat` | 472 | 67,244 | 138 |
| Taxi 3 `Tracks/Track_01/track_01.dat` | 246 | 111,191 | 186 |
| Speed Challenge `Tracks/Day/Australy.dat` | 167 | 45,998 | 69 |

Not read: the `TMAP` second uv set, the per-vertex colours on nodes, and the kinds 6 / 10 / 13
(splines, sound sources, property blocks - `GhostPoint`, `StartPoint00`, `WaveName`).
