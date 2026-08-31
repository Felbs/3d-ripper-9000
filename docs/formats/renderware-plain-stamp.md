# RenderWare files refused for having an old version stamp

`rwstream.looks_like_stream` is the cheap sniff every RenderWare file goes through.  It
accepted two shapes of library id - the modern packed stamp with `0xffff` build bits, and the
RW 3.2-3.7 builds without them - and refused everything else.

Older RenderWare writes the library id as a **bare version number**: `0x0310`, `0x0304`.  Those
were refused, and the files fell through to the structure scanner, which scavenges a few
triangles out of anything.

**They parse perfectly.**  Extracting 60 refused `.dff` from NFL Blitz 20-03 by hand, bypassing
the sniff: **60 of 60 produce scenes, 5,900 triangles, nothing raised.**  The reader was never
the problem.

    NFL Blitz 20-03   1,334 .dff:  357 packed (accepted), 975 plain 0x310, 2 plain 0x304
    after the fix     1,511 .dff detected, first 120 giving 341,791 triangles
    Blitz 20-02       1,272 .dff detected, first 120 giving 244,164 triangles

## How far it reaches

Sampling every disc whose `.dff` are addressable from the manifest - 14 of them, 280 files -
the stamps split **115 packed, 87 plain, 45 old-style, 33 other**.  Six discs beyond the two
Blitz titles carry plain-stamp files that were being refused:

    Burnout            Driven            Outlaw Golf
    Redcard 20-03      MLB SlugFest 20-04   MLB Slugfest 2003

Midway's own games (Blitz, Redcard, Slugfest) and Criterion's early ones (Burnout, Driven).
That is only the discs whose `.dff` sit at a readable disc offset; files inside archives were
not sampled, so the true reach is larger.

The refusal is now three classes instead of two, and a nonsense library id is still refused -
pinned by a test in both directions.

## The rest of the "other" stamps are not RenderWare

The same sample left 33 files in no class at all.  They are not more of the same:

* **Call of Duty: Finest Hour's `GodData.dff`** - type `0x0719`, library id `0`, chunk size 34
  in a 5 MB file.  Treyarch's own format wearing a `.dff` name; nothing to accept here.
* the remainder read as `0x01000000`, `0x04000000` and similar - byte-swapped values rather
  than plausible little-endian chunk types, so either big-endian streams or not RenderWare.
  Left alone rather than guessed at.

## Re-checking cluster 1 with the fixed sniff

`.rws` was closed earlier as RenderWare **audio**, and that conclusion was reached with the
sniff in its broken state - so it was worth re-testing rather than trusting.  It holds.
Sampling Asterix & Obelix XXL (631 files), Piglet's Big Game (620), Burnout 2 (150),
Madagascar (31) and Frogger: Ancient Shadow (19), every chunk type is **`0x080d` (109) or
`0x0809` (30)** - both in RenderWare's audio range.  No `CLUMP`, no `WORLD`, no `TEXDICT`
anywhere in the sample.

A conclusion drawn with a broken tool deserves re-testing; this one survived it.
