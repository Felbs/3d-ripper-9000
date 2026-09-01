# `.rws` on the cluster-1 discs is **audio**, not a model bundle (2026-09-01)

The backlog listed `.rws` RenderWare stream bundles as cluster 1 - the highest-return item -
across Asterix & Obelix XXL, Burnout 2, Call of Duty: Finest Hour, Frogger: Ancient Shadow,
Madagascar and Piglet's BIG GAME.  Five of those six produce nothing today.

**The premise is wrong.**  On the three discs whose `.rws` are not opened at all, every one of
them is streamed audio, and there is no geometry in them to find.

## What a `.rws` actually is on these discs

A single RenderWare chunk that wraps the whole file exactly:

    0x080D  the stream file, size == filesize - 12
      0x080E  a table of contents, ~2 KB
      0x080F  one data block, 40,960 bytes = 20 disc sectors

The inner chain covers the outer body to the byte on every sample.  The `0x080F` payload is
4-bit nibble data at **entropy 7.04-7.19** opening `30 1f 21 f0 10 10 f1 0f`, which is GameCube
DSP-ADPCM; the `0x080E` table holds offsets around 9 MB, into a larger stream than the file
itself.  Measured:

| disc | `.rws` | first chunk | lib stamp | entropy |
|---|---|---|---|---|
| Asterix & Obelix XXL | 631 | `0x080D` | `0x1803ffff` | 7.04 |
| Madagascar | 31 | `0x080D` | `0x1c020037` | 7.17 |
| Piglet's BIG GAME | 620 | `0x080D` | `0x1003ffff` | 7.19 |

`0x080D`/`0x080E`/`0x080F` are none of `CLUMP` (0x10), `WORLD` (0x0B) or `TEXDICT` (0x1A), which
is why `plugins/renderware.py` declines them - correctly.  **That the discs finish in 4 to 13
seconds is the tell**: a 1.4 GB disc whose largest readable files are audio has nothing for a
model plugin to walk.

Frogger: Ancient Shadow and Burnout 2 are the same story from the other side - their `.rws`
*are* expanded, into `g0000`-style members, and their biggest ones are `sound/st_house.rws` and
`music/trk10mgpl.rws`.

## Where the geometry actually is

| disc | holds the models | size |
|---|---|---|
| Asterix & Obelix XXL | 108 `.KGC` | ~16 MB each |
| Madagascar | 16 `.gcn` | up to 5 MB |
| Piglet's BIG GAME | `PIGGCN.pkd` | 232 MB, one file |
| Frogger: Ancient Shadow | `gamedata.bin` | 198 MB, one file |

### Madagascar's `.gcn` is a named-node tree, and it is the tractable one

Entropy **1.61** - structured, uncompressed - against 7.17 for its audio.  It opens with two
RenderWare-stamped chunks (`0x071C` then `0x0716`, lib `0x1802ffff`) and then stops being a flat
chain at offset 424, because the rest is a **node tree that names its own types in ASCII**:

    TD_LEVEL FOLDER
    rwID_TEXDICTIONARY
    c:\madagascar\content\data\xml\title\build output\gamecube\...

A format that spells out `rwID_TEXDICTIONARY` in the file is telling you what its nodes are,
and it carries the original build paths with them.  That is where cluster 1 should be worked,
not in the `.rws`.

## What this changes

Cluster 1 is not one format across six discs.  It is four different level containers - `.KGC`,
`.gcn`, `.pkd`, `gamedata.bin` - from four studios that happened to license RenderWare, plus a
shared audio format that was never going to yield a model.  Anything spent widening the `.rws`
sniff would have been spent decoding sound.
