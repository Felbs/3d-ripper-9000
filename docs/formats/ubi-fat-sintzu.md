# Ubisoft `.fat` / `.000` and Rise of Sin Tzu's `geoobj.bin` (Batman: Vengeance, Batman: Rise of Sin Tzu)

Read 2026-09-04 (`gcrip/formats/ubi_fat.py`, `ubi_geoobj.py`, `gcrip/plugins/ubi_fat.py`, `ubi_geoobj.py`, `tests/test_ubi_fat.py`).

## The archive

Vengeance ships three pairs (`levels`, `Dlr`, `Etf`), Sin Tzu one pair a level (37).  `.fat`
is little-endian: a byte `01`, then records that **end** `u32 time, u32 time, u32 length,
"/gamedata/...\0"`; a directory (name ending `/`) has 16 bytes before the times, a file 20:
`u16 flags, u16, u32 index, u32 offset, u32 unpacked, u32 packed`.  The reader locates each
record by that tail - the two 2001-2003 timestamps followed by a length and a `/` - because
a directory record's leading bytes are tool memory (`nary`, `ild#`).

`.000` holds the files at their offsets as `u32 unpacked (8,192), u32 packed, u32
0xdeadbabe, u8 flag` blocks of **LZO1X**.  Flag 3 opens a file, flag 1 continues it **and its
matches reach back into the earlier blocks' output** - `gcrip.formats.lzo.decompress` grew a
`history` argument for it - and flag 0 is a stored block.  The `.fat` is the container
(`NEEDS_SIBLING`, the `.000` fetched beside it) and members come out by their `/gamedata/`
path.

## Sin Tzu's members

A level's archive holds 421 `.tsd` pictures, 81 `.bin` and 42 `.a3i` animations.  The
geometry is `binary_vr/<level>/3d/gli/geoobj.bin`: `u32 count`, then records `u32 size,
"x86\0", payload` - the **PC layout, little-endian, kept on GameCube**.  Each record is an
object of elements:

    vertices x 36   f32 x y z, f32 nx ny nz, f32 u v, u8 r g b a
    u32 corners, u8, u16 length, "<file>.gmt^GameMaterial:<name>\0", u16[corners]   (a strip)

The header's counts are byte-packed and not decoded; the reader finds an element by its run
of unit-normal vertices and checks the index block after it.  Bat museum: 312 objects, 387
elements, 86,384 strip triangles; the Batcycle's nine elements agree with their normals at
0.93-1.00.  Through the rip: 294 models / 54,995 triangles / 206 textured from that one level.

`.tsd`: `u32 size, u32 1, u32 1, char[256] source path`, big-endian `u32 width, height,
kind` at +268, pixels at +300 in **PC layouts** - linear DXT1 (0x17, 339 of 421), RGBA8
(0x09), 4-bit indices low-nibble-first with a 16-entry little-endian RGB565 palette 4 bytes
after them (0x07 / 0x0a; the ones with more data behind them keep mips and are skipped).  The
GX-tiled reading gives noise; the linear DXT1 reading gives the loading screen's display
cases.  Pictures are named after the materials that use them (`bikeBody2` ->
`bikebody2.tsd`), which is how the plugin binds them.

## Donald Duck: Goin' Quackers and Tarzan Untamed use the same archive

27 and 3 `.fat`/`.000` pairs (`gamedata/binary/big/Azt/Ac_Bonus.fat` ...), root path `/ar...`
rather than `/gamedata/`, the same LZO blocks, `.tsd` pictures (decoded on their own now, as
are Vengeance's) and a `3d/gli/geoobj.bin` a level whose records are **not** Sin Tzu's: the
vertex run is 24-byte **big-endian** `f32 x y z, f32 a b c` (a, b, c not unit - Vengeance's
24-byte records again) behind a byte-packed header, followed by `u16` index data.  Four discs
share that older layout (Donald Duck, Tarzan, Vengeance's `.flt`, and likely more Ubisoft
Montreal titles of 2000-2002); reading it is the next step here.

## Open

Vengeance's `.flt` flat files (`mac` header, `^VisualMaterial:` / `^GameMaterial:` names)
unpack through the same archive but carry 24-byte vertex records without unit normals - a
different, older layout still to read.  Sin Tzu's `superobjects/` placements and the
`gamematerial.bin` -> `visualmaterial.bin` chain (for the materials whose picture is not
named after them) are also unread.
