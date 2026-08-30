# Cluster 2 (`.arc`) - resolved disc by disc, 2026-08-30

The cluster was six discs treated as one "single-zlib" family.  They are five different things.

| disc | state |
|---|---|
| Mega Man X: Command Mission | **DONE** - 1,467 `.arc` are a 32-byte header wrapping a stock TPL |
| Evolution Snowboarding | **DONE** - 29 `.arc` are `KCEO ARCDT` archives, 2,323 members |
| Cabela's x3 | zlib chain mapped, inner format unknown - see below |
| Over the Hedge | media plus two data archives, one of them entity script data |
| Mega Man X Collection | **dead end** - emulated 2D games, there is no 3D to rip |

## Cabela's - the chain is mapped, shipping it is not worth it yet

`data.arc` (248 MB on Outdoor Adventures, 615 MB on Big Game Hunter) is a chain of raw zlib
streams at **0x800-aligned offsets**, each inflating to about 2 MB - 11 blocks in the first
8 MB.  Every block opens `0c 00 00 00 a0 00 00 00` and carries FUN Labs' own structures
(`ADRIAN`, `PathGen 3.2`).

`gcrip.plugins.generic` already claims the file and inflates the **first** block, so a dedicated
container would add the other ~120.

**Deliberately not shipped.**  Inflating 248 MB into ~600 MB per disc, three times over, is a
real cost in a pass, and it buys nothing today: `gxscan` finds **zero** scenes in an inflated
block, and a search for every magic gcrip knows - TPL, DDS, FSBF, GCT, FMBF, FABF, BPXB, CUBE,
PKG - finds **none** of them.  The float runs are there (11,931 in one block) but are not
sequentially coherent (span-to-step 8,459), so they are not a strip or a simple vertex list.

The chain is worth shipping the moment something can read a FUN Labs block.  Until then it would
be rip time spent on blobs.

## Over the Hedge

Five `.arc`: `movies.arc` (574 MB) and `audiostr.arc` / `samples.arc` are media.  The data is
`datasets.arc` (399 MB, untouched) and `levels.arc` (2.9 MB), and the small one is **entity
script data**, not geometry - it is full of readable names like `EITrigger`,
`D_CAM_TriggerBox_HatTree`, `EICameraFollowDualSpline`, `S_Ambient_Wild_Loop`.  Models, if any,
are in `datasets.arc`.
