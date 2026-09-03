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


## The display lists read cleanly once the vertex-count cap is right

The 87-strip scan above used a 2,048-vertex cap and let false positives in - its index columns
ran to 65,472.  The real lists are bigger.  Walking from the first genuine opcode, at tail
offset **77**:

    98 10 2b   00 b1 00 b1 00 b1 00 b1   00 b2 00 b2 00 b2 00 b2 ...

`0x102b` = **4,139 vertices**, then a second strip of 345 - **4,484 vertices, 3,922 triangles**,
and now every column agrees:

| column | max | distinct |
|---|---|---|
| 0-3 | 3,123 | 3,096 |

All four index columns hold the **same** value on every vertex, so the attributes are
interleaved and one index addresses them all - the same arrangement Acclaim's `.GDF` uses.  So
this group has **3,124 vertices**.

## The position array: found the trap, not the array

Sweeping the 2.2 MB tail for a big-endian `s16` array of 3,124 triples and scoring it by
triangle locality gives a best of **0.0077** - a score that would be conclusive on a real mesh.
It is an **index array**.  Its vertices read `(476,476,478)`, `(478,478,478)`, `(464,464,464)`:
a run of one repeated `u16`.

That is a general trap and it is now in `gcrip/oracles.py` as discredited.  **Consecutive
indices are numerically close, so an index buffer read as xyz has tiny triangles inside a wide
box** - exactly what the oracle rewards - and it beats the real positions.  It is very likely
what made the same search flat on Free Radical's `gcr`.

The repair is to require a vertex's three components to differ, since index data has them
nearly equal.  A *mean* over the array is not enough: with that filter in place the top hit was
still `(331,331,331)`, `(719,719,719)`, because triples straddling a boundary lift the average.
It has to be the **fraction** of vertices whose components agree, and that is where this stands.


## The layout, on the first group, with two independent identities (2026-09-02)

Walking `0x98` strips from tail offset 77 with stride 8, skipping up to 64 bytes of zero
padding between them, gives **4 strips, 4,688 vertices, 4,054 triangles**, and:

* all four index columns hold the **same** value on 100% of vertices - one index addresses every
  attribute, as in Acclaim's `.GDF`;
* the indices are **exactly 0..3,251**: 3,252 distinct values with a maximum of 3,251.  That is
  the containment identity, and it both fixes the vertex count and gives a test for whether a
  candidate strip run is real.

The arrays then follow the lists:

| | offset in the tail | bytes | evidence |
|---|---|---|---|
| display lists | 77 .. 37,624 | 37,547 | GX opcodes, indices exactly 0..N-1 |
| **positions**, `f32` x 3 BE | **37,645** .. 76,669 | 39,024 | triangle locality **0.0241**, bounding box (-24.67, -1.03, -1.43) .. (0.95, 6.09, 1.44) |
| (16 bytes unread) | 76,669 .. 76,685 | 16 | |
| **normals**, `f32` x 3 BE | **76,685** .. 115,709 | 39,024 | **unit length, worst `|n| - 1` = 4.15e-08** |

The normals are the strong one: 3,252 consecutive `f32` triples of length 1.0 to eight decimal
places is not something a wrong offset produces.  And 115,709 opens `c1 88 3f d3 be fa c4 26`
= (-17.03, -0.4898, -13.66), so the next group's positions start there.

Positions at `normals - N * 12` = 37,661 give **garbage** (-7e+26), so the two arrays are not
adjacent; the sixteen bytes between them are unread.

### What is left

The group boundary.  Scanning forward from 115,709 for the next strip run finds a false one at
130,440 claiming 65,536 vertices with only 7,703 distinct - which the containment identity
rejects, so the test to reject it exists, but the rule that *finds* the next group's lists does
not yet.  Until that is settled a reader would work on the first group of a clump and guess at
the rest, and guessing here produces a plausible wrong mesh rather than an error.
