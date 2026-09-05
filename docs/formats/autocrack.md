# autocrack - the standard hypothesis battery for unknown member bytes

`gcrip/autocrack.py` (2026-09-04).  A **reporting** tool, not a shipper: given an unknown
member's bytes it runs every standard hypothesis test from the night eight formats fell
(Skye SKX/skg, Acclaim SKN, VC SCNE, Gun .mpk, TR Legend DRM...) and emits a structured
report of which fired, with evidence and parameters - so a session starts a format crack at
step 5 instead of step 0.  It ships no reader: a fired probe is a lead, and acceptance
still runs through the oracle discipline (`gcrip/oracles.py`) and the mandatory render gate.

    python -m gcrip.autocrack <file>            # pretty report
    from gcrip.autocrack import probe
    report = probe(data)                        # Report: probes + archetypes + summary()

Every probe returns `ProbeResult{name, fired, evidence, params}`.  A 42 MB buffer runs the
whole battery in ~13 s (caps: `MAX_GX_STARTS`, `GX_BUDGET`, bounded zlib inflates, capped
table scans); `probe(data, budget=)` bounds the total.

## The probes

### Containers

* **`chunk-stream`** - tag+size chunk runs that tile the buffer, three header shapes:
  size *including* the 8-byte header (EA SHOC - the `.scg`/`.hog` shape), size excluding
  it, and the VC record frame (16 opaque bytes, 4CC at +16, u32 size at +20, span
  `size+16`).  Fires at >= 4 chunks covering >= 90%.  On the LOTR `.scg` samples: 76-1,962
  chunks, 100% coverage, tags `CTRL/SHOC/PADD/FILL`.  On decoded VC members: `RTXT/ENCS/
  HTXT` runs, 100%.
* **`container-tiling`** - u32 offset/size table candidates (strides 8-32, both endians,
  table start in the first 256 bytes) whose spans **tile the buffer to the byte** - the
  identity that shipped `vc_dat` ("member spans account for every byte").  A column only
  qualifies as the offset column if it is in-bounds and ascending; up to 32 bytes of
  constant alignment padding between spans is tolerated and reported as non-exact.
* **`ascending-offsets`** - strictly ascending u32 columns at strides 4-32: offset tables
  without sizes, and **sorted hash arrays** (the CD bigfile identity: 4,314 ascending
  hashes is what a sorted lookup table looks like and what nothing else in a header does).
* **`name-table`** - NUL-terminated printable strings at the fixed strides real name
  tables use (16/32/36/64 - SKN bones are `char[32]`) plus dense back-to-back name lists
  (the Skye `.pak` shape).  Fires on the SKN material+bone block (stride 32 from +0x4c)
  and the Taz `.gcp` name list (698 back-to-back).

### GX display lists

* **`gx-display-list`** - tolerant opcode walks at vertex strides 5-16 from every draw-op
  candidate (greedy skip over claimed spans, gxscan-style).  Accepts NOPs, CP loads
  (`0x08`), XF loads (`0x10`), indexed-XF loads (`0x20/0x28/0x30/0x38`), BP loads
  (`0x61`) and draw ops `0x80-0xbf` (any VAT nibble).  Reports clean spans, prim/vertex
  totals, dominant stride, per-attribute max indices of the best span (via gxscan's field
  inference), and **naked-list detection** - no CP/XF setup at all, the TR Legend / Gun
  shape that hid from gxscan.
  * The noise gate matters: 8 MB of pure noise chains hundreds of 1-4-prim "spans"
    averaging >1,000 verts/prim.  The probe fires only on a dense span (>= 6 prims) or a
    span where setup ops chain with >= 4 modest-count prims; anything less is reported
    but labelled WEAK and not fired.  On the packed VC member this correctly stays quiet.

### Vertex arrays

* **`f32-positions`** - big-endian f32 xyz runs: finite, plausible 10-90-percentile
  extent, and the discredited-oracle guard - **the three components of a triple must
  differ** (an index buffer read as xyz has them nearly equal; `gcrip.oracles`,
  "triangle locality").
* **`s16-fixed-point`** - scent for s16 arrays at the standard fixed points seen this
  push (/256 SKN, /1024 Skye+LOTR, /4096 uv, /16384 normals): 1 KB pages scored on
  mid-range magnitude (the 0.82 threshold sits above uniform noise's ceiling of 0.81 and
  below real regions' 0.84-1.0) and value variety; the best region is reported with its
  per-divisor dequantized extent.  WEAK by nature - it ranks regions, never accepts.
* **`normal-runs`** - unit-vector runs: s16 at /16384 (the run test that located Gun's
  global normal array) and s8 at /64 (LOTR, VC) or /127 (TR Legend).  Detects both
  **packed** runs (non-overlapping triples) and **record-interleaved** normals (SKN
  12/16-byte rows, VC 16-byte entries) via triple-chains at a fixed element stride -
  `unit[i] & unit[i+s] & unit[i+2s]`, which noise cannot sustain.
* **`uv-runs`** - f32 pairs inside [0,1] (the Skye lesson: floats in [0,1] on a textured
  model are uvs, not "normalized geometry") and u16 pairs plausible at /4096.
* **`quaternion-runs`** - unit quaternions under the framings the `.skg` proved: bare
  `q4`, the 20-byte animation key (`f32 frame + q4`), `t3+q4` and `t3+q4+pad`.
  Distinct-value counting guards against a repeated constant (the oracle note: 358
  distinct of 400 is what made the skg keys evidence).
* **`matrix-runs`** - orthonormal 3x3 / 3x4/4x4 runs: row norms ~1 AND all three row
  pairs orthogonal (one small dot happens by chance on a packed unit-normal array; three
  at once is a rotation).  Reports the record stride - on `skye.skx` it finds the joint
  table exactly: 112 3x3 matrices from +0x24 at byte stride 128.

### Skeletons

* **`parent-table`** - i32/i16 sequences forming a valid forest (every parent precedes
  its child, roots are -1) at packed and per-record strides (the `.skg` keeps its i32
  parent at +0 of a 64-byte record - found there at stride 64 on the samples).  Ranking
  prefers nonzero information and the wider stride, because zeros are always-valid
  parents and an aliased finer stride pads its run with them.
* **`bone-names`** - bone vocabulary over the file's strings (`ROOT`, `L_UP_LEG`,
  `rhumerus`, `Bip01`...).  Confirmation-grade only: it points at where a skeleton is
  *named*, never how it is stored.

