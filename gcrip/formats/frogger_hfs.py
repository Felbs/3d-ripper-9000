"""Frogger: Ancient Shadow's ``gamedata.bin`` - an ``hfs\\n`` archive, whole.

The whole game is one 197,959,680-byte file and the disc produces four models.  An earlier pass
read the first directory block and left the rest open: *"this header describes one block of a
198 MB file and there are more; whether they chain or are listed somewhere is not yet known."*

They are a contiguous table at the front of the file, one block every 2,048 bytes.  Little-endian::

    +0   char magic[4]     "hfs\\n"
    +4   u32  span         bytes of member data this block covers
    +8   u32  count        members in this block
    +12  u32  data offset  absolute, where this block's members begin
    +16  count x 8 bytes:
             u32  sector | 0x01000000   member start, in 2,048-byte sectors from `data offset`
             u32  size                  member length in bytes

**Three numbers close the archive, and each is exact:**

* the directory is **67 blocks**, and ``67 * 2048 = 137,216`` is exactly the data offset the
  first block declares - so the table ends precisely where the data begins;
* the blocks **chain by span**: block 0's data offset plus its span, ``137,216 + 106,496 =
  243,712``, is block 1's data offset, and so on down all 67;
* the spans sum to **197,822,464**, and ``137,216 + 197,822,464 = 197,959,680`` - the file
  length, to the byte.

That accounts for **4,195 members**.

Every one of them is ``PRS1`` and compressed: measuring 355 of them gives entropy 6.13 to 8.0,
with none stored, so there is no plaintext on this disc to decode the codec against.  ``PRS1``
is not Sega's PRS - ``gcrip.formats.prs`` rejects it at every plausible offset with
*back-reference before start* - and 48 LZSS variants have already failed against it.  That codec
is the remaining work; the archive around it is finished.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.identities import Identity

MAGIC = b"hfs\n"
#: the directory is a run of these, one every 2,048 bytes
BLOCK = 2048
HEADER = 16
ENTRY = 8
SECTOR = 2048
#: the high byte every sector word carries
SECTOR_FLAG = 0x01000000
SECTOR_MASK = 0x00FFFFFF
MAX_BLOCKS = 1 << 16
MAX_COUNT = 1 << 16
#: what a member opens with
MEMBER_MAGIC = b"PRS1"
#: and its header: magic, u32 unpacked size, u32 packed size (== the directory's), payload
MEMBER_HEADER = 12
MEMBER_UNPACKED_AT = 4
MEMBER_PACKED_AT = 8


def member_sizes(data: bytes, m: Member) -> tuple[int, int] | None:
    """(unpacked, packed) from the member's own header, or None if it is not PRS1."""
    if m.offset + MEMBER_HEADER > len(data) or data[m.offset : m.offset + 4] != MEMBER_MAGIC:
        return None
    return struct.unpack_from("<2I", data, m.offset + MEMBER_UNPACKED_AT)


def _members_declare_their_sizes(data: bytes):
    found = members(data)
    checked = held = 0
    for m in found:
        if m.offset + m.size > len(data):
            continue
        got = member_sizes(data, m)
        if got is None:
            continue
        checked += 1
        unpacked, packed = got
        held += packed == m.size and unpacked >= packed
    if not checked:
        return None, "no PRS1 member inside the data"
    return held == checked, f"{held} of {checked} members: +8 == directory size and +4 >= +8"


@dataclass(frozen=True)
class Member:
    block: int
    index: int
    offset: int
    size: int


@dataclass(frozen=True)
class Block:
    offset: int
    span: int
    count: int
    data_at: int


def is_hfs(head: bytes) -> bool:
    return head[:4] == MAGIC and len(head) >= HEADER


def blocks(data: bytes) -> list[Block]:
    """The directory: every 2,048-byte block until one stops carrying the magic."""
    out: list[Block] = []
    at = 0
    n = len(data)
    while at + HEADER <= n and len(out) < MAX_BLOCKS:
        if data[at : at + 4] != MAGIC:
            break
        _m, span, count, data_at = struct.unpack_from("<4s3I", data, at)
        if count > MAX_COUNT or at + HEADER + count * ENTRY > at + BLOCK:
            break
        out.append(Block(at, span, count, data_at))
        at += BLOCK
    return out


def members(data: bytes) -> list[Member]:
    out: list[Member] = []
    for b in blocks(data):
        for i in range(b.count):
            at = b.offset + HEADER + i * ENTRY
            sector, size = struct.unpack_from("<2I", data, at)
            offset = (sector & SECTOR_MASK) * SECTOR + b.data_at
            out.append(Member(b.offset // BLOCK, i, offset, size))
    return out


def directory_bytes(data: bytes) -> int:
    return len(blocks(data)) * BLOCK


# -- identities ---------------------------------------------------------------------------


def _table_ends_where_the_data_starts(data: bytes):
    got = blocks(data)
    if not got:
        return None, "not an hfs archive"
    return len(got) * BLOCK == got[0].data_at, (
        f"{len(got)} blocks x {BLOCK} = {len(got) * BLOCK} against a declared "
        f"data offset of {got[0].data_at}"
    )


def _blocks_chain_by_span(data: bytes):
    got = blocks(data)
    if len(got) < 2:
        return None, "one block or none"
    ok = sum(1 for a, b in zip(got, got[1:]) if a.data_at + a.span == b.data_at)
    return ok == len(got) - 1, f"{ok} of {len(got) - 1} blocks reach the next one's data"


def _spans_and_table_account_for_the_file(data: bytes, total: int | None = None):
    got = blocks(data)
    if not got:
        return None, "not an hfs archive"
    size = total if total is not None else len(data)
    reach = len(got) * BLOCK + sum(b.span for b in got)
    return reach == size, f"{reach} accounted for against a file of {size}"


IDENTITIES = [
    Identity(
        "a member's header repeats its size and declares the unpacked one",
        "u32 at +8 == the directory's size, and u32 at +4 >= it",
        _members_declare_their_sizes,
    ),
    Identity(
        "the directory ends where the data begins",
        "blocks * 2048 == the data offset the first block declares",
        _table_ends_where_the_data_starts,
    ),
    Identity(
        "the blocks chain by their spans",
        "a block's data offset plus its span is the next block's data offset",
        _blocks_chain_by_span,
    ),
    Identity(
        "the table and the spans are the whole file",
        "blocks * 2048 + the sum of the spans == the file length",
        _spans_and_table_account_for_the_file,
    ),
]
