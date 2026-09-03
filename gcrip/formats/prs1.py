"""``PRS1`` - the member codec of Hudson's ``hfs`` archives (Frogger: Ancient Shadow; Frogger's
Adventures: The Rescue carries the same members).

Read out of Ancient Shadow's DOL: the loader at 0x800095f8 checks the little-endian magic,
allocates the u32 at +4 (unpacked size), and hands ``src + 12`` and the u32 at +8 (packed
size) to the 84-instruction routine at 0x800094a8 - which is Okumura's LZSS, unchanged:

* a 4,096-byte ring, zeroed, write position starting at 0xFEE;
* a flag byte, consumed LSB-first (the ``| 0xff00`` trick), 1 = literal, 0 = copy;
* a copy is two bytes: ``pos = b1 | ((b2 & 0xf0) << 4)`` is an *absolute ring position*,
  ``length = (b2 & 0x0f) + 3``.

Every earlier attempt at this stream failed for one reason: 48 LZSS variants were tried with
distances relative to the output, and PRS1 addresses the ring absolutely.  Members that do not
open ``PRS1`` are stored (RenderWare audio dictionaries, 0x0809) and the loader copies them.
"""

from __future__ import annotations

import struct

MAGIC = b"PRS1"
HEADER = 12
RING = 4096
RING_START = 0xFEE
THRESHOLD = 2


class Prs1Error(ValueError):
    pass


def is_prs1(head: bytes) -> bool:
    return head[:4] == MAGIC and len(head) >= HEADER


def sizes(member: bytes) -> tuple[int, int]:
    """(unpacked, packed) from the 12-byte header."""
    if not is_prs1(member):
        raise Prs1Error("not a PRS1 member")
    return struct.unpack_from("<2I", member, 4)


def decode(src: bytes, unpacked: int) -> bytes:
    ring = bytearray(RING)
    r = RING_START
    out = bytearray()
    p = 0
    flags = 0
    n = len(src)
    while len(out) < unpacked:
        flags >>= 1
        if not flags & 0x100:
            if p >= n:
                break
            flags = src[p] | 0xFF00
            p += 1
        if flags & 1:
            if p >= n:
                break
            b = src[p]
            p += 1
            out.append(b)
            ring[r] = b
            r = (r + 1) & (RING - 1)
        else:
            if p + 1 >= n:
                break
            pos = src[p] | ((src[p + 1] & 0xF0) << 4)
            count = (src[p + 1] & 0x0F) + THRESHOLD + 1
            p += 2
            for i in range(count):
                b = ring[(pos + i) & (RING - 1)]
                out.append(b)
                ring[r] = b
                r = (r + 1) & (RING - 1)
    if len(out) < unpacked:
        raise Prs1Error(f"stream ended at {len(out)} of {unpacked} bytes")
    return bytes(out[:unpacked])


def unpack(member: bytes) -> bytes:
    """Decode a whole member (header + stream)."""
    unpacked, packed = sizes(member)
    return decode(member[HEADER : HEADER + packed], unpacked)
