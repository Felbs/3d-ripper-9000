# gxscan's salvage pass (2026-09-03)

`gcrip/gxscan.py` is the universal fallback - the display-list scanner that runs on every
file nothing else claims, across 540 non-ripping games.  Its walk is **greedy**: an accepted
chain claims the bytes it covers and later starts inside them are skipped, which is what keeps a
whole-archive blob affordable.  The cost is that one accidental chain can bury every real list
behind it.  On TimeSplitters 2's `ob__chrs__chr128.gcr` a spurious 1,397-vertex chain at offset
254 covers 35 KB and hides 562 genuine strips; the file scanned to 36 triangles.

## The pass

When a chain is rejected by the geometry score, the span it claimed is remembered.  After the
first sweep, those spans are re-walked with the skip off, the chains found are **ranked** by how
much they look like real lists - many primitives at one stride, index bytes that stay small
because they address an array - and only the best 24 are scored, two strides each.  Scoring is
the cost: 30-46 s a file when every candidate is scored, 1-5 s when the best few are.

## Benchmark

Twenty-two files from twelve zero-model discs (the biggest low-entropy file on each, 4 MB
each) plus the TimeSplitters character, scanned by the shipped scanner and then by this one:

| file | before | after | time before | time after |
|---|---|---|---|---|
| `ts2_chr.gcr` | 36 | **16,897** | 4.1 s | 9.1 s |
| Conflict: Desert Storm `training2.sch` | 93 | **877** | 17.5 s | 27.3 s |
| Geist `03A_X_1HeliPad.GSF` | 5,467 | 5,496 | 82.0 s | 90.4 s |
| sixteen files with nothing in them | 0 | 0 | 3-65 s | +50-100% |
| **total** | **5,738** | **23,412** | 561 s | 804 s |

Four times the triangles, and the whole extra cost was on files that had nothing to give.

## The gate

Every file that gained had already produced at least one mesh on the first pass; none of the
sixteen that produced nothing gained anything.  So the salvage runs **only when the first pass
found something** - that is the evidence the blob holds GX geometry at all.  Re-benchmarked
with the gate: the gains hold exactly (16,897 and 877) and the empty files return to their
baseline time to the tenth of a second (21.6 s and 8.2 s).

This is not a circular test: the first pass is a fixed, independent scorer, and the gate reads
its verdict rather than the salvage pass's own.
