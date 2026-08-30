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
