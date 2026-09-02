# Alien Hominid - no 3D on the disc (2026-09-01)

Cluster 3 listed it under `.pak` "pack" archives.  Its 45 `.pak` are **ZIP files** - they open
`PK\x03\x04` and `gcrip/plugins/zip.py` already expands them, which is why the manifest shows
1,948 `.brec` members and no one had to write anything.

What those members are, counted over 12 archives:

| magic | count | what |
|---|---|---|
| `RSND` | 560 | sound |
| `SWF6` | 9 | **Flash** - one per level, up to 4.5 MB |
| `PIXL` | 3 | bitmap |
| `GLYP` | 1 | font |

Alien Hominid began life as a Flash game and the GameCube port carries the Flash content
across: a level is one `SWF6` blob whose art is **vector shapes**, not meshes.  There is no
geometry on this disc to rip, and no reader would find any.

Same conclusion as Mega Man X Collection in the same cluster, for the same kind of reason - the
game is not 3D - though by a different route: that one is emulated 2D sprites, this one is
vector Flash.

The only thing here a texture pass could take is the handful of `PIXL` bitmaps, about eleven
across the disc.  Recorded rather than done: a plugin for eleven images on one disc is not worth
the surface area, and anyone who disagrees now knows exactly what they would be writing it for.
