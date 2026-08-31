# ZIPs whose central directory does not point at their data

NFL Blitz 20-03 and Blitz 20-02 ship their game data in ordinary-looking ZIPs - `PK 03 04`, a
proper central directory, correct entry names and sizes.  Python's `zipfile` lists all 1,981
entries of `stadium.zip` happily.  **Reading any of them fails**: the offsets in the central
directory do not point at local headers, so every `read` raises
`Bad magic number for file header`.

`gcrip/plugins/zip.py` caught those per member and moved on - the right instinct, one bad
member must not lose the rest - so a 179 MB archive holding **1,334 RenderWare `.dff` models**
came back as an empty archive, with no error anywhere.

## The entries are all there; only the directory is wrong

Walking `PK 03 04` records from offset 0 recovers **all 1,981 with every CRC matching**, and
the walk finishes exactly on the central-directory signature.  That last part is what makes it
a proof rather than a guess: a mis-parsed record would drift and land nowhere in particular.

`gcrip/formats/zip_local.py` does that walk, and the plugin uses it **only as a fallback**, so
a normal archive still goes through `zipfile`.  The CRC in each local header is what makes it
safe - a mis-parsed record almost never produces a payload that checksums, so a bad walk yields
nothing rather than garbage.

## What it recovers

    NFL Blitz 20-03   stadium.zip  171 MB   1,981 members   1,334 .dff
                      sound.zip    167 MB   5,388
                      shell.zip     35 MB     350
                      players.zip   40 MB     296     124 .dff
    Blitz 20-02       stadium.zip  122 MB   1,764 members   1,185 .dff
                      sound.zip    152 MB   5,435
                      players.zip   31 MB     241      83 .dff
                      ... and five smaller archives

**16,090 members over the two discs, about 2,780 of them RenderWare `.dff`** - a format gcrip
already reads.  Both discs were producing nothing at all.

## How far this reaches: two discs, and no further

Testing every top-level `.zip` / `.pak` in the library that actually begins `PK 03 04` - 458
files, on 70 discs - the local walk beats `zipfile` on **exactly the fourteen archives of the
two Blitz discs** and on nothing else.  Every other ZIP in the library reads normally through
the central directory.

So this is a two-disc fix, not a library-wide one, and the fallback will stay dormant
everywhere else.  Worth stating plainly, because "walk the local headers" sounds like it ought
to rescue more than it does.

One small honest gap: Blitz 20-02's `stadium.zip` lists 1,766 entries and the walk returns
1,764.  The two missing are entries whose payload does not match the CRC in their own local
header, and they are dropped rather than passed on - which is the behaviour the CRC check
exists for.
