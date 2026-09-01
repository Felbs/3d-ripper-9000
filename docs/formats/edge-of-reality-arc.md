# Edge of Reality `index.ind` + `.arc` - The Sims, Shark Tale, Over the Hedge - CRACKED

Three discs with **fourteen to nineteen files each**, almost all of the bytes sitting in a
handful of unnamed `.arc` blobs that open with zeros. All three reported **two textures** and
no models, because nothing opened an `.arc`.

Read by `gcrip/formats/edge_ind.py` + `gcrip/plugins/edge_arc.py`.

| disc | files on disc | `.arc` | MB |
|---|---|---|---|
| Over the Hedge | 15 | 5 | 1,196 |
| Shark Tale | 14 | 4 | 1,032 |
| The Sims | 19 | 7 | 410 |

The directory for every archive is the single `index.ind` beside them - 223 KB, 133 KB and
123 KB respectively. It is read through the `NEEDS_SIBLING` / `expand_with` hook, the same one
Eurocom's `Filelist.000` uses.

## The index

Big-endian. A flat list of segments:

    +0    u32 count
    +4    (count + 1) u32 offsets into this file, ascending; the last is the file length

`offsets[0]` is exactly the end of the offset table and `offsets[-1]` is exactly the file
length, which is what identifies the format - the archives themselves have no magic at all.

The segments alternate a short printable **category name** and that category's **table**, and
the names say precisely where everything lives:

    Levels  QuickDatas  Graphs  QDMetadatas  Characters  Models  Occluders  Animations
    BonePositions  Havoks  Fonts  Movies  PclEffects  Shaders  Textures  Sounds  Binaries
    Samples  AudioStreams  Programs  DataBuilders  Datasets        (Over the Hedge, 21 of 22)

## The table is a sorted hash array, not a record array

    u32 count
    count * u32           name hashes, strictly ascending
    count * (u32 offset, u32 size)

`4 + count * 12` is the same length either way, so it *measures* as an array of twelve-byte
records - and read that way it yields three columns of entirely plausible 32-bit numbers, none
of them ascending and all of them meaningless. What gives it away is that the **first `count`
words are sorted**: it is a binary-search table with the payload locations after it. The reader
requires that sort, which is the only thing separating the two readings.

## Which archive a category lives in

**Its own name, truncated to eight characters** - `AudioStreams` to `audiostr.arc`,
`QuickDatas` to `quickdat.arc`, `RleTextures` to `rletextu.arc`. That is a guess, and it is
made safe by an exact check: the category's `max(offset + size)` has to account for the
archive's length.

Eleven of the sixteen category/archive pairs across the three discs land **on the byte**:

    Over the Hedge   Levels 2,894,207   Movies 574,376,316   Samples 61,154,604
                     AudioStreams 216,477,632   Datasets 399,527,193
    Shark Tale       Movies 444,219,776   Samples 33,133,851   AudioStreams 344,887,680
    The Sims         Movies 101,379,296   Samples 113,860,974   AudioStreams 150,309,798

The other five stop 156 to 64,357 bytes short of a padded tail - the worst being 0.73% of an
8.7 MB archive. **Demanding an exact match rejects two of the three discs outright**, and
Over the Hedge is precisely the disc that hides it, because all five of its archives are exact.
The allowance is still a real check: a wrong pairing misses by a different order of magnitude,
Over the Hedge's `Models` ending at 73 MB against a 399 MB `datasets.arc`.

A category with no matching archive - `Models` and `Textures` on Over the Hedge, which ships no
`models.arc` - is left alone rather than pointed at the nearest file.

## Results

Audio and video categories are skipped rather than carried: `Movies` alone is 574 MB on Over
the Hedge and none of it is geometry.

| disc | archive | members |
|---|---|---|
| The Sims | `models.arc` | 901 |
| | `rletextu.arc` | 377 |
| | `datasets.arc` | 309 |
| | `quickdat.arc` | 5 |
| Over the Hedge | `datasets.arc` | 153 |
| | `levels.arc` | 62 |
| Shark Tale | `datasets.arc` | 106 |

**1,913 members** on discs that had none. This closes the `Over the Hedge datasets.arc` entry
that had been sitting in `docs/OPEN.md`.

## What the members are - first pass

None of the 1,913 is a TPL, so nothing decodes them yet, but each category has a legible shape:

**`models.arc` (901 on The Sims) - named.** Four zero bytes, then a NUL-terminated name from
+6: `the_terrain_for_neighborhood_screen(derived_from_rev46)`.  After the name the payload is
dense and unaligned - one string in the first 20 KB, no plausible float or offset columns - and
**`gxscan` finds nothing in any of the six largest**, so the geometry is not GX display lists.

**`datasets.arc` (309 / 153 / 106) - nested containers.** A member opens with its own name
(`RD_TRAINSET_-_CHEAP_A`), then a count, then a sub-category name - `Textures` - so a dataset
repeats the index's own name-then-table idea one level down.  That is the most promising thread:
it is the only category that says in plain text what it holds.

**`rletextu.arc` (377) - a palette then RLE indices.**  The first 1,024 bytes are **256 ARGB
entries**, alpha first.  That byte order is not a guess: read from offset 0 the first column
takes only **three distinct values** across all 256 entries (255 on 217 of them, 0 on 36, 190 on
3) while the other three take 150, 144 and 122 values over a smooth ramp -
`(255,199,170,130) (255,205,175,135) (255,212,182,142) (255,221,192,151)`.  A colour channel
does not behave like that; an alpha channel does.  The remaining ~62 KB is the RLE stream.

## Still open

* the RLE scheme and the image dimensions for `rletextu` - nothing in the member states a size,
  so the dimensions probably live in the `Textures` table of the dataset that references it;
* the `models.arc` payload, which is not GX;
* the `Textures` category on Over the Hedge and Shark Tale, which have no `textures.arc` - like
  `Models` there, they must be reached through `datasets.arc`.
