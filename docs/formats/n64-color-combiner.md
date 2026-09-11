# The N64 colour combiner, read correctly — Ocarina of Time

*2026-09-11. Established by decoding `G_SETCOMBINE` words out of the retail ROM and checking
every conclusion against a render. The control is adult Link, and it is a good one.*

## Why this matters more than it sounds

`G_SETCOMBINE` is one command with two words, and it decides three separate things the ripper
depends on:

1. **whether a material is OPAQUE, MASK or BLEND** — via whether the *alpha* equation samples a
   texel at all,
2. **what colour tints the texture** — PRIMITIVE or ENVIRONMENT, and they are different
   registers set by different code,
3. **whether a second tile is being sampled** — the two-cycle detail texture.

Get the bit positions wrong and all three are wrong everywhere, quietly. This package had four
of the eight alpha selects coming out of the wrong word at shifts that overlap the command byte
and the RGB `c1` field. Nothing crashed; materials were just silently misclassified across the
whole rip.

## The packing

gbi.h assembles the sixteen multiplexer selects across the two words with **no regular stride**,
and — the part that is easy to get wrong — the alpha halves of cycle 1 live in **w1**, not w0.

| field | word | shift | width |   | field | word | shift | width |
|-------|------|-------|-------|---|-------|------|-------|-------|
| `a0`  | w0   | 20    | 4     |   | `Aa0` | w0   | 12    | 3     |
| `b0`  | w1   | 28    | 4     |   | `Ab0` | w1   | 12    | 3     |
| `c0`  | w0   | 15    | 5     |   | `Ac0` | w0   | 9     | 3     |
| `d0`  | w1   | 15    | 3     |   | `Ad0` | w1   | 9     | 3     |
| `a1`  | w0   | 5     | 4     |   | `Aa1` | w1   | 21    | 3     |
| `b1`  | w1   | 24    | 4     |   | `Ab1` | w1   | 3     | 3     |
| `c1`  | w0   | 0     | 5     |   | `Ac1` | w1   | 18    | 3     |
| `d1`  | w1   | 6     | 3     |   | `Ad1` | w1   | 0     | 3     |

Source codes, 0–5, shared by the RGB `a`/`b`/`d` muxes and the whole alpha mux:
`0 COMBINED, 1 TEXEL0, 2 TEXEL1, 3 PRIMITIVE, 4 SHADE, 5 ENVIRONMENT`.
The RGB `c` mux is five bits and continues past 5:
`6 SCALE, 7 COMBINED_A, 8 TEXEL0_A, 9 TEXEL1_A, 10 PRIM_A, 11 SHADE_A, 12 ENV_A,
13 LOD_FRACTION, 14 PRIM_LOD_FRAC, 15 K5`.

## The control that pins it

Adult Link (object 20) is drawn by exactly two combiners, and **they differ in one field**:

```
0xfc127e60  ->  389 triangles: skin, boots, gauntlets, sword, shield
0xfc127ea0  ->  206 triangles: the tunic and cap
```

`0x...60` and `0x...a0` differ only in bits 5–8 of w0. Read at `a1 = (w0 >> 5) & 0xF` those are
**3 = PRIMITIVE** and **5 = ENVIRONMENT**. That is a meaningful difference: it is the split
between a constant the object's own display list sets and one the actor sets at draw time, and
it falls exactly on the tunic — the piece whose colour is not in its texture.

Any other reading of that field makes these two words differ in something that is not a colour
source, which is the test. It is recorded as `test_the_combiner_field_layout_is_pinned_by_adult_link`.

## What it changed, measured

Over the 167-model rip, with only the decode corrected:

- **27 of 167 models** changed alpha profile. MASK 150 → 171, OPAQUE 2023 → 2015.
- Of the 15 materials that became MASK, **14 have textures that are 47–62% transparent
  texels** — genuine cut-outs that were being exported solid.
- Of the 2 that went the other way, both are Iron Knuckle's axe, which is solid steel; its
  render went from mottled speckle to clean metal.

That ratio is the evidence the new reading is right. A wrong decode does not preferentially
pick out the textures that are full of holes.

## The trap: an unwritten register is not white

The obvious next step — "tint from the register the combiner names" — is **wrong on its own**,
and measuring caught it.

Link's combiner names ENVIRONMENT, but **his object file contains no `G_SETENVCOLOR` at all**.
The actor writes it at draw time. Reading env literally returns the default white and throws
away the Kokiri tunic constant `(30, 105, 27)` that the object list parked in PRIMITIVE. In the
real rip that emptied all eight of his tinted materials: green in, white out, a strictly worse
result than the naive `base_color = prim` it replaced.

So the rule is:

```python
# the register the combiner names, falling back to whichever the object actually WROTE
order = ("env", "prim") if named == "env" else ("prim", "env")
```

and only when neither was written is the batch genuinely untinted. This is a general shape and
not a Zelda quirk: **a register no display list in the file writes carries no information, and
must not be read as its reset value.** Track "was this written" alongside every RDP register
whose default is a legal value.

## Two-cycle detail textures

1,051 triangles over 11 models sample TEXEL1. The second tile is real art, not a mip level —
Volvagia's are a bright orange flame sheet and a dark red molten-rock sheet, both coherent
32×32 RGBA16 of the same size. glTF's metallic-roughness model has nowhere to put a second
diffuse tile, so it rides along as an extra image plus `extras.gcrip_detail_texture`.

**Do not bake a blend weight.** It is `ENV_ALPHA` on 843 of those triangles and
`PRIM_LOD_FRAC` on 208, never `LOD_FRACTION` — and where the object list sets neither, the
actor supplies it. Record the register by name and leave the weight to whoever disassembles
the overlay. A 50/50 blend renders convincingly and is derived from nothing, which is the
failure mode this project keeps having to undo.

Also: **do not look for `G_CYC_2CYCLE` in object display lists.** No display list in this ROM
ever sets the cycle-type field; all 4,421 `G_SETOTHERMODE_H` commands in object files are
`gsDPSetTextureLUT`. The cycle type comes from `code`'s own setup lists. The usable measure is
the combiner.

## Texgen: the vertex UVs are dead bytes

Unrelated to the combiner but found in the same pass, and the same class of mistake — reading a
field the hardware overwrites.

With `G_TEXTURE_GEN` (0x00040000) set, the RSP **overwrites** each vertex's s/t from the vertex
normal, so the s/t bytes sitting in the file are dead and reading them gives an arbitrary slice
of the tile. All 1,449 texgen triangles in this ROM also set `G_TEXTURE_GEN_LINEAR`
(0x00080000), whose map is:

```
s = acos(-n.x) / pi * 32
t = acos(-n.y) / pi * 32
```

Two things that are easy to get wrong and were both caught by rendering:

- it is **not** the sphere map `(n * 0.5 + 0.5)`. The sphere map erases dark Link's blade
  entirely, and 473 of his 475 triangles are texgen, so he is the model that decides it.
- the coordinate spans a **fixed 1024 in S10.5 = 32 texels regardless of tile size**, so it must
  not be scaled by tile width or height; 320 of these triangles are on 32×64 tiles and scaling
  shears them.

The normal is taken in the limb's world space (`mtx[:3,:3] @ n`), and the lookat is the default
axis pair because a static rip has no camera. That last part is a judgement standing in for the
in-game reflection orientation, not a derivation, and the code says so.

## Related

- [[oot-npc-faces-2026-09-11]] — the expression tables and the tile-gap oracle
- [[oot-rest-pose-2026-09-11]] — why animation selection is attested rather than scored
- [[oot-code-route-2026-09-11]] — reading actor overlays for what the model does not say
