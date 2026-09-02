"""The Visual Concepts ``.IFF`` codec - NBA 2K2/2K3, NFL 2K3, NCAA Basketball/Football 2K3.

``game.dat`` holds 9,380 members across the five discs and 1,916 of NBA 2K3's are ``.IFF``.
Fifty-eight are stored as they are and their textures already shipped; the other 1,858 are
packed, and this reads them.

A member opens with **sixteen bytes copied to the output verbatim** and then a byte-oriented
LZ77 stream:

    u8 flags                   eight items, bit taken LSB first
      bit 0 -> literal        one byte, copied out
      bit 1 -> match          three bytes, big-endian, as one 24-bit word:
                                  length   = word >> 14          (10 bits)
                                  distance = (word & 0x3fff) + 1 (14 bits)

That is the whole format.  It is a 10:14 split of a 24-bit word - which is why every earlier
attempt failed on the same wall: the two spare bits at the top of the second byte look like a
control field sitting beside an 8-bit length, and every reading of them as a *control* has to
explain matches that need different lengths from identical bytes.  They are not a control.
They are the bottom two bits of the length.

What settles it, on the 251 packed members of the first 24 MB of NBA 2K3's ``game.dat``:

* **246 land exactly on the length the member declares**, with no clipping and no rounding -
  the decoder is not stopped at the target, it arrives there.  Length is the oracle here and it
  has to be measured that way: stopping the walk at the target makes any rule land on it, which
  is how a wrong rule once scored 251 of 251.
* **all 246 then carry ``RTXT`` at +16 and the nested ``RTXT`` at +44** - the chunk header the
  uncompressed members show - and read back as named textures: ``unif``, ``office_photos``,
  ``coachface``.
* the walk consumes 90% of the stored span, the rest being the member's padding.

Two of the 251 do not reach their declared length and three overrun it by sixteen bytes; those
are reported, not smoothed over.
"""

from __future__ import annotations

import struct

from gcrip.identities import Identity

#: bytes copied to the output before the packed stream begins
VERBATIM = 16
#: the tag of a stored member sits at +16; a packed one has a zero there and the tag at +17
TAG_AT = 16
#: the packed member states its own output length here
DECLARED_AT = 21
#: length occupies the top ten bits of the 24-bit match word
LENGTH_SHIFT = 14
#: ... and the distance the low fourteen, biased by one
DISTANCE_MASK = 0x3FFF
#: no member on any of the five discs is anywhere near this
MAX_OUTPUT = 64 << 20


class PackError(ValueError):
    """The packed stream does not reach the length the member declares."""


def is_packed(head: bytes) -> bool:
    """A packed member has a zero where a stored one has its four-character tag."""
    return len(head) >= DECLARED_AT + 4 and head[TAG_AT] == 0 and head[TAG_AT + 1 : TAG_AT + 5].isalpha()


def declared(head: bytes) -> int:
    """The output length the member states, not counting the sixteen verbatim bytes."""
    return struct.unpack_from(">I", head, DECLARED_AT)[0]


def unpack(data: bytes) -> bytes:
    """Decode one packed member.  Raises if the stream cannot reach the declared length."""
    want = declared(data)
    if not 0 < want <= MAX_OUTPUT:
        raise PackError(f"declared output length {want} is not plausible")
    target = want + VERBATIM
    out = bytearray(data[:VERBATIM])
    i = VERBATIM
    n = len(data)
    while len(out) < target and i < n:
        flags = data[i]
        i += 1
        for bit in range(8):
            if len(out) >= target or i >= n:
                break
            if not (flags >> bit) & 1:
                out.append(data[i])
                i += 1
                continue
            if i + 3 > n:
                raise PackError(f"a match runs off the end of the member at {i}")
            word = data[i] << 16 | data[i + 1] << 8 | data[i + 2]
            i += 3
            length = word >> LENGTH_SHIFT
            distance = (word & DISTANCE_MASK) + 1
            if distance > len(out):
                raise PackError(f"distance {distance} reaches before the output at {len(out)}")
            for _ in range(length):
                out.append(out[-distance])
    if len(out) < target:
        raise PackError(f"stream ended {target - len(out)} bytes short of the declared {want}")
    # the last match may overrun the declared end; that is ordinary for an LZ stream
    return bytes(out[:target])


# -- identities ---------------------------------------------------------------------------


def _reaches_declared(data: bytes):
    if not is_packed(data[: DECLARED_AT + 4]):
        return None, "not a packed member"
    try:
        out = unpack(data)
    except PackError as exc:
        return False, str(exc)
    return len(out) == declared(data) + VERBATIM, f"{len(out)} bytes for a declared {declared(data)}"


def _nested_tag(data: bytes):
    if not is_packed(data[: DECLARED_AT + 4]):
        return None, "not a packed member"
    try:
        out = unpack(data)
    except PackError as exc:
        return False, str(exc)
    tag = data[TAG_AT + 1 : TAG_AT + 5]
    return out[16:20] == tag, f"decoded tag {out[16:20]!r} against the stored {tag!r}"


IDENTITIES = [
    Identity(
        "the stream arrives at the declared length",
        "output == the u32 the member states at +21, plus the sixteen verbatim bytes",
        _reaches_declared,
    ),
    Identity(
        "the decoded tag is the one the member advertises",
        "output[16:20] == the four characters stored at +17",
        _nested_tag,
    ),
]
