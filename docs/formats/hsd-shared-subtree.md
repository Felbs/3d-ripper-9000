# HSD: a shared subtree hangs the reader forever (2026-09-02)

Found by chasing two library shards that stopped writing to their logs and never resumed - 39
and 13 minutes with no error, no output and no exit.  The file is
`files/choice/Result/l_result_back.dat` on **One Piece - Treasure Battle!**, 680,862 bytes.

## What happens

`Jobj.walk()` is iterative, and deliberately so - recursing costs a Python frame per joint and
these trees come out of disc data.  It has no **visited set**, and it did not need a cycle
guard because the parser already rejects a joint that is its own ancestor.

Nothing rejects a joint that is its own *sibling's* child.  Two children can point at the same
subtree, and a tree read out of arbitrary bytes does that freely.  The walk then enumerates
**paths, not nodes**, which is exponential in the sharing depth - forty levels of it is a
trillion paths, and the process simply never comes back.

The symptom is the worst kind: no exception to catch, no progress line, and a shard of the
library pass that looks alive to every check except the log's timestamp.

## The fix, in two halves

`Jobj.walk()` now yields each joint **once**, keyed on its offset.  Both callers - the
`handled` set in `models()` and the joint list a Scene gets - wanted distinct joints anyway.

Fixing only that moved the freeze into `world_matrices`, which is a *second* walk of the same
tree, recursive, and equally exponential; it turned the hang into

    IndexError: list index out of range

because a joint visited twice had its `index` reassigned underneath a child that had already
recorded it.  That walk is now iterative and de-duplicating too, and keeps the same depth-first
order.

## Measured

`l_result_back.dat` went from **never finishing** to **0.12 s and 6 scenes**.  All 24 files
around it on the disc now read; none takes more than 0.12 s.

Two tests pin it, built from the shape rather than the file: a forty-level diamond, which is
2**40 paths and 41 joints, must walk in 41 steps and must number its joints 0..40 once each.
