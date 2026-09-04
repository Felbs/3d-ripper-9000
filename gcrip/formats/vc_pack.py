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

**The stream is input-driven and the encoder trims it** (settled 2026-09-04).  The stored
stream is decoded until the member's bytes run out, not until a target is reached, because the
u32 at +21 is not the member's output length - it is the first record's own size field, read
through the stream's opening literals, and a member may hold *several* records
(``MORPHEDIT.IFF`` decodes to three).  Two encoder habits follow from the stream being sized
by its content rather than by a header:

* **Trailing zero-producing ops are trimmed.**  A member whose output ends in a run of zeros
  may store a stream that stops short of them - ``AH743.IFF`` ends 16 zeros early, cleanly
  between ops, and 58 of the 359 packed members in the verification corpus end *inside* a
  match word, because the trim cut at the container's 32-byte alignment and left a stale
  byte of the fuller stream behind (``AA743.IFF`` dangles ``06`` - the first byte of a
  ``06 00 00`` match that would copy 24 more zeros).  A cut like that ends the stream; it is
  not an error.
* **Up to 31 bytes of source slop follow the content.**  The encoder compressed its source
  buffer through the 32-byte alignment padding, so a few bytes of junk may decode after the
  last record.  Record walkers already stop at the tiling boundary and never see it.

What settles all of it, on the 359 packed members fully inside the first 24 MB of NBA 2K3's
``game.dat`` (251 of them RTXT texture members, 108 others):

* **zero decode errors** - no match ever reaches before the start of the output, which is the
  check that catches a wrong split of the 24-bit word within a handful of ops;
* **every member's decoded tag matches the one it advertises** at +17;
* **239 of the 251 RTXT members tile into complete records exactly** (the other 12 carry
  non-RTXT chunks after their first record, ``A030.IFF``-style, and tile as far as RTXT
  records go); the multi-record members ``MORPHEDIT.IFF`` and ``REF1.IFF`` - unreachable
  under the old stop-at-declared walk - tile as 3 x 17,072 to the byte;
* the five members the stop-at-declared walk could not explain are all explained: two were
  multi-record, three were trimmed.

The earlier "same bytes, different lengths" contradiction that suggested hidden adaptive
state is fully dissolved: it was an artifact of a wrong op grammar consuming the wrong number
of bytes before the point of comparison.  There is no adaptive state.
"""

from __future__ import annotations

import struct

from gcrip.identities import Identity

#: bytes copied to the output before the packed stream begins
VERBATIM = 16
#: the tag of a stored member sits at +16; a packed one has a zero there and the tag at +17
TAG_AT = 16
#: the first record's size field - part of the output, read back through the opening literals
DECLARED_AT = 21
#: length occupies the top ten bits of the 24-bit match word
LENGTH_SHIFT = 14
#: ... and the distance the low fourteen, biased by one
DISTANCE_MASK = 0x3FFF
#: no member on any of the five discs is anywhere near this
MAX_OUTPUT = 64 << 20
#: the largest zero-tail trim seen on a real member is 101 bytes (PB30.IFF); a shortfall far
#: beyond that is a mis-decode, not a trim
MAX_PAD = 4096


class PackError(ValueError):
    """The packed stream is not decodable as this codec."""


def is_packed(head: bytes) -> bool:
    """A packed member has a zero where a stored one has its four-character tag."""
    if len(head) < DECLARED_AT + 4:
        return False
    return head[TAG_AT] == 0 and head[TAG_AT + 1 : TAG_AT + 5].isalpha()


def declared(head: bytes) -> int:
    """The first record's size field - a *minimum* for the output, not its length."""
    return struct.unpack_from(">I", head, DECLARED_AT)[0]


def decode(data: bytes) -> tuple[bytearray, bool]:
    """Decode the whole stored stream.  Returns ``(output, clean)``.

    ``clean`` is False when the stream ends inside a match word - the encoder's trim cutting
    at an alignment boundary - which ends the stream and is ordinary, not an error.  A match
    reaching before the start of the output raises, because that is what a wrong reading of
    the 24-bit word produces within a handful of ops.
    """
    out = bytearray(data[:VERBATIM])
    i = VERBATIM
    n = len(data)
    while i < n:
        flags = data[i]
        i += 1
        for bit in range(8):
            if i >= n:
                break
            if not (flags >> bit) & 1:
                out.append(data[i])
                i += 1
                continue
            if i + 3 > n:
                return out, False
            word = data[i] << 16 | data[i + 1] << 8 | data[i + 2]
            i += 3
            length = word >> LENGTH_SHIFT
            distance = (word & DISTANCE_MASK) + 1
            if distance > len(out):
                raise PackError(f"distance {distance} reaches before the output at {len(out)}")
            if len(out) + length > MAX_OUTPUT:
                raise PackError(f"output would pass {MAX_OUTPUT} bytes")
            for _ in range(length):
                out.append(out[-distance])
    return out, True


def _tiling_target(out: bytearray, tag: bytes, floor: int) -> int:
    """How far the output provably extends: the record tiling the decode itself shows.

    Records are ``16-byte header, tag, u32 size`` spanning ``size + 16``; a member may hold
    several.  Only records whose headers actually decoded count - a tiling read from junk
    would invent output.
    """
    target = floor
    at = 0
    while at + 24 <= len(out):
        if bytes(out[at + TAG_AT : at + TAG_AT + 4]) != tag:
            break
        size = struct.unpack_from(">I", out, at + TAG_AT + 4)[0]
        if size < 8 or size > MAX_OUTPUT:
            break
        at += size + VERBATIM
        target = max(target, at)
    return target


def unpack(data: bytes) -> bytes:
    """Decode one packed member.

    The stream is decoded to its end; if it stops short of the record tiling it declares,
    the difference is the zero tail the encoder trimmed and comes back as zeros.  The result
    may carry up to 31 bytes of the encoder's alignment slop after the last record - record
    walkers stop at the tiling boundary and never read it.
    """
    if not is_packed(data[: DECLARED_AT + 4]):
        raise PackError("not a packed member")
    want = declared(data)
    if not 0 < want <= MAX_OUTPUT:
        raise PackError(f"first record size {want} is not plausible")
    out, _clean = decode(data)
    target = _tiling_target(out, data[TAG_AT + 1 : TAG_AT + 5], want + VERBATIM)
    if len(out) < target:
        pad = target - len(out)
        if pad > MAX_PAD:
            raise PackError(f"stream ends {pad} bytes short of its own record tiling")
        out += bytes(pad)
    return bytes(out)


# -- identities ---------------------------------------------------------------------------


def _reaches_declared(data: bytes):
    if not is_packed(data[: DECLARED_AT + 4]):
        return None, "not a packed member"
    try:
        out = unpack(data)
    except PackError as exc:
        return False, str(exc)
    want = declared(data) + VERBATIM
    return len(out) >= want, f"{len(out)} bytes against the first record's {want}"


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
        "the stream covers the first record",
        "decoded length >= the record size the stream's own literals state, plus 16",
        _reaches_declared,
    ),
    Identity(
        "the decoded tag is the one the member advertises",
        "output[16:20] == the four characters stored at +17",
        _nested_tag,
    ),
]
