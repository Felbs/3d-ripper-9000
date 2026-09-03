# Harry Potter and the Goblet of Fire - what is actually on the disc (2026-09-03)

The census has this disc at **0 models and 0 triangles**, and the backlog files it under cluster
5 with the other Harry Potter titles.  It is not a `.hog` disc at all.

## Eight files, and 956 MB of them are EA BIG

    data.big     217,025,920   BIGF, 153 entries
    movies.big   269,667,544   BIGF
    music.big    356,610,432   BIGF
    speech.big   112,839,296   BIGF
    gof_f.elf    277,639,896
    gof_f_us.elf   5,128,148
    GOF.DDF              275   an ASCII [Input] config
    opening.bnr        6,496

**`plugins/ea` already claims all four `.big`** - the container is not the gap.  `data.big`
holds 153 members and **152 of them are `.str`**, named as GUIDs
(`{0376F13E-F524-4382-8577-1C8A664A32AB}.str`), plus one `fingerpr.int`.

## The members are RenderWare streams with EA's own chunk ids

A `.str` opens as an ordinary RenderWare chunk - `u32 id, u32 size, u32 version` - with a
**version stamp of `0x1802FFFF`**, which is RenderWare 3.6.  The ids are not the stock ones:

    0x071C   size 28-64, carrying a name - "TriggerBox"
    0x0716   carrying the original build path and a `.dir` reference

and the paths are the developer's own:
`Z:\gof_game
ws\GobletofFire\Build Output\GameCube\Folder\{59969448-...}.dir`.

## What was checked and did not fire

On the three smallest members pulled (1,120, 6,720 and 109,888 bytes):

* **no stock RenderWare geometry chunks** - no CLUMP, WORLD, GEOMETRY, ATOMIC, TEXDICT or
  GEOMETRYLIST anywhere in them, at any offset, with a plausible size and a 3.x version stamp;
* **no native groups** - `formats/rw_native.py`, which cracked Piglet's native geometry, finds
  nothing: 0 candidate strip runs.

Those three are small metadata assets, so it was not evidence about the disc.  **The two
largest members were then pulled** - 7,345,024 and 7,157,408 bytes - and they are not geometry
either.  They are gameplay scripts: the strings read `bcAsymmetricZoneModelBucketsBehaviour`,
`CharmConfigObject`, `GenericJinxShot`, `RicochetShot`, `BubotuberPusShot`, `ClusterGrenadeShot`.

A strip scan on them looks like a find and is not, which is worth recording: chaining `0x98` at
stride 8 turns up **261 runs and 6,016 vertices** on one of them.  They are noise.  The four
index columns agree on **1-2%** of vertices where a real group agrees on 100%, the maximum index
is 65,535, and only 3,689 distinct values appear.  `0x98` is a common byte and script data is
full of it.  The containment test in `formats/rw_native.py` rejects every one of these runs,
which is what it is for.

So `data.big`'s big members are scripts, and where the geometry lives on this disc is still
unknown.  `movies.big`, `music.big` and `speech.big` are named for what they hold; the untested
places are the rest of `data.big`'s 152 members and the **277 MB `gof_f.elf`**.

## Why this matters

The disc is 956 MB of content behind a container gcrip already opens, and the inner format is
RenderWare - the family `plugins/renderware.py` and now `plugins/rw_native.py` both read.  It is
much closer to reachable than "0 models" suggests.
