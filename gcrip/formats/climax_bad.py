"""Climax `.bad` archives - ATV: Quad Power Racing 2, Hot Wheels World Race, The Italian Job.

Each of the three discs is **one `.bad` plus video and audio**, so the archive is the whole
game: 94, 130 and 76 MB.  The payload is ring-buffer LZSS - Okumura's classic, 4096-byte
window, 18-byte maximum match, flag byte read **low bit first** with a set bit meaning one
literal byte and a clear bit a two-byte match::

    lo = data[i], hi = data[i + 1]
    position = lo | ((hi & 0xf0) << 4)      absolute in the ring, not a distance
    length   = (hi & 0x0f) + 3

The ring starts zero-filled, and that is checked rather than assumed: matches early in the
stream do reach into the untouched ring, and with a zero fill ATV's header reads as the clean
big-endian sequence 31, 48, 0, 8, 16, 75, 643, while Okumura's traditional space fill turns
those same words into runs of 0x20.

**The build tag in the old notes was a misreading of this stream.**  ``CUBAN 1._02`` is not a
tag with an underscore in it: the ``_`` is byte 0x5f, the *flag byte* that follows the first
eight literals, and the text is ``CUBAN 1.02``.  A header sampled without decompressing it
shows the compressor's control bytes interleaved with the data.

## Where the stream starts

A file is a run of ``u32 kind, u32 count`` headers.  The stream begins at the first header
whose payload starts with a flag byte of all literals, which is what every stream must open
with while the ring is still empty:

* ATV and The Italian Job put it first, so the stream is at +8 (``ff`` then ``CUBAN 1.`` /
  ``BOG 1.01``).
* Hot Wheels has a 728-byte uncompressed block in front, so its stream is at +744 (``ff`` then
  ``//`` and a comment).  Its tail carries a second one.

The second header word is not a payload length - on ATV it measures a block of plain game text
at the very end of the file - so it is not used to bound the walk.
"""

from __future__ import annotations

import struct

import numpy as np

RING = 4096
MAX_MATCH = 18
THRESHOLD = 2
ALL_LITERALS = 0xFF
HEADER = 8
MAX_SKIPS = 8
#: below this the JIT's call overhead outweighs the win
_JIT_MIN = 1 << 16
#: A flag byte covers eight items and a match costs two input bytes for up to 18 output, so a
#: stream cannot expand by more than 18*8/(1+16) - call it nine.  The old flat 1<<28 default
#: silently truncated ATV: its 98.8 MB stream stopped at exactly 268,435,466 bytes, which is
#: the cap plus one match, and the tail of the archive was simply lost with nothing to say so.
MAX_EXPANSION = 9
#: bound on what one member may cost in memory, whatever the arithmetic above allows
LIMIT_CEILING = 1 << 30
DEFAULT_LIMIT = 1 << 28


def output_limit(size: int) -> int:
    """How much output to allow for `size` compressed bytes."""
    return min(LIMIT_CEILING, max(DEFAULT_LIMIT, size * MAX_EXPANSION))


def _decompress_core(data, out, ring, limit, ring_size, max_match, threshold):
    """The ring-buffer walk, written so numba can compile it.

    LZ decoding is inherently serial - every match copies from output the decoder has just
    produced - so there is nothing here for threads or a GPU to do.  What it does respond to is
    being compiled: a 98 MB stream took minutes as a Python loop, which is why sweeping decoder
    variants against real data was too expensive to be practical.
    """
    r = ring_size - max_match
    flags = 0
    i = 0
    written = 0
    n = len(data)
    while i < n and written < limit:
        flags >>= 1
        if not flags & 0x100:
            flags = data[i] | 0xFF00
            i += 1
            if i >= n:
                break
        if flags & 1:
            c = data[i]
            i += 1
            out[written] = c
            written += 1
            ring[r] = c
            r = (r + 1) % ring_size
        else:
            if i + 2 > n:
                break
            lo = data[i]
            hi = data[i + 1]
            i += 2
            pos = lo | ((hi & 0xF0) << 4)
            for k in range((hi & 0x0F) + threshold + 1):
                c = ring[(pos + k) % ring_size]
                out[written] = c
                written += 1
                ring[r] = c
                r = (r + 1) % ring_size
    return written


try:  # numba is optional: the pure-Python path stays the reference implementation
    from numba import njit as _njit

    _decompress_fast = _njit(cache=True, nogil=True)(_decompress_core)
except Exception:  # noqa: BLE001
    _decompress_fast = None


def decompress(data: bytes, limit: int | None = None) -> bytes:
    """Inflate the stream.  ``limit`` defaults to :func:`output_limit` for the input's size.

    A caller that needs to know whether the result is complete should compare its length
    against the limit - see :func:`hit_limit`.
    """
    if limit is None:
        limit = output_limit(len(data))
    if _decompress_fast is not None and len(data) > _JIT_MIN:
        src = np.frombuffer(data, np.uint8)
        # +MAX_MATCH so the last match cannot run past the buffer; the limit still bounds it
        buf = np.zeros(limit + MAX_MATCH, np.uint8)
        ring_arr = np.zeros(RING, np.uint8)
        written = _decompress_fast(src, buf, ring_arr, limit, RING, MAX_MATCH, THRESHOLD)
        return buf[:written].tobytes()
    ring = bytearray(RING)
    r = RING - MAX_MATCH
    out = bytearray()
    flags = 0
    i = 0
    n = len(data)
    while i < n and len(out) < limit:
        flags >>= 1
        if not flags & 0x100:
            flags = data[i] | 0xFF00
            i += 1
            if i >= n:
                break
        if flags & 1:
            c = data[i]
            i += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) % RING
        else:
            if i + 2 > n:
                break
            lo, hi = data[i], data[i + 1]
            i += 2
            pos = lo | ((hi & 0xF0) << 4)
            for k in range((hi & 0x0F) + THRESHOLD + 1):
                c = ring[(pos + k) % RING]
                out.append(c)
                ring[r] = c
                r = (r + 1) % RING
    return bytes(out)


def hit_limit(out: bytes, size: int, limit: int | None = None) -> bool:
    """True when the output stopped because it ran out of room rather than out of input.

    The loop tests the limit before emitting, so a truncated result overshoots it by up to one
    match - which is why this is a `>=` against the limit and not an equality.
    """
    if limit is None:
        limit = output_limit(size)
    return len(out) >= limit


def stream_start(data: bytes) -> int | None:
    """Offset of the first LZSS stream, walking the ``u32 kind, u32 count`` headers."""
    at = 0
    for _ in range(MAX_SKIPS):
        if at + HEADER >= len(data):
            return None
        _kind, count = struct.unpack_from(">2I", data, at)
        if data[at + HEADER] == ALL_LITERALS:
            return at + HEADER
        if not 0 < count < len(data) - at:
            return None
        at += HEADER + count
    return None


def looks_like(head: bytes) -> bool:
    """Cheap plausibility on the 64 bytes ``classify`` sniffs.

    It deliberately does **not** call :func:`stream_start`: Hot Wheels' stream begins at +744,
    past the end of the sniffed head, so a detector that insisted on finding it would refuse
    the largest of the three archives.  The extension carries the claim and
    :func:`stream_start` does the real check when the whole file is in hand.
    """
    if len(head) < HEADER + 1:
        return False
    kind, count = struct.unpack_from(">2I", head, 0)
    return kind <= 2 and 0 < count < (1 << 27)
