# Piglet: the clump tail **is** GX display lists (2026-09-02)

`docs/OPEN.md` records Piglet's blocked geometry as "a **raw block inside the clump**: the
biggest clumps are 2.8 MB of which 2.85 MB is an unchunked tail after STRUCT, FRAMELIST and one
0x11010 plugin chunk, at entropy 7.37, opening on an image-like byte ramp, **with no GX display
lists in it**".

The last clause is wrong.

Taking the biggest CLUMP from the first 40 MB of `PIGGCN.pkd` - 2,232,166 bytes, whose chunk
walk covers STRUCT (12 bytes) and FRAMELIST (17,000) and then stops, leaving a **2,215,106-byte
unchunked tail** - and scanning it for a chained primitive opcode at each stride:

| stride | lists | opcode | vertices |
|---|---|---|---|
| **8** | **87** | `0x98` | **32,096** |
| 4 | 27 | `0x98` | 3,207 |
| 3 | 14 | `0x80` | 818 |
| 24 | 9 | `0x91` | 8,145 |

Stride 8 wins by a factor of three, and the first strip reads cleanly:

    98 01 59   0b 3e 0b 3e 0b 3e 0b 3e   0b 3f 0b 3f ...

`GX_DRAW_TRIANGLE_STRIP`, 0x0159 = 345 vertices, then 8-byte vertices of four big-endian `u16`
all holding 0x0b3e = 2878.  That is the same vertex shape as Free Radical's `gcr`
(see [free-radical-pck.md](free-radical-pck.md)) - an index per attribute, the first two equal
on 95% of vertices.

`gxscan` does not see these for the reason recorded there: its walk is greedy, and an accidental
chain earlier in the blob claims the span.

## Why the absence was recorded in the first place

The scan that produced "no GX display lists in it" was looking for the canonical opcodes at the
strides `gxscan` offers, through `gxscan` itself.  Both of those are the wrong instrument here,
and neither failure was evidence about the data.

**This is the third "not X" verdict in these notes to fall in one session** - the others being
"`Zdat` is not zlib" (it is; a block-level inflate cannot work because the stream spans chunks)
and "`gcr` is not GX display lists" (they are; 562 of them).  An absence measured with one tool
is a fact about the tool.

## What is still needed

The same thing `gcr` needs: **where the position array starts**.  This clump has no GEOMETRY
chunk at all - the walk finds only STRUCT and FRAMELIST - so RenderWare's declared `numVertices`
is not available here either, and the index columns of the 87 strips run to 65,472, which means
false-positive lists are still mixed in and the list set needs tightening before a count can be
trusted.
