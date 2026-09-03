"""``FSYS`` archives - Pokemon Colosseum and Pokemon XD: Gale of Darkness.

Two discs whose content is almost entirely inside these: **1,852 archives and 350 MB** on
Colosseum, **2,540 and 1,032 MB** on XD.  Both reported nothing at all, because nothing opened
an ``.fsys``.

Big-endian::

    +0    char magic[4]   "FSYS"
    +4    u32 version     0x102 (Colosseum) / 0x201 (XD)
    +8    u32 identifier
    +12   u32 entry count
    +16   u32 flags
    +20   u32 3           how many pointers the table at +24 holds
    +24   u32 -> a three-pointer table
    +32   u32 file length

The three pointers are, in order, the **list of per-entry detail pointers**, the start of the
detail records, and the start of the data.  Two independent sums confirm that reading, on both
versions at once: Colosseum's 157 entries need `96 + 157 * 4 = 724` bytes of pointer list, and
the second pointer is **736** - the same number rounded up to 32.  XD's two entries need
`96 + 8 = 104`, and its second pointer is **112**.  The third pointer equals the first entry's
data offset, and ``+32`` equals the file length exactly (18,069,472 and 131,180,768).

A detail record - 80 bytes on Colosseum, 112 on XD, so the stride is taken from the pointer
list rather than assumed::

    +0    u32 identifier
    +4    u32 data offset
    +8    u32 **unpacked** size
    +20   u32 **stored** size
    +32   u32 kind
    +36   u32 -> the member's name, NUL-terminated

**+8 is the unpacked size and +20 the stored one, not the other way round.**  On an
uncompressed member the two are equal, so the mistake is invisible on exactly the archive you
would check first - ``people_archive.fsys``, where both read 61,743.  It shows up only on a
compressed one, as a "size" larger than the archive containing it.

**Members are named**, which is the point of opening these at all: ``people_archive.fsys``
holds ``sensei_b1``, ``hunter_f_b2``, ``warugaki_b3``, ``jiji_b_b1`` - the game's cast, one
entry each.

A member is stored one of two ways, and the first four bytes say which: an uncompressed member
repeats its own stored size there, and a compressed one begins ``LZSS`` followed by the
unpacked and stored sizes again.  Anything else is refused, so a mis-read table cannot carve
the archive up at invented offsets.

**Almost everything is compressed**, which is the honest limit on this reader: across the 40
largest archives of each disc, Colosseum has 157 stored members (17 MB) against 2,257 ``LZSS``
(143 MB), and XD has none stored at all.  The container is solved; the codec is the gate.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.identities import Identity

MAGIC = b"FSYS"
COUNT_AT = 12
POINTERS_AT = 24
LENGTH_AT = 32
POINTERS = 3
OFFSET_AT = 4
UNPACKED_AT = 8
SIZE_AT = 20
LZSS = b"LZSS"
LZSS_HEADER = 16
KIND_AT = 32
NAME_AT = 36
MIN_DETAIL = 40
MAX_COUNT = 1 << 16
MAX_NAME = 64


@dataclass
class Member:
    name: str
    kind: int
    offset: int
    size: int
    unpacked: int
    compressed: bool


RING_BITS = 12
RING_FILL = 0x00
RING_START = (1 << RING_BITS) - 18
LENGTH_BIAS = 3


def is_fsys(head: bytes) -> bool:
    return head[:4] == MAGIC


def decompress(stream: bytes, want: int) -> bytes | None:
    """The ``LZSS`` payload: Okumura's scheme, 4 KB ring, literals flagged by a set bit.

    A flag byte then eight items, bit taken LSB first; a set bit is a one-byte literal and a
    clear bit is a two-byte match with the window position in twelve bits and the length in
    four, ``(b1 & 0x0f) + 3``.

    Getting here needed a **two-sided** check rather than the obvious one.  Matching the
    declared output length alone is far too weak - eighty parameter sets satisfy it, and the
    four distinct outputs they produce all begin with runs of untouched window fill.  Requiring
    the decoder to consume the stream to its final byte *at the same moment* it reaches the
    declared length cuts that down, and re-compressing the result ranks what is left: real data
    squeezes back to roughly the ratio the file was stored at, noise does not.

    The other thing that misled the first attempt was insisting the first operation be a
    literal, on the grounds that a match cannot reference an empty window.  It can: these files
    open with sixteen zero bytes, and against a zero-filled window a match is exactly what an
    encoder should emit.  That heuristic pointed at the wrong flag polarity for hours.

    ``RING_FILL`` only shows through where a match reads window that nothing has written yet,
    which happens in the first few bytes of a file or not at all; ``0x00`` is used because
    these files start with zeros rather than spaces.
    """
    size = 1 << RING_BITS
    mask = size - 1
    window = bytearray([RING_FILL]) * size
    r = RING_START
    out = bytearray()
    at, n = 0, len(stream)
    while at < n and len(out) < want:
        flags = stream[at]
        at += 1
        for i in range(8):
            if len(out) >= want:
                break
            if (flags >> i) & 1:
                if at >= n:
                    return None
                c = stream[at]
                at += 1
                out.append(c)
                window[r] = c
                r = (r + 1) & mask
                continue
            if at + 2 > n:
                return None
            b0, b1 = stream[at], stream[at + 1]
            at += 2
            pos = ((b1 & 0xF0) << 4) | b0
            for _ in range((b1 & 0x0F) + LENGTH_BIAS):
                c = window[pos & mask]
                pos += 1
                out.append(c)
                window[r] = c
                r = (r + 1) & mask
                if len(out) > want:
                    return None
    return bytes(out) if len(out) == want else None


def _cstr(data: bytes, at: int) -> str:
    end = data.find(b"\x00", at, at + MAX_NAME)
    if end < 0:
        return ""
    return data[at:end].decode("latin-1", "replace")


def members(data: bytes) -> list[Member]:
    if not is_fsys(data[:4]) or len(data) < LENGTH_AT + 4:
        return []
    count = struct.unpack_from(">I", data, COUNT_AT)[0]
    table = struct.unpack_from(">I", data, POINTERS_AT)[0]
    if not (0 < count <= MAX_COUNT) or table + POINTERS * 4 > len(data):
        return []
    pointers = struct.unpack_from(f">{POINTERS}I", data, table)
    if pointers[0] + count * 4 > len(data):
        return []
    details = struct.unpack_from(f">{count}I", data, pointers[0])
    out: list[Member] = []
    for at in details:
        if at + MIN_DETAIL > len(data):
            continue
        offset = struct.unpack_from(">I", data, at + OFFSET_AT)[0]
        unpacked = struct.unpack_from(">I", data, at + UNPACKED_AT)[0]
        size = struct.unpack_from(">I", data, at + SIZE_AT)[0]
        kind = struct.unpack_from(">I", data, at + KIND_AT)[0]
        name_at = struct.unpack_from(">I", data, at + NAME_AT)[0]
        if size == 0 or offset + 4 > len(data) or offset + size > len(data):
            continue
        head = data[offset : offset + 4]
        if head == LZSS:
            compressed = True
        elif struct.unpack_from(">I", data, offset)[0] == size:
            compressed = False
        else:
            continue  # neither shape: the table was read wrong, so claim nothing
        out.append(
            Member(
                _cstr(data, name_at) or f"member{len(out):04d}",
                kind,
                offset,
                size,
                unpacked,
                compressed,
            )
        )
    return out


# -- the models inside a member -------------------------------------------------------------
#
# ``docs/OPEN.md`` recorded XD's members as "f32 model data behind a relocation table" and left
# it as a geometry job.  It is not a new format at all: **a member of kind 15 carries a whole
# HAL sysdolphin archive** - the same ``.dat`` container Melee and Kirby Air Ride use, which
# `gcrip/formats/hsd.py` has read all along.
#
# What hides it is that the archive does not start at the beginning of the member.  It sits
# behind a prefix - 3,680 bytes on Pokemon XD, **64 on Colosseum** - so a reader that checks
# offset zero sees nothing and a reader that assumes one constant offset gets one disc right.
#
# It does not have to be guessed at, because **the member's own first word is the archive's
# file size**, and the sysdolphin header states four more numbers that have to reconcile with
# it:  ``0x20 + data + relocations * 4 + roots * 8 <= file size``, the remainder being the
# string table.  On `laplace` that is 32 + 207,636 + 7,055*4 + 2*8 = 235,904 against a declared
# 235,925 - twenty-one bytes left, which is exactly ``scene_data\0bound_box\0``.
#
# Those two root names are the give-away and they are the same on every model member.

#: the smallest sysdolphin archive worth looking at
MIN_HSD = 0x40


def hsd_offset(data: bytes) -> int | None:
    """Where the embedded sysdolphin archive starts, or ``None``.

    The member's first word states the archive's size; this finds where that size is repeated
    as a header that reconciles, so neither the prefix length nor the disc has to be known.
    """
    if len(data) < HEADER_WORDS:
        return None
    want = struct.unpack_from(">I", data, 0)[0]
    if not MIN_HSD < want <= len(data):
        return None
    key = struct.pack(">I", want)
    at = data.find(key, 4)
    while at >= 0:
        if at % 4 == 0 and at + want <= len(data) and _hsd_reconciles(data, at, want):
            return at
        at = data.find(key, at + 1)
    return None


#: file size, data size, relocation count, root count, extern count
HEADER_WORDS = 20


def _hsd_reconciles(data: bytes, at: int, want: int) -> bool:
    size, block, relocs, roots, externs = struct.unpack_from(">5I", data, at)
    if size != want or not block or not roots + externs:
        return False
    return 0x20 + block + relocs * 4 + (roots + externs) * 8 <= size


def _model_members_carry_an_archive(data: bytes):
    """Every member that decompresses and declares a plausible size holds one."""
    found = members(data)
    if not found:
        return None, "not an FSYS archive"
    checked = held = 0
    for m in found:
        blob = data[m.offset : m.offset + m.size]
        payload = decompress(blob[LZSS_HEADER:], m.unpacked) if m.compressed else blob[4:]
        if payload is None or len(payload) < HEADER_WORDS:
            continue
        want = struct.unpack_from(">I", payload, 0)[0]
        if not MIN_HSD < want <= len(payload):
            continue  # not a model member
        checked += 1
        held += hsd_offset(payload) is not None
    if not checked:
        return None, "no member declares an archive size"
    return held == checked, f"{held} of {checked} members hold a sysdolphin archive"


IDENTITIES = [
    Identity(
        "a model member holds a sysdolphin archive",
        "the member's first word is a file size a reconciling HSD header repeats",
        _model_members_carry_an_archive,
    ),
]
