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


## CRACKED: Madagascar's `.gcn` (2026-09-01)

`gcrip/formats/tfb_gcn.py` + `gcrip/plugins/tfb_gcn.py`.  **114,936 triangles from one file**,
on a disc that reports zero today.

A `.gcn` is a flat chain of little-endian RenderWare-style chunks that covers the file to the
byte - 5,028,968 of 5,028,968 on `title.gcn`.  Three types: `0x071C` a class census, `0x0716` a
named resource, `0x0704` unread.

The census is genuinely useful on its own: `u32 count` then NUL-terminated names padded to four
bytes with `0xBF`, each with an instance count - `CTFBModel` 15, `CProtoActor` 48,
`SpriteObject` 165 - so a level says what it holds before anything is opened.

A resource carries its payload behind a header whose **first word is the header's own length**,
so the payload is at `body + 8 + header` and the build-path strings never have to be walked.
It is confirmed by ending flush with the chunk, allowing the 1 to 3 bytes of four-byte
alignment padding that made a strict test miss 24 of 49 resources.

That finds **46 of the 49** RenderWare resources - every `rwID_CLUMP` (18), `rwID_WORLD` (5),
`rwID_TEXDICTIONARY` (3) and `rwID_HANIMANIMATION` (20); only the three `rwID_2DFONT` differ.
The payloads need no new reader: `plugins/renderware.py` takes them as they are, giving
`mort_giant.dff`, `bird_big_mouth.dff`, `penguin_tube_loading.dff` and six world sections.

**The trap**: the payload's library stamp is the old style `0x1c020016`, with no `0xffff` build
bits, so a hand-rolled scan insisting on those finds *nothing at all* - which is exactly what my
first pass did. `rwstream.looks_like_stream` already knows about old-style stamps.

### `.gcn` is not one format - checked, not assumed

Seven discs carry `.gcn` and five produce nothing, so it was tempting to claim all of them.
Only Madagascar is this format.  Cocoto Funfair (42 files), Cocoto Platform Jumper (41), Cocoto
Kart Racer (16) and Charlie's Angels (13) share a **different** one with each other:

* the first `u32` is **big-endian and equals the file size minus 8** - 0x003f875a against
  4,163,426 bytes, 0x002a7516 against 2,782,494, exact on all four;
* the word at +8 is `0x000000ef` on every one.

That is four more discs at zero, on one shared format, and a clean handle to start from.  It is
not this reader's.


## Asterix's `.KGC` - reconnaissance, not cracked (2026-09-01)

108 files: 146 bytes of level metadata at the small end, three of 15-16 MB at the large.  Entropy
5.88 to 7.15, so parts are compressed.  Header, little-endian::

    +0   u32  varies per level - 0x86d8, 0x84a2, 0x76c1
    +4   u32  0x0002e50a / 0x0002e50b - near constant, a version
    +8   u32  0x00000500
    +12  u32  0
    +16  packed words that repeat: 0x00010001, 0x01000100, 0x00010000, 0x01000001

They carry the asset names in the clear, with LOD suffixes, so the naming survives whatever
packs them: `spec1_obelix`, `spec1_pirnl_sabre_lod0`, `it_baril_rayons_b01_p0`,
`he_pier_templ_d01_p0`, `100_specmap6`, `sfx_cascade06a`, `ico_jauge02`.

**Two cheap tests, both negative, both worth not repeating:**

* the trick that cracked Madagascar finds nothing here - scanning for `CLUMP` / `WORLD` /
  `TEXDICT` / `GEOMETRY` / `ATOMIC` headers with any plausible library stamp gives **zero hits**
  across three 256 KB samples, so this engine does not embed RenderWare streams whole;
* there is **no offset table** in the first 8 KB.  The longest ascending in-range run is twelve
  small integers (95, 107, 108, 110, ...), which are indices, not offsets, and the header words
  are repeating packed patterns rather than a directory.

So `.KGC` is a serialised structure to be walked from byte 0, not an archive with a table -
the same shape of problem as TotemTech's `.dgc`.  That is a session of its own, and the two
negatives above are the ones not to spend it on.
