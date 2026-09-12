# Ocarina of Time levels — scenes, rooms, mesh headers, collision, and the tables in `code`

*2026-09-11. Decoded by a 34-agent investigation, every claim then challenged by an independent
agent, and reproduced end to end by `n64rip/level.py` and `n64rip/collision.py` — 101 scenes
in six seconds, to the triangle. Every offset here was re-read from
`collectors_zle_f.n64` (the GameCube Collector's Edition disc's ROM, CRC f3dd35ba/4152e075).*

## What a level is

A **scene** file plus one or more **room** files. The scene holds what is shared — collision,
lighting, spawns, the doors between rooms, and most of the *palettes* — and each room holds
its own display lists and the actors standing in it. Both are a flat list of 8-byte header
commands ending in opcode `0x14`. There is one executor for both in `code`
(`Scene_ExecuteCommands`, VRAM `0x800812F0`): it tests `0x14` before dispatching and silently
skips any opcode ≥ `0x1A`.

Census, reproduced: **101 scenes (DMA 1006–1492), 388 rooms (1007–1494)**, a strict
partition — no room is shared between scenes. Rooms per scene: 62 scenes have one; the Water
Temple has 23, the Spirit Temple 29.

## Anchors in `code` (DMA file 27, VRAM base `0x80010EE0`)

Found **by structure, never by constant** — Master Quest moves every one of these by 0x20 and
Majora's Mask changes the scene-table stride to 0x10.

| table | how it is found | Ocarina |
|---|---|---|
| `gObjectTable` | `objects.find_object_table` (run of DMA pairs) | `0xE7618`, 402 slots |
| `gEntranceTable` | walk *backwards* from the scene table while `{s8 scene ≤ 110, s8 spawn ≤ 18}`, floor at the object table's end, then trim the **8 zero bytes** of padding (a zero record passes the test) | `0xE82B0`, 1,556 × 4 B |
| `gSceneTable` | the longest run of 0x14-byte records whose first two words are a live DMA pair and whose next two are a DMA pair or `{0,0}` | `0xE9B00`, 101 × 0x14 B |

`gSceneTable` record: `{scene vrom pair; title-card vrom pair; u8 unk; u8 drawConfig; u8 unk;
u8 zero}`. Entry 0 verbatim: `01 f0 10 00 01 f0 ea 10 01 98 30 00 01 98 4b 00 01 13 02 00` →
scene file 1006, title file 884, draw config 0x13.

**The entrance table is flat.** It is *not* 389 groups of four: the game stores entrance ids
0x53, 0x517 and 0x11E as immediates, which are 3, 3 and 2 mod 4. An entrance occupies its
record plus the next three (a 0..3 variant index), so consecutive entrances overlap. Scene
1006's exit list `{521, 1039}` resolves to (scene 85, spawn 1) and (scene 17, spawn 0) — the
two places the Deku Tree leads to.

## The header command language

`w0 = op<<24 | count<<16`, `w1` = a segmented pointer or an immediate. The count byte is a
real count for `0x00 0x01 0x04 0x0B 0x0E 0x0F`. Every scene-side pointer is **segment 2**,
every room-side pointer is **segment 3** — 1,898 room pointers, 0 exceptions — and that is
proven from the loader's own stores into `gSegments`, not inferred.

| op | side | meaning |
|---|---|---|
| `0x00` | scene | player spawns, `count` × 16-byte `ActorEntry` |
| `0x01` | room | actor list, `count` × 16-byte `ActorEntry` — **19 rooms have none** |
| `0x03` | scene | collision header |
| `0x04` | scene | room list, `count` × `{u32 vromStart, u32 vromEnd}` |
| `0x06` | scene | entrance list, uncounted `{u8 spawnIndex, u8 roomIndex}` — bound it by the next pointer target in the header |
| `0x07` | scene | shared keep: `w1` byte 3 is 2 (field keep) or 3 (dungeon keep), a clean dungeon/overworld partition |
| `0x0A` | room | **mesh header** |
| `0x0B` | room | object list, `count` × u16 object ids |
| `0x0E` | scene | transition actors (doors), `count` × 16 B |
| `0x0F` | scene | light settings, `count` × **22 B** |
| `0x11` | scene | skybox id / config / envLightMode, immediates |
| `0x13` | scene | exit list, uncounted u16 indices into `gEntranceTable` |
| `0x18` | both | alternate-header array — see below |