### Codecs

* **`zlib-streams`** - checksum-validated `0x78` CMF/FLG sites, each given a bounded
  inflate; reports count, clean ends, and decompressed volume.
* **`entropy-map`** - the per-4KB-page entropy profile that mapped Gun's regions, plus
  repeated-fill detection (32 bytes of `AB AB` is the MSVC heap fill, and 918 Gun
  "members" were exactly that).  Fires on a contiguous high-entropy region >= 16 KB.

## Archetype suggestions

From the probe pattern, the matcher suggests which of the cracked archetypes fits, each
with its evidence lines:

| archetype | trigger | exemplar |
|---|---|---|
| container (expand first) | chunk-stream or container-tiling | VC DAT, SHOC, CD bigfile |
| LZ-packed | zlib fires, or near-uniform high entropy with no structure | SHOC Zdat, VC pack |
| indexed-GX-arrays | GX lists **with** setup + separate attribute arrays | Blitz/Taz, Gun levels |
| naked-GX | GX draws with no CP/XF setup anywhere | TR Legend DRM, Gun props |
| bone-local-skinned | skeleton **with stored transforms** (matrix-runs + parents/names) | Darkened Skye SKX |
| dual-copy-baked | bone *names* but no transforms + GX lists | Acclaim SKN |
| fixed-point-flat | s16 fixed-point + unit normals, no f32 positions | SKN /256, Skye /1024 |

## Oracle utilities (exported)

The render gate is mandatory, so the module exports the guarded oracles for reuse:

* `edge_coherence(positions, tris)` - median edge / 10-90-percentile extent with the
  anti-gaming guards the Skye and VC notes demand: degenerate triangles dropped and
  counted, percentile extent against outlier inflation, and collapse detection (most
  edges near zero, or too few distinct vertices) that sets `gamed` and the score to inf.
  Even ungamed it is a *ranking* signal - only a render is acceptance.
* `connected_components(tris)` - component sizes; one body vs. ten thousand islands.
* `bbox_containment(positions, lo, hi)` - meaningful only when the box comes from
  somewhere the decode did not use (dequantizing against the same box is vacuous -
  `gcrip.oracles`, DISCREDITED).
* `triangle_identity(declared, produced)` - exact or nothing.
* `render_wireframe(positions, tris, path)` - three ortho views (matplotlib Agg); the
  only judge that was never gamed.

## Ground-truth hit table (2026-09-04, cached samples, zero disc reads)

| sample | key probes fired | archetypes suggested |
|---|---|---|
| Taz `.tba` x2 (from tazhub .gcp) | gx (CP/XF, stride 8), f32-positions, quats, matrices | **indexed-GX-arrays** |
| `HandL.SKN` | name-table (stride 32), gx (stride 6), s16, normals (strided 32), uv | naked-GX; **dual-copy-baked**; fixed-point-flat |
| `SkinRegH.SKN` | name-table, gx (stride 7, CP/indexed-XF), s16, normals (strided 16) | **indexed-GX-arrays**; **dual-copy-baked**; fixed-point-flat |
| LOTR `.scg` x3 | **chunk-stream 100%**, zlib (TTA members), entropy | **container**; LZ-packed |
| VC decoded `FRONTEND.IFF` | chunk-stream 100% (VC frame), gx, matrices | container; indexed-GX-arrays |
| VC packed member | nothing (correctly quiet) | - |
| `skye.skx` | matrices (3x3 @ stride 128 = the joint table), parents, f32, uv | **bone-local-skinned** |
| 8 MB uniform noise | entropy only | LZ-packed (by elimination) |

Misses worth knowing: the GX probe under-fires on VC scene members whose lists interleave
with vertex arrays (`GAMEDATA.IFF` stays WEAK; `FRONTEND` and `GAMEDATAEXTRA` fire) - the
chunk-stream probe leads the way into VC members regardless.  The `container-tiling`
probe found no false positives anywhere and is exercised by synthetic fixtures; the
cached sample set has no head-of-file offset/size container to fire it on (the Taz `.gcp`
keeps its directory at the tail).

Tests: `tests/test_autocrack.py` - synthetic fixtures per probe family, plus the
noise-stays-quiet check.
