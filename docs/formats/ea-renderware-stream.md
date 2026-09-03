# EA's RenderWare stream container (2026-09-03)

EA's RenderWare stream container - Call of Duty: Finest Hour and Harry Potter: Goblet of Fire.

Both discs report almost nothing (21 models and 0) and both are full of files that open as a
RenderWare chunk and then refuse to walk::

    1c 07 00 00   10 03 00 00   ff ff 02 18

`u32 id, u32 size, u32 version` little-endian, with a version stamp of ``0x1802FFFF`` -
RenderWare 3.6 - but the ids are EA's own rather than the stock CLUMP / WORLD / TEXDICT, so
``plugins/renderware.py`` declines the file and nothing else claims it.

The stream walks exactly.  On two files as different as a 591,720-byte level script and a
6,062,378-byte object database, ``at += 12 + size`` covers **every byte and lands on the end**:
554 chunks and 6,411 chunks respectively, with nothing left over.  That is the size identity,
and it is what says the ids are being read correctly.

Three ids carry the structure:

``0x071C``
    the **type table**: `u32 count, name, NUL, 0xBF padding to four` repeated - `RenderTrigger`,
    `WorldLight`, `CAnimPackSelector`, `LevelInfo`, `CPickupSelector`.  One per file, first.
``0x0716``
    an **asset descriptor**: a length-prefixed name, sixteen bytes of identifier, a
    length-prefixed *type* name - `rwID_TEXDICTIONARY`, `rwID_SPLINE` - and the asset's build
    path, `ps:\\cod\\game\\rws\\cod1_22p\\build output\\gamecube\\texture dictionary\\{...}`.
``0x0704`` / ``0x0719``
    the payloads.  495 of the first in the level script; 6,411 of the second in the object
    database, each a small typed record.

The names and types are the point of opening these: a member comes out as
``rwID_TEXDICTIONARY`` or ``rwID_SPLINE`` under the name the game gave it, and whichever plugin
reads that kind gets it.

**What is not here:** mesh geometry.  The two files walked hold 57 splines, one texture
dictionary and an object database, and neither carries a RenderWare chunk with a 3.x stamp
inside it or a single native display-list group.  Call of Duty's meshes are somewhere else on
the disc - its 231 `.rws` (582 MB) are the obvious place, and `docs/formats/rws-is-audio.md`
only measured `.rws` on three other discs.

## Measured

| file | disc | bytes | chunks | assets |
|---|---|---|---|---|
| `level.dff` | Call of Duty: Finest Hour | 591,720 | **554, landing on 591,720** | 58, all `rwID_` typed |
| `GodData.dff` | Call of Duty: Finest Hour | 6,062,378 | 6,411, landing on 6,062,378 | - |

`GodData.dff` walks with the same 12-byte header shape but carries **version 0** rather than a
RenderWare stamp, and holds no asset descriptors - small typed records instead.  It is a related
but distinct container and `is_ea_rws` deliberately does **not** claim it.

## No container plugin, and why

The module ships without one.  The assets `level.dff` declares are 57 splines and one texture
dictionary; emitting them would add thousands of members to the dump and not one triangle.
The value here is that the format is now readable and the ids are named - a plugin follows if
and when a stream turns up carrying geometry.

## Where Call of Duty's geometry is not

Neither file carries a RenderWare chunk with a 3.x stamp inside it, and
`formats/rw_native.py` finds **zero** candidate strip runs in either.  The disc's 57 `.dff`
(118 MB) are level scripts and object databases.  Its **231 `.rws` (582 MB)** are the obvious
next place; `docs/formats/rws-is-audio.md` measured `.rws` on Asterix, Madagascar and Piglet,
not on this disc.


## The Goblet of Fire variant: a sentinel where the size belongs (2026-09-03)

Goblet of Fire's `.str` failed the walk at chunk 1 every time, always with the same reading:
`0x0716` with a "size" of **4,206,559,413**.  The same value, in five different files, at five
different offsets.  That is not a corrupt length - it is `0xFABB00B5`, a **sentinel** meaning
the chunk does not declare one.

Bounding such a chunk by the next stamped header instead closes the format on that disc:

| member | bytes | chunks | ends | assets |
|---|---|---|---|---|
| `{146ED2C8-…}.str` | 7,157,408 | 1,602 | **exact** | 333 |
| `{50F19F5E-…}.str` | 109,888 | 8 | **exact** | 4 |
| `{6F15A79E-…}.str` | 6,720 | 7 | **exact** | 4 |
| `{59969448-…}.str` | 1,120 | 4 | **exact** | 2 |
| `{E72D47F7-…}.str` | 7,345,024 | - | 24 bytes short, on an id that is not one | - |

and Call of Duty's `level.dff` is unchanged at 554 chunks.

The recovery is deliberately narrow: **only** a size that equals the sentinel exactly is
re-derived.  An arbitrary oversized length is still refused outright, because that is a misread
file rather than this variant, and the member that ends 24 bytes short returns nothing rather
than a partial archive.

## What the assets are on that disc, so far

The five members sampled declare `rwID_SEQUENCE` (26) and `rwID_HAVOK_HKX_DATA` (4) - scripts
and physics.  **No geometry type has turned up yet**, and 147 of `data.big`'s 152 members are
still unsampled.
