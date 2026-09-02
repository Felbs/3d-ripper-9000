# Cabela's `MULA` texture archives (2026-09-02)

``MULA`` texture archives and their ``GCT `` images - Cabela's, inside ``Data/data.arc``.

Cluster 2's last three discs.  ``docs/OPEN.md`` had them down as a dead end: *"gxscan finds
nothing in an inflated block and none of gcrip's magics appear, so it would cost ~600 MB of
inflation per disc for no output"*.  That was measured on **the first block only**, and
``data.arc`` is not homogeneous - it is a chain of raw zlib streams at 0x800-aligned offsets
whose contents differ completely along its 307 MB.  The first blocks are navigation data
stamped ``PathGen 3.2``; the middle holds Lua (``LoadScript("Sound\\stdsound.snd")``); and the
tail is ``MULA``, a named texture archive.  Sampling one block and generalising is what made
the disc look empty.

## The archive

Little-endian::

    +0    char magic[4]      "MULA"
    +4    u32  count
    +8    count x { u32 size; u32 name_offset }
    then  u32  string table bytes
    then  the NUL-terminated names, `name_offset` counted from here
    then  the payloads, in entry order, `size` bytes each

**The identity that checks it**: the payloads tile the rest of the block exactly.  On the two
blocks small enough to inflate whole, ``data_start + sum(size)`` comes to 412,520 and 147,312 -
their inflated lengths, to the byte - with 192 of 192 and 90 of 90 names decoding as ordinary
paths (``TEXTURES\\LEVELS\\COLORMAP\\MAP7\\MAP7A_GRD_01_X1.GCT``).

## The images

Each payload holds one image, big-endian::

    +0    char magic[4]      "GCT "   (the payload pads it to 0 or 2 - see `gct_at`)
    +4    u16  width
    +6    u16  height
    +8    u16  GX texture format
    +12   u8   mip levels
    +16   u32  pixel bytes
    +28   the palette, if the format has one, then the pixels

with a 32-byte header counted from the start of the payload rather than from the magic.

**And the identity that checks that**: ``32 + palette + pixel bytes == the entry's size``, on
**200 of 200** textures.  It also settles the palette sizes rather than assuming them - the
first 136 matched with a 512-byte palette and 64 did not, every one of those format 8 and every
one short by exactly 480, which is 512 - 32: format 8 is ``C4`` with 16 entries, format 9 is
``C8`` with 256.  Formats seen are 9 (126), 8 (64) and 14 (CMPR, 10).

## What it changes

`docs/OPEN.md` listed the three Cabela's discs as cluster 2's dead end.  They are not: the
tail of `data.arc` is full of named textures.  `plugins/cabelas_arc.py` walks the zlib chain
and keeps only the `MULA` blocks - inflating all ~8,300 to hand back navigation meshes and Lua
would cost hundreds of megabytes for nothing - and `plugins/mula.py` decodes each archive into
one textures-only Scene.

On the two blocks small enough to hold whole in the sample, **282 textures decode** (192 and
90, all of them).