`ActorEntry`: `{u16 id; s16 pos[3]; s16 rot[3]; u16 params}`, stride pinned by the data
(stride 20 overruns the next structure in 333 rooms, stride 16 in 0). Room 1007's entry 0:
`00 95 01 1b 01 de 01 65 00 00 a3 8e 00 00 00 00` → id 0x95 at (283, 478, 357), rotY −23666.

Door (`0x0E`): `{s8 frontRoom; s8 frontCam; s8 backRoom; s8 backCam; u16 actorId; s16 pos[3];
s16 rotY; u16 params}`. The actor id takes exactly **three** values across all 638 records —
9, 35, 46 — the three door types. That is far stronger evidence for the field layout than any
range check.

Light setting (`0x0F`, 22 bytes): ambient RGB, light1 dir (s8×3) + RGB, light2 dir + RGB, fog
RGB, `u16` whose low 10 bits are fogNear (0..999, never ≥ 1000), `s16` zFar. The stride is
settled by entropy — 31 distinct last-u16 values at stride 22 against 315–336 at every
neighbour — and the offsets by 2,229 of 2,940 direction triples having integer magnitude
exactly 126 or 127. A widely-copied 21-byte transcription of scene 1006's row drops the `00`
at +3 and shifts every colour by a byte.

### Alternate headers — the trap

`0x18` points at an array of header pointers whose length is stored nowhere and which is
**NULL-sparse**: for 27 of the 32 scenes carrying it, slots 0–2 are zero and the first real
pointer is slot 3. A walk that stops at the first non-pointer sees *zero* alternates for those
scenes and reports "no differences" from an empty loop. Skip NULLs, stop on the first word
that is neither NULL nor a header.

And what alternates change: actors (197 of 251 room alternates carry their own), objects,
time, lighting (117 of 134 scene alternates differ) — and **never geometry**. 0 of 134 scene
and 0 of 251 room alternates name a different room list or mesh header. So 388 rooms and
164,228 triangles is the complete set, and the geometry exporter ignores `0x18`.

## Mesh header (room `0x0A`)

Common head, **note the padding**:

```
+0  u8  type      0 flat, 1 prerendered background, 2 culled
+1  u8  count     (type 1: the background FORMAT, 1 or 2 - not a count)
+2  u16 pad       0 in all 360 type-0/2 rooms
+4  u32 start     pointers are at +4 and +8, NOT +2 and +6
+8  u32 end
```

* **Type 0** (157 rooms): entries of 8 bytes `{opa, xlu}`; `end − start == count × 8`, 157/157.
* **Type 2** (203 rooms): entries of 16 bytes `{s16 centre[3]; u16 radius; opa; xlu}` —
  `end − start == count × 16`, 203/203. The sphere is real: every decoded vertex lies inside
  it for all 1,595 entries that draw, and it is a **Chebyshev** fit — `max|v − c|` per axis
  equals the radius exactly; a Euclidean assert fires on 99% of entries.
* **Type 1** (28 rooms): the word at +4 is **one indirection away** — it points at a single
  `{opa, xlu}` record, not at a display list. Read it as a list and you execute a `G_CULLDL`
  on the entry array and walk into the JPEG: 146,759 triangles instead of 164,228 and
  fabricated references to segments 0xFF and 0x65. Format 1 (23 rooms) has an inline
  `BgImage` at +8; format 2 (5 rooms — 1338, 1348, 1438, 1442, 1444) has a `u8 count` at +8 and
  a pointer at +12 to 0x1C-byte records. The images are **baseline JFIF JPEG**, 35 of them,
  320×240, 604,785 bytes stored; `fmt 0 / siz 2` describes the RSP's destination buffer, and
  decoding them as RGBA16 texels gives 35 noise images.

Exactly one room draws nothing — file 1350 (scene 71), a bare `G_ENDDL` — and scene 71 is
degenerate throughout (4 collision vertices, 2 polygons). It is not a bug.

## Segments — the recipe

```python
Segments({2: scene_bytes, 3: room_bytes, 4: gameplay_keep, 5: field_or_dungeon_keep})
```

Triangle counts are identical with or without the scene bound — which is exactly why a
count-only check misses it. **8,940 of 9,504 TLUT references (94%) live on segment 2**:
without the scene, nearly every colour-index texture in every room is unpalettable. Only 29
materials in the whole game ask for texels the cartridge does not hold (segment 8: 25,
segment 9: 3, segment 6: 1).

