# Asobo `.dgc` - "Internal Cross Technology" (Disney-Pixar Ratatouille)

320 `.dgc` files, disc reports zero models.  Shares the extension with TotemTech (Spirits &
Spells) and Superman's `MDGC0200` and is a third, unrelated engine - the file opens with a plain
banner:

    v1.06.63.01 - Asobo Studio - Internal Cross Technology

## Container

After the banner and zero padding, a directory of **24-byte big-endian records at 0x120**:

    u32 type          2..63 seen; 4 is the commonest (15 of 43)
    u32 uncompressed size
    u32 stored size
    u32 block size    0x800 when packed, **0 when stored raw**
    u8  hash[8]

The records run to 0x528 on `SW.DGC` (43 of them) and the payload follows immediately, each
chunk stored back to back in table order.

**When `uncompressed == stored` the block size is 0 and the chunk is raw.**  That is a clean,
self-checking rule, and it covers a useful slice: **11 of 43 records, 1,751,040 of 6,830,080
bytes - 26% of the archive is readable with no codec at all.**

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
