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

## Inside a dataset - the structure is solved, the pixel format is not

A dataset member is the index's own idea one level down, and it walks cleanly:

    char name[]        NUL-terminated: "RD_TRAINSET_-_CHEAP_A"
    u32  sections
    then per section:
        char name[]    "Textures", "RleTextures", "Animations", "Samples", "Binaries"
        u32  count
        then per entry:
            u32 hash
            u32 size       from the start of the name to the end of the entry
            u32 0
            char name[]    "LFXTstrings_theory_stereo", "LFXTmusic_note_particle"
            u16, u16 width, u16 height
            12 bytes
            the pixels

**Entries are interleaved with their payloads and the stride closes exactly**: the first entry
of `0fcf8afd` sits at 47 with `size` 2094, and `47 + 12 + 2094 = 2153` is precisely where the
second entry's hash begins.

**270 of The Sims' 309 datasets parse**, and the dimensions are the proof: every pair is a
power of two - 32x32 (72), 64x64 (45), 128x64 (37), 128x128 (36), 512x512 (24), 16x16 (12),
64x32 (11), 512x256 (9), 256x256 (8), 256x128 (8).  A layout read at the wrong offset does not
produce powers of two 270 times.

**This is where the missing texture dimensions live**, which is what `rletextu` needs - no
member of that archive states its own size.

### The flag byte identifies the depth, and the pixels still resist

Walking the whole dataset tree gives **5,092 entries** across every section - Animations 2,708,
Textures 752, Shaders 738, RleTextures 371, Models 343, Characters 96, ParticleTypes 64,
QuickDatas 6 - so the container reading is not in doubt.

The two bytes before the dimensions are a format flag, and bits-per-pixel separates them
cleanly (payload bytes * 8 / (width * height)):

| flag | n | bpp min / median / max | reads as |
|---|---|---|---|
| `81 04` | 455 | 4.000 / 4.016 / 4.250 | 4 bpp, no palette |
| `89 04` | 109 | 4.002 / 4.516 / 6.062 | 4 bpp plus a small palette |
| `8a 08` | 188 | 8.125 / 10.004 / 136.250 | 8 bpp plus a 512-byte palette |

`81 04` sitting on 4.000 to 4.016 across 455 entries says the payload is **raw and fixed-size**,
not compressed - a compressor does not land on exactly four bits per pixel 455 times.

**And yet it does not decode as an image in any of the obvious readings.**  Scored as the
median ratio of a shuffled copy's roughness to the decode's - every texture genuinely cracked
in this project scores 3x to 69x:

    8a 08  GX I8 tiles      2.91x        89 04  C4, palette last     1.78x
    8a 08  C8, palette last 1.49x        89 04  C4, palette first    1.39x
    8a 08  C8, palette first 1.35x       81 04  GX CMPR              1.09x
    81 04  GX I4 tiles      0.98x        81 04  linear 4 bpp         1.20x
    8a 08  linear 8 bpp     1.73x

Nothing clears 3x, and the largest group is indistinguishable from noise either tiled or
linear.  So the depth is known, the dimensions are known, and the pixel order is not.

**PS2 swizzle was the obvious next guess and it is wrong.**  These are PS2-era multiplatform
titles, so the standard `PSMT8` unswizzle was the first thing to try on the 8 bpp group: it
scores **1.32x**, *worse* than reading the same bytes linearly (1.73x).  Ruled out.

That leaves a per-block encoding as the likeliest answer - the sibling category being called
`RleTextures` says this engine does encode its textures.  Nine readings are now eliminated;
the next attempt should start from the payload's own structure rather than from a layout guess.

## Still open

* the pixel format inside a dataset's `Textures` entry - the structure around it is solid, so
  this is now a question about one blob with known dimensions rather than about the container;
* the RLE scheme for `rletextu`, whose dimensions can now be looked up by hash in the datasets;
* the `models.arc` payload, which is not GX.