Segments 8–0xD: 356 `G_DL` calls point into them and every one is a **tile-state list the
frame builds at draw time** from the scene's draw config — TileSync / SetTileSize /
SetEnvColor / EndDL and nothing else. The bytes exist nowhere in the ROM. Skipping them costs
exactly 0 triangles. The only absolute RAM address any room list uses is `0x800FE2A0`,
`code+0xED3C0`, and the 64 bytes there are the identity matrix.

**Two-cycle mode cannot be read from a room's display list.** No room list ever sets the
cycle type; the only `G_SETOTHERMODE_H` writes are TEXTLUT. It comes from `code`'s 71-entry
setup-DL table. The usable measure is the combiner, which
[[oot-color-combiner-2026-09-11]] decodes.

## Reassembly: rooms need no transform

A room's vertices are already in the scene's world space. Three oracles in the *scene* file —
a different compressed file from the rooms — say so: 768 of 778 door placements lie inside the
room geometry they name; 330 of 334 door-joined room pairs touch or overlap, 128 on a boundary
plane exact to the unit; and the collision box matches the decoded room extent on five of six
bounds for scene 1006 and all six for 53 of 100 scenes. A deliberate 50-unit per-room shift
breaks 708 of 1,595 cull spheres. (The cull sphere alone does *not* prove this — it lives in
the room file and agrees under either hypothesis.)

So a level is concatenation plus placement. The exporter writes **one glTF per scene with a
node per room**, the collision on its own node, and every actor, spawn and door as a named
empty carrying its id, params and raw binary angles.

### The one geometry defect: the unresolved `G_MTX`

Seven rooms (files 1040, 1046–1050 in Jabu-Jabu, 1359) run a triple per placed object:
`LOAD <placement matrix in segment 3>`, `MUL 0x0D000000`, `LOAD 0x800FE2A0`. The last two are
unresolvable from the cartridge, and an interpreter that returns early on an unresolvable
load leaves the placement in force for everything drawn afterwards — 2,176 triangles under a
stale matrix, and scene 2's rooms reaching Y 2257 against a collision ceiling of 607. The fix
is that an unresolvable **LOAD** resets the matrix to identity. After it, every scene's rooms
sit inside their declared collision box to within 100 units.

## Collision (scene `0x03`)

```
struct CollisionHeader {          // 0x2C
    s16 min[3], max[3];
    u16 numVertices; u16 pad;  u32 vtxList;
    u16 numPolygons; u16 pad;  u32 polyList;
    u32 surfaceTypeList;  u32 camDataList;
    s16 numWaterBoxes; u16 pad;  u32 waterBoxes;   // NULL in the 74 scenes with no water
};
```

Layout is strictly ordered and contiguous, 101/101: `camData < surfaceType < poly < vtx`,
and `polyList + n×16 == vtxList` exactly. That adjacency is what **defines** the surface-type
count, which is stored nowhere — `max(poly.type)+1` is only a lower bound. The list's *span*
is a multiple of 8; its *offset* is only 4-aligned (scene 1006 puts it at 0x314).

Polygon, stride 16: `{u16 type; u16 vA; u16 vB; u16 vC; s16 normal[3]; s16 dist}` with the
vertex index in the **low 13 bits** (flags above). Over all 87,215 polygons: 0 out-of-range
indices, 0 degenerates, every normal within 3 of 0x7FFF, plane residual < 0.7, and
**winding agrees with the stored normal on 87,215 of 87,215** — nothing needs flipping. The
header's declared box always contains the vertices but equals their extent in only 32 of 101
scenes; use the decoded extent.

`camDataList` entries are `{u16 setting; s16 numVec3s; u32 ptr}` with count 0, 3 or 6. The
Vec3s block's meaning is **per setting**: setting 0x1E is the only one with count 6, and its
block is a six-point polyline, not two cameras. Carry it raw.

The same struct, minus water boxes, appears inside object files — the dyna-poly meshes for
doors, drawbridges and platforms; ~201 headers in 74 files. `collision.find_headers` finds
them by the strict parse.

## Names

65 of the 101 scenes carry a title card — `gSceneTable`'s second column, 144×48 IA8, the
Japanese line over the English. All 65 were rendered and transcribed: Inside the Deku Tree,
Dodongo's Cavern, Hyrule Field, Kakariko Village, Lon Lon Ranch, Ganon's Castle… Several
places share one (three Markets, three Potion Shops, three Castle Courtyards), so the scene
index stays in the published name. The 36 without a card — boss arenas, cutscene stages,
houses — keep their index. Scene 91 (Lost Woods) is title file **914**; 921 is Ganon's Castle.

