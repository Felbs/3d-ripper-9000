# Asobo `.dgc` - "Internal Cross Technology" (Disney-Pixar Ratatouille)

320 `.dgc` files, disc reports zero models.  Shares the extension with TotemTech (Spirits &
Spells) and Superman's `MDGC0200` and is a third, unrelated engine - the file opens with a plain
banner:

    v1.06.63.01 - Asobo Studio - Internal Cross Technology

## Container

After the banner and zero padding, a directory of **24-byte big-endian records at 0x120**:

    u32 id            4 is commonest (15 of 55) but values run to 1150 - an id or hash,
                      not a small enum
    u32 uncompressed size
    u32 stored size
    u32 block size    0x800 on 38 records, 0 on the 16 raw ones, 0x7000 on the last one
    u8  hash[8]

**55 records** on `SW.DGC`, table 0x120..0x648, payload following immediately with the chunks
back to back in table order.  Stored total 8,706,406 against a 8,710,144-byte file, leaving a
2,130-byte trailer.

**When `uncompressed == stored` the block size is 0 and the chunk is raw.**  That is a clean,
self-checking rule, and it covers **16 of 55 records - 2,539,520 of 8,708,096 bytes, 29% of the
archive - readable with no codec at all.**

*(An earlier pass of this note said 43 records and 26%.  That walk stopped early because it
rejected any id above 64 and any block size other than 0x800/0; both assumptions were wrong -
ids go to 1150 and the final record uses a 0x7000 block.  Numbers here are the corrected ones.)*

Chunk sizes are uniform - 153,600 or 163,840 bytes - which says this is a **paged virtual file
system**, not a directory of individual assets.  A chunk is a page of a larger address space, so
even the raw ones are slices rather than whole files, and the `type` word is probably the page
kind rather than an asset type.

## What is blocking

The codec for the other 32 records.  Raw-chunk entropy runs 5.21 to 7.64, so some pages are
dense data (textures) and some are structured; the packed ones cannot be identified until they
inflate.  Ratios are barely below 1.0 (163,840 -> 163,835 on some records), which is unusual -
that is a codec that mostly fails to compress, so it may be a simple RLE or LZ with a small
window rather than anything sophisticated.

Worth noting before anyone spends a session: because this is a paged file system, cracking the
codec gives an address space, not files.  The asset directory that maps names to pages has still
to be found on top of that.

## The raw pages do hold geometry - but not GX geometry

Checked rather than assumed, since 29% of the archive is readable without the codec.  One raw
page (id 7) carries a **1,478-float big-endian run** - 492 triples, bbox
(-7.94, 0, -9.82)..(0, 5.64, 2.96), span 16.07 with a median step of 0.679, so a span-to-step
ratio of **23.6**.  That is a coherent point set, not noise: real vertex data.

But `gcrip.plugins.gx`, the structure scanner, finds **zero** scenes in that page.  Asobo builds
its own primitives rather than GX display lists, so exposing the raw pages as members would not
produce models through the existing fallback - it would just add ~160 KB blobs to the dump.

That settles the cost: Asobo needs its own mesh reader on top of the codec and the page
directory.  Three separate problems, so it is not a one-session job whatever the raw slice
suggests.


## From `ratsgc_m.elf` (2026-09-03): the resource codec, and why the pages are not the unit

The ELF keeps its symbol table.  `UnPack_Z::DecodeRS(const u8* src, u8* dst)` is the codec the
engine applies to **resources** (`ClassManager_Z::LoadResourceData(BigFileRsc_Z&)`: a resource
record is `u32 offset, u32 size, u32 packed` and its bytes sit at `page + 0x18 + offset`):

    header   u32 LE unpacked size, u32 LE packed size
    stream   u32 BE control word: bits 31..2 are 30 flags, the low 2 bits k pick the split;
             per flag from bit 31: 1 = match, a u16 BE v -> length (v >> (14 - k)) + 3,
             offset (v & (0x3fff >> k)) + 1, copied byte by byte; 0 = one literal byte;
             after 30 flags the next control word; stop when the unpacked size is out

The **page records at 0x120 are not compressed with it**: the "packed" pages (stored two to
forty bytes short of 163,840) open with zeros or with 8-byte repeats that no LZ output could
hold, so the page-level difference is something else - a per-page trailer or a `Pack_Z`
framing (`EncodeRS`, `EncodePacket`) still unread.  Above the pages sits a second table -
16-byte resource entries the `ClassManager_Z` walks by handle - and above that Asobo's own
class serialisation (`Mesh_Z`, `MeshStreamList_Z::SetVtxDesc`), so this remains a full
engine transcription for one disc.  Parked with the codec written down.
