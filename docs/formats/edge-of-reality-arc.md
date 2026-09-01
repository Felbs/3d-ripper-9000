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

## Still open

The member formats. None of the 1,913 is a TPL, so nothing decodes them yet:

* The Sims' `datasets.arc` members open with readable tags - `RD_S`, `RD_P`, `RD_T` - so that
  is the thread to pull first;
* `models.arc` members (901 of them) open with four zero bytes;
* `rletextu.arc` members open `ff 00`, and the category name says run-length-encoded textures.
