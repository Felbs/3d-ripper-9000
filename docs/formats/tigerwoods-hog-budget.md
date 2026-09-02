# Tiger Woods `.hog`, and why the scanner never reached the geometry (2026-09-01)

Cluster 5 was listed as "`.hog` WART3.00 [Harry Potter x2, Looney Tunes, Animaniacs, Tiger
Woods x3]".  **That grouping is by extension, and there are two unrelated formats in it.**
The four Warthog discs are `WART3.00` (`docs/formats/warthog-hog.md`); Tiger Woods is EA
Redwood Shores and its `.hog` open `CTRL`, an EA `SHOC` chunk archive - already read by
`gcrip/formats/shoc.py`.

There are **six** Tiger Woods disc entries, not three: 2003, 2004 (2 discs), 2005 (2 discs)
and 06, carrying **1,213 `.hog`** between them.

## Why Tiger Woods 2003 reported zero

Not routing.  `gx.detect` returns `True` for its `.skg`, `plugins_for` returns `[gx]`, and
`gxscan` finds **8 meshes and 840 triangles in the first 128 KB** of `35char.skg`.  The
geometry is there and the plugin claims it.

The fallback scanner is budgeted (`GCRIP_GX_DISC_BUDGET`, 900 s per disc) and spent that
budget **biggest-first**.  On this disc that order is fatal twice over:

| what | count | size each | what a scan of it yields |
|---|---|---|---|
| `Data/Movies/intro.ngc` | 1 | ~100 MB | nothing - it is video |
| `.hog` course archives | 273 | 2-5 MB | **nothing - measured, see below** |
| `.skg` character models | 35 | 0.5-1 MB | 840 triangles per 128 KB |

A full `gxscan` of one 4.9 MB `hole.hog` - both the raw file and the reassembled `Rdat`
payload stream - finds **0 meshes and 0 triangles**, in 64.8 s and 29.2 s respectively.  So
273 files, each capped at the 45 s per-file budget, against a 900 s disc budget: the scan
cannot get past the `.hog`, and the `.skg` are never reached.  A run with the budget raised
to 5,400 s was still on file 21 of 381 after an hour and a half, which is the same result
from the other direction.

Two ordering fixes follow, both in `gcrip/rip.py`:

* **media last whatever its size** (`_looks_like_media`) - the empty-disc census already found
  that the biggest file on a disc is usually media *by path*, `Data/Movies/`, `streams/`,
  `packages/Music/`;
* **archives a real container plugin already walks, last too** (`_claimed_by_container`) - a
  `SHOC` `.hog` has its members expanded and routed through their own formats, so scanning the
  whole blob again is duplicated work.  Fallback containers are excluded from that test:
  `plugins/generic.py` claims every file there is, and counting it would deprioritise the
  entire disc and change nothing.

## How much of the library this affects

Tiger Woods is the case that exposed it, but the ordering was wrong nearly everywhere.  Taking
the ten biggest files on each of the 635 discs with a manifest - which is what the old
biggest-first order fed the scanner first - and counting how many are media by path:

| media among the 10 biggest files | discs | share |
|---|---|---|
| all 10 | **165** | 26% |
| 8 or more | 313 | 49% |
| 5 or more | 412 | 65% |
| 3 or more | 470 | 74% |
| 1 or more | 520 | 82% |

On a quarter of the library the scanner's entire per-disc budget went to video and audio before
it reached a single file that could contain a triangle.  The worst carry about a gigabyte of it
in those ten files alone - Frogger's Adventures 1,094 MB, Charlie's Angels 1,084 MB, SSX Tricky
1,075 MB, Freestyle Street Soccer 1,011 MB, NBA Live 06 1,006 MB.

## Correction: these archives are not "audio and configuration"

