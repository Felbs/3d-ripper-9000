# Zelda 64 faces: the eye and mouth textures an actor swaps at runtime

*Ocarina of Time (and Majora's Mask, same engine). Implemented in `n64rip/face.py`,
`n64rip/actor_code.py`, `n64rip/objects.py`, `n64rip/extract.py`.*

A Zelda character's face is not painted into its model. The head's display list samples
segments 8 and 9, and the game points those at one of several textures each frame. A static
rip therefore leaves the face blank - which is why "the NPCs have no eyes" is a **texture**
problem, not a geometry one.

This note records how those textures are located, and - more usefully - the three wrong
answers that looked right first.

## Where the tables live

Link keeps his expression table in `code`, as an evenly spaced array of segment-6 pointers.
A stride walk finds it (`face.find_faces`), and that is the whole of the Link path.

**Almost no NPC is like that.** Of 53 face-wanting models the stride walk found 2. Each NPC
keeps its own table in **its actor overlay**, and the way in is:

* `gActorOverlayTable` in `code` - eight words an entry, the first two a real DMA range and
  the next two VRAM addresses, which is specific enough to locate the table by structure
  alone (`objects.find_actor_overlays`). Each entry's `initInfo` points at an `ActorInit`
  whose object id sits at +8.
* **Several actors share one object**, and only one of them may be the one that draws the
  face, so every actor for an object has to be kept - not the first. Keeping only the first
  cost 204 objects most of their overlays.
* Inside the overlay, the table reads directly as raw `0x06XXXXXX` words, because **segmented
  pointers are never relocated**. They are absolute segment addresses, not overlay-internal
  ones, so the loader leaves them alone. No disassembly and no relocation table needed.

A capstone pass that reconstructed `lui`/`addiu` pairs was written first and reached 7 of 53.
The raw word scan reaches 35. The disassembler is kept (`actor_code.segmented_pointers`)
but is not the route.

## Reading a table once you have it

A run of pointers is not yet a table of eyes. Three things have to be settled, and each has
a source that is reliable and several that are not.

| Question | Read it from | Do **not** read it from |
| --- | --- | --- |
| pixel format | the display list (`SETTILE` states it outright) | the pointer table |
| texture size | the table's spacing, or the display list, whichever scores better | the display list alone |
| where eyes end and mouths begin | the change in spacing, or the drop in frame similarity | position in the run |

**Size is the trap.** The display list's tile dimensions are derived from how many texels
were actually loaded - and for exactly the actors whose face is missing, nothing was ever
loaded on that segment, so the dimensions are stale. The pointer table measures it
independently: entries of one table are spaced by exactly one texture, so the spacing *is*
the size. Neither source is right on its own (some tables are not packed and have no
constant spacing at all), so both are offered as candidates and scored.

A spacing gives a texel count, not a shape. The squarest split with `w >= h` picks the right
shape on every actor checked: 1024 texels is 32x32, not 64x16; 2048 is 64x32.

**Format matters more than it looks.** Not every face is CI8 - the Great Fairy's eyes and
Ruto's are RGBA16. Decoding 16-bit pixels as 8-bit indices halves the width and turns a face
into vertical lace. That single mistake accounted for most of the "glitchy" NPCs.

## Scoring a candidate: what actually discriminates

The frames of an eye set are *the same drawing with the lid moved*, so they share most of
their **bytes**. Unrelated data shares about one byte in 256. That gap is far wider than
anything measurable after decoding, and it is the only measure that works on colour-indexed
art - Pearson correlation over palette *indices* is close to meaningless, because
neighbouring indices are not neighbouring colours.

True-colour faces are re-shaded rather than copied, so they can share few exact bytes while
plainly being the same picture; correlation over decoded pixels carries those. The score is
the better of the two.

Two guards sit on top:

* **flat or identical frames are rejected** - one repeated byte is padding, and identical
  frames are one pointer listed twice.
* **a roughness gate** (mean difference between neighbouring texels). Drawn art is locally
  smooth; bytes that are not a picture measure near 0.33, where uniform random bytes land.
  Used only to reject, and only well above anything a real texture reaches, because a face
  decoded out of unrelated bytes is worse than an honestly blank one.

Selection is by **length first** among candidates that clear the threshold. Scoring alone
picks the shortest table every time - the score is an average over consecutive pairs, and a
two-entry candidate has only its single best pair to average. That reduced a
nine-expression face to two.

## Three wrong answers

1. **"Search `code` for the table."** `face.find_faces` returns the longest run in whatever
   buffer it is given, so searching `code` returns *Link's* table for every actor. One
   distinct table was measured across objects 20, 21, 10, 29, 51, 53, 75, 78, 91, 96, 135,
   136 - Link's, bound into eleven other characters' object files, decoding unrelated bytes
   as a face. `face.owns_table` exists to reject this.

2. **"Pick the candidate with the most pixel variance."** Exactly backwards: noise has more
   variance than any real image, so maximising it selects garbage every time. This put
   scrambled bytes on nineteen faces and they all scored as successes.

3. **"A face binding is free."** It is not - rebuilding with segments 8 and 9 bound makes
   display lists that call through them execute face-texture bytes as a display list. Before
   the gate that requires the rebuild to keep the same triangle count and lose no textures,
   this injected **95,023 junk triangles**, about 65% of everything the rip shipped;
   `file_0644` came out 38,363 triangles of which 491 were real.

## Verifying

Counting does not work here. `quality.py` scored all 168 N64 models "0 garbage / 0 suspect"
both before and after real bugs, and the nineteen scrambled faces above passed every numeric
check. The only test that settled any of this was rendering the candidate textures to a
contact sheet and looking at them.

## The object table was truncated, and that was most of the problem

The biggest single cause of missing faces turned out not to be the face code at all.

`find_object_table` walks a run of `{vromStart, vromEnd}` pairs, accepting a slot when it
names a real DMA file or is `{0, 0}`. Ocarina's slot 227 is `{0x015e2000, 0x015e2000}` - a
range of **zero length**. The DMA table never yields a zero-length file, so that pair can
never match a real one, and the walk treated it as the end of the table.

It stopped at object 227 of 402, hiding 175 objects. Those objects had no id, so
`find_actor_overlays` could not attribute an overlay to them, so their face tables were
unreachable - not because the mechanism was wrong, but because the actor was invisible.
**King Zora is object 255.** With an id, the existing algorithm finds his eyes on the first
attempt: overlay `file_0353`, offsets `0x1470 / 0x1870 / 0x1C70`, CI8 32x32, and they render
as a purple iris on pale blue Zora skin - open, half-lidded, closed.

Accepting a zero-length range as a blank slot: 227 -> 402 object slots, 211 -> 380 object
files, and **22 -> 40 characters with expression sets**, with no change to the first 227
entries and nothing lost.

## Reading the binding out of the code

Everything above reads *data* and guesses what the game does with it. The game does not
store "this texture goes on segment 8" anywhere - the actor's Draw function computes it every
frame:

    gSPSegment(gfx, 0x08, SEGMENTED_TO_VIRTUAL(sEyeTextures[this->eyeIndex]));

An emulator gets that for free by running the code. `actor_code.gsp_segments` reads it
instead. The macro compiles to a fixed shape: the command word is built by `lui r, 0xdb06`
and `ori r, r, seg*4` and stored at `0(gfx)`; the address is stored at `4(gfx)`. Find a
store of a register holding `0xDB06xxxx`, take the store to `+4` of the same base register,
and work out where *that* register's value came from - which is the whole method, plus three
things the first attempt got wrong:

* **The address is derived, not built.** `SEGMENTED_TO_VIRTUAL` masks the offset with `and`
  and adds the segment base with two `addu`. A tracker that drops the value at the `and`
  finds nothing in any actor. The segmented source has to be *carried through* arithmetic.
* **Pair the two stores, not the nearest address.** With two calls interleaved by the
  compiler, the `+4` store nearest by distance belongs to the previous call, and every
  pointer lands one segment late. The mate is the nearest `+4` store that *follows*.
* **The pointer may come through the actor's own struct.** Child Zelda's Update copies
  `sEyeTextures[index]` into `this->eyeTexture`; her Draw binds `this->eyeTexture` and never
  builds the table address at all. That needs a second hop: stores into the same field offset
  whose value traced to a table.

Two sources of address occur. A **direct** binding builds the segmented constant itself -
Tektite does this once per colour variant, and no data scan can find it because the offsets
never appear as `0x06XXXXXX` words. A **table** binding loads it from an array whose VRAM
address the code builds; the overlay is linked for its home address, so the table's offset
in the file is that address minus `vramStart` from `gActorOverlayTable`.

Tried before the data route, per role. It is exact where a run found by shape may be two
tables end to end: object 188's run of ten is the code's two tables of five, and object 10's
segment `0x0A` mouth is a two-entry subtable the shape scan could only ever see as the tail
of the eyes.

### Attributing an object nobody claims

Some actors name `gameplay_keep` in their `ActorInit` and pick their real object at runtime.
The second child Zelda and one of the Deku Scrubs are drawn by such actors, so no entry in
the actor table leads to them and every data route is blind. Their *code* is not: the object
is offered to every runtime-object actor through `gsp_segments` alone, and a candidate is
kept only when it names at least two offsets that fit the object and decode, at the format
the head requests and through the head's own palette, as something that passes the ordinary
picture gates. Of four candidates for Zelda one passed, and it was her. The pool is never
searched by pointer shape - that would be a search over a hundred and thirty overlays, and
the rest of this note says what that produces.

## Hair, hats, held items: display lists the actor draws on a limb

The Gerudo's ponytail is not in her limb table. Nothing in the skeleton references it, every
texture on the model resolves, and she is bald. The actor draws it from its post-limb
callback:

    addiu $at, $zero, 0xf      ; limbIndex == 15 (1-based: the head)
    bne   $a1, $at, skip
    lui   $t7, 0xde00          ; gSPDisplayList
    sw    $t7, 0(gfx)
    lbu   $t8, 0x29e($a3)      ; this->hairType
    lui   $t0, 0x80a2
    sll   $t9, $t8, 2
    addu  $t0, $t0, $t9
    lw    $t0, -0x4b34($t0)    ; hairTable[hairType]
    sw    $t0, 4(gfx)

with the head's matrix on the stack - so the list's vertices are in head space and the hair
moves with the head. `actor_code.attachments` reads exactly this: the same two-store anchor
as `gsp_segments`, plus the nearest preceding `addiu $at, $zero, N` consumed by a branch on
`$a1` (the callback's `limbIndex`). A list with no such guard is drawn under the actor's own
matrix, whose pose is not known statically, and is left alone rather than placed at the
wrong joint. `zobj.build` runs each attached list under its limb's world matrix, exactly as
the game does, so it is posed and skinned with the limb.

Two details that cost a round each:

* The table's low half is folded into the load's displacement - `lui 0x80a2` then
  `lw -0x4b34($t0)` - so the base register points *outside* the overlay while the load
  lands inside it. Judging "is this a table read" on the base register finds nothing; it
  has to be the effective address. The same gap was latent in `gsp_segments`.
* The attachments have to be threaded through *every* rebuild - the pose, the face binding,
  each expression variant - because the face-binding gate compares triangle counts before
  and after, and a rebuild without the hair would be rejected as having lost geometry.

Eight actors in Ocarina of Time carry attachments this way. The Gerudo's table has three
lists (hairstyles, chosen by an actor field); the first is what she draws by default.

## A face belongs to a head

Three of the newly-reachable objects were not characters: a glow sprite, a ring and a small
flame, each of which samples segment 8 and so looked like an actor asking for a face. They
shipped a black donut and two coloured blobs as "eyes".

They are separable structurally rather than statistically. A real face tile covers between
4.7% and 48.9% of the limb that draws it, because a head also carries skin, hair and ears.
All three of these sit at exactly 100% on limbs of two to six triangles: the tile *is* the
limb. A face request is therefore only counted when the limb carries geometry beyond the
swapped tile itself.

## Result

Ocarina of Time, 167 models: 40 actors carry expression sets, face textures written
beside the models as `face_eye_N.png` / `face_mouth_N.png`, `textures_missing` down from 169 to 123, triangle count unchanged. Expressions beyond the first are also attached to the glTF
as variant primitives, which the Blender add-on turns into one keyframeable integer per face
part - a shape key cannot do this job, because nothing about the geometry changes between
expressions.
