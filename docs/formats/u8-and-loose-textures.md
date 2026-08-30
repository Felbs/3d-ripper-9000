# Nintendo U8 archives and loose RenderWare textures (GameCube, 2026-08-29 night)

Two container / texture gaps closed in one evening; both were found by walking the telemetry
rather than a disc: `batch_results.jsonl` shows which games rip models at 0% textured, and the
per-game `disc_manifest.json` files record the classifier's format guess for every file.

## U8 archives (`gcrip/formats/u8.py`, `gcrip/plugins/u8.py`)

The plain Nintendo directory archive - `55 AA 38 2D` - was classified but never opened.  The
library's manifests show **12 discs carrying 1,414 U8 archives**: Harvest Moon: A Wonderful
Life (446), F-Zero GX (350), Harvest Moon: Another Wonderful Life (278), Swingerz Golf (262),
Ultimate Muscle: Legends vs New Generation (43), One Piece: Treasure Battle (29), and singles
in Army Men RTS, Dragon Drive, Billy Hatcher, Chibi-Robo, Super Monkey Ball 2 and Twilight
Princess.

Layout (big-endian): `u32 magic | u32 root node offset (0x20) | u32 header size | u32 data
offset | 16 zero bytes`, then 12-byte nodes - `u8 type (0 file / 1 directory) | u24 name
offset | u32 data offset or parent index | u32 size or index one past the last child` - and a
NUL-terminated string table right after them.  The root node's size field is the node count.
Directories are a stack while walking, so members come out with full in-archive paths, which
matters because the sibling lookups (a model's texture next to it) key on the folder.

Contents seen: Harvest Moon packs one actor per archive - `arowana.act`, `arowana.gpl`,
`arowana.tpl`, `arowana.skn`, `arowana.anm.arc` (a nested U8) - and 88 of 88 `.tpl` members
parse with the existing TPL reader, so those discs gain textures immediately; `.gpl` (geometry)
and `.skn` (skin) are a new model format and still open.  F-Zero GX's
`vehicle_parts/parts_all.arc.lz` (AVLZ-compressed U8) holds 75 `.gma` + 75 `.fmi` + 46 `.tpl`;
its part `.tpl` members are 32-byte index tables (`00 01 02 ... 1b`) into a shared texture
bank rather than real packs, which is why the 525 custom-part models stay untextured for now.

## Loose RenderWare textures (`gcrip/formats/tga.py`)

MLB SlugFest 2003 / 2004, Outlaw Golf and RedCard 2003 are RenderWare games that ship **no
TXDs at all**: the textures are loose `.dds`, `.tga` and `.tgx` files whose stem is the
material name (checked on SlugFest: 40 of 40 material names matched a file).  `.tgx` is an
ordinary TGA under another extension - 8-bit palettised with a 32-bit colour map, top-down.

`plugins/renderware.py` now falls back to a loose-image index (built once per source, decoded
on demand and cached) after the TXD lookups fail, and `formats/tga.py` reads true-colour,
greyscale and colour-mapped TGAs, RLE or raw, either row order.  MLB SlugFest went from 0 to
**100% of materials textured**, Outlaw Golf from 0 to **92%** (295 scenes / 349k triangles).
The remaining SlugFest misses were `.tgx` files before that extension was added.

## Heavy Iron RWTX naming (same night)

The Incredibles / SpongeBob: The Movie discs ripped 2,498 and 2,206 models at 27% and 15%
textured.  Their textures are all present: each `RWTX/<asset>.RW3` member of the level's
`.HOP` holds one raster, but the raster's INTERNAL name is often the artist's leftover
("temp", "greenrock"), while the model's material names the ASSET (`car_C_Damg_hs`).  The
texture index keyed only on the internal name, so those materials never matched.

`plugins/renderware.py` now also indexes a dictionary that holds exactly one raster under its
own file stem (the existing `_key(path, "")` fallback, previously used only when the raster
name was blank).  Measured on the Incredibles: `HS/hs01.HOP` 226 scenes went from ~0 to
**237 of 239 materials bound (99%)** and `FT/ft02.HOP` to 92%.  The same applies to the other
Heavy Iron discs (SpongeBob: Battle for Bikini Bottom / The Movie, Rise of the Underminer,
Scooby-Doo).