`docs/OPEN.md` recorded the 2003/2004/2005 `.hog` as **"Resolved negatively: audio and
configuration, not models"**, on the strength of the members that survive the parse.  That
reads the silence as evidence.  Measured on `01_peb/Hole_01/hole.hog` from Tiger Woods 2004
Disc 1, the archive **declares `ter` terrain (3,922,304 bytes), `txf` textures (1,471,392),
`tgd` (1,675,700) and `gras` (617,136)** in its `SHDR` chunks.  The resources are there and
named; they are dropped later because their payload does not reconcile with the declared size.
The same `ter` and `txf` resources are what `plugins/ea_obg.py` and `plugins/ea_txg.py`
already rip on Tiger Woods 06.

So the negative result was an artefact of the reconciliation check, and the row is wrong.

## What is inside `hole.hog`, as measured

The chunk walk in `gcrip/formats/shoc.py` is sound - it covers **100.0% of the file**, 932
chunks: 700 `SHOC`, 181 `FILL`, 48 `SONO`, 2 `PADD`, 1 `CTRL`.  Blocks are 0x78000 bytes and
the bare four-byte `FILL` pad at each boundary is already handled.

What does not work is member reconciliation.  78 `SHDR` heads are found and **only 57 members
survive, totalling 5,204 bytes of a 4.9 MB file**.  The small `Cact` members reconcile; every
large resource fails its declared size:

| resource | bytes collected | declared | |
|---|---|---|---|
| `ter` (terrain) | 2,319,208 | 3,922,304 | 59% |
| `tgd` | 1,037,900 | 1,675,700 | 62% |
| `txf` (textures) | 707,396 | 1,471,392 | 48% |
| `gras` | 381,860 | 617,136 | 62% |
| `TEO` x6 | 984-10,764 | 4,480-21,504 | 22-50% |

Those are **raw bytes collected, not inflated bytes** - `ter`'s blob does not start with a zlib
header, so the reader's inflate branch is never taken and the member fails the size check on
its raw length.

The cause is not yet established and is **recorded as reconnaissance, not a finding**.  What
is known: the 551 `Rdat` chunks each carry a ~48-byte prefix of little-endian pointer-shaped
words (`0012dc40`, `0012fcc4`, `0040124e`), a dumped runtime struct rather than data, and only
18 of 551 share the same one - so the prefix is per-resource, not per-file, and `RAW_PREFIX`
being stripped once from the joined blob cannot be right.  Feeding every later data chunk into
one decompressor while ignoring intervening `SHDR` markers fails immediately with `incorrect
header check`, so the resources are not one contiguous stream either.

### The terrain is `OBG `, behind an LZ stream

The gap is not interleaving.  Taking **every** data chunk from `ter`'s `SHDR` to the end of the
file still gives only 3,770,284 bytes against 3,922,304 declared, and file-wide the data chunks
hold 4,478,132 bytes against 7,753,488 declared across all `SHDR`.  More is declared than is
stored, so the payload is compressed - just not with zlib and not from byte 0.

Dumping the first `ter` data chunk past its prefix shows what it is::

    +64  00 00 20 2e 88 0a  4f 42 47 20  01 04 00 00  41 52   .. ...OBG ....AR
    +80  90 03 88 30 19 04 00 00 06 3f 00 04 00 00 5a 7a      ...0.....?....Zz

`OBG ` at +70 is **the same EA terrain format `plugins/ea_obg.py` already rips on Tiger Woods
06**, and `41 52` immediately after is the start of its `ARRA` array tag.  The `88 0a`, `90 03`,
`88 30` between the literal runs are LZ control bytes - literals, then back-references - so each
resource is one LZ stream carrying an ordinary `OBG `/`TXG ` payload.

Identifying that codec is the whole job.  It is not zlib and not EA refpack at the stream start
(no `10 fb`), and it is the single thing standing between six discs and their course terrain and
textures, both of which gcrip can already read once decompressed.

The payload is worth returning for: `Rdat` is 2.97 MB at 7.64 bits/byte and contains `TXG `
and `HEAD` tags, and `gcrip/formats/ea_txg.py` already reads `TXG `.  The course textures on
six discs are behind this.