## The props — geometry that hangs on no skeleton

230 of the 380 object files have no skeleton and 8 more (503, 517, 531, 537, 561, 581, 639,
689) return one whose limb pointers are raw small integers, so the skeleton route exports
nothing for them — and 161 of the 282 object ids that rooms request are among them: chests,
doors, signs, pots, tents, the drawbridge. `n64rip/static.py` finds them with a **gate**, not
a guess:

* candidates: every stored `0x06XXXXXX` word on an 8-byte boundary that is not a command
  operand (the second word of `G_DL`/`G_VTX`/`G_SETTIMG`/`G_MTX` is a pointer too, and a `G_DL`
  operand is precisely the interior case), plus every start `scan.display_lists` accepts. Never
  a bare "offset 0" or "after every `G_ENDDL`": a run of zero words is a run of `G_NOOP`s and
  the interpreter walks it into the next real list and claims its geometry — a fixture caught
  this fabricating a root out of vertex data.
* the gate: the list draws, and **every vertex load resolved from the file's own segment**.
  Over all 2,368 limb lists in the ROM that is literally `{6: everything}`; on random starts
  in non-exporting files only 8.7% pass. Textures on runtime segments are *not* a reason to
  reject — that rule alone hid a third of the geometry (file 767's slab, file 503).
* roots: a list another kept list calls is interior, unless a table (not an operand) names it.
* the keep banks live on segments **4** (`gameplay_keep`, object 1) and **5** (field and dungeon
  keeps); bound at 6 they yield nothing. File 497 at segment 4 gives 68 roots / 1,093
  triangles; the investigation's two pipelines gave 72 / 1,106 and a band of 18,000–28,500
  for the whole set. This gate lands inside it.

Each root is its own node (`dl_XXXXXX`) in the object's own space, so a chest and its lid come
out as two objects. What the route cannot do: a root made only of `G_DL` calls draws nothing
itself, so the scan never proposes it; if no table names it, its callees are exported
individually and the grouping is lost, not the geometry.

## Animations as clips

Every `AnimationHeader` in an object file is now a glTF clip on that file's rig(s): frame *f*
gives `(root translation, per-limb ZYX rotations)` through the same `frame_values` that
produces the rest pose, joint 0's translation is the animation's root translation (the same
substitution `pose_matrices` makes, so a walk cycle walks), and rotations become quaternions
via the same `rotation_matrix`. 20 fps. Checked in Blender: the Zora imports with 22 actions
and its bones move between frames.

Two honest limits. A file with several rigs gets every clip on each rig — which animation
drives which rig is in the actor's code, not the file. And **Link's clips are not shipped**:
`link_animetion` (DMA file 7, 2.5 MB, 18,760 frames of 134 bytes) is a bare run of frames, and
the table in `code` that says where each animation starts has not been decoded — the one
contiguous run of segment-7 records (1,391 at `code+0xFD0EC`) has a first halfword that counts
up by one per record and segment offsets eight bytes apart, an index of something else. Cutting
clips at guessed boundaries would be the rest-pose mistake again. Open.

`anim.plausible` gates a header before it becomes a clip: the joint-index block must lie in the
file and every animated track must have *frames* shorts of room — the check `read_animation`
lacks, which let a run of limb pointers pose object 393 into a lump.

## What is still open

* Which of a scene's 4–26 light settings is active in fixed-light mode — chosen at runtime
  by actor code; the export picks index 0 and says so.
* The fog arithmetic (`blendRate` in the upper bits of the fogNear word, and how `(fogNear,
  zFar)` become the `G_FOG` multiplier) — in `Gfx_SetupDL` in `code`, undecoded.
* The 1,211 triangles in 7 rooms that no header names, reachable only by a blind scan.
* The actor rotation convention. Placements are exported as YXZ from the game's
  translate-rotate call; most actors rotate about Y alone so it rarely matters, and the raw
  angles are carried for whoever settles it.
* Whether room mesh entries inherit texture state across entry boundaries the way Volvagia's
  limbs do. 381 batches come out untextured with a fresh interpreter per list.

## Related

- [[oot-color-combiner-2026-09-11]] — the combiner, the alpha rule, texgen
- [[oot-npc-faces-2026-09-11]], [[oot-rest-pose-2026-09-11]], [[oot-code-route-2026-09-11]]
