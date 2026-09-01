# Frogger: Ancient Shadow - `gamedata.bin` is an `hfs\n` archive (2026-09-01)

The last unexamined disc of cluster 1.  Its 198 MB `files/gamedata.bin` is the whole game, and
the disc produces nothing today.

## The directory reads

Little-endian::

    +0   char magic[4]      "hfs\n"
    +4   u32  span          bytes of member data this block covers
    +8   u32  count         members in this block
    +12  u32  data offset   absolute, where the members begin
    +16  the entries, 8 bytes each:
             u32  sector | 0x01000000     member start, in 2,048-byte sectors from data offset
             u32  size                    member length in bytes

On the first block: `span` 106,496, `count` 8, `data offset` 137,216, and the eight sector
values 0, 9, 11, 19, 24, 32, 37 and 48.  Multiplied by 2,048 and added to the data offset they
land on **137,216, 155,648, 159,744, 176,128, 186,368, 202,752, 212,992 and 235,520** - and a
scan for the member magic finds it at exactly those eight offsets.  **8 of 8**, which is what
says the directory is read correctly rather than plausibly.

`span` is consistent too: 137,216 + 106,496 = 243,712, which is where the ninth member sits.  So
this header describes one block of a 198 MB file and there are more; whether they chain or are
listed somewhere is not yet known.

## The members are `PRS1`, and it is not Sega's PRS

Each member opens::

    +0   char magic[4]   "PRS1"
    +4   u16  tag        differs per member - 'jp', 'ir', '4E', 'uo', 0x10e4, 0x8c26
    +6   u16
    +8   u32  size       the same length the directory gives
    +12  the payload

**How the header length is known**: members 0 and 2 have different sizes (17,207 and 14,482) and
*identical bytes from +12 onwards*, as do members 1 and 3.  Fields that repeat across members of
different lengths are payload, not header - so the header ends at +12 and what I first read as a
checksum and an uncompressed size at +12 and +16 is the start of the compressed data.

The payload is compressed - entropy 7.59 to 7.75 - and opens `ff ff ef 03 18 01 00 fa`.

**`gcrip.formats.prs` rejects it** at every plausible offset (8, 12, 16, 20, 24), always with
*back-reference before start*.  So the `PRS1` tag is not Sega's PRS, whatever it borrowed from
it.  That codec is the remaining work, and it is a session of its own; the archive around it is
solved.
