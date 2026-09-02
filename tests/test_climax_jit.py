"""The compiled decoder must be the same decoder.

LZ decoding is inherently serial - every match copies from output just produced - so there is
nothing here for threads or a GPU.  What it responds to is compilation: a 98 MB stream took
minutes as a Python loop, which is why sweeping decoder variants against real data was too
expensive to be practical, and why that codec ended up parked.

A faster decoder that disagrees with the reference is worse than no decoder, so these tests
compare the two byte for byte rather than merely checking the fast one runs.
"""

from __future__ import annotations

import numpy as np
import pytest

from gcrip.formats import climax_bad as cb


def _reference(data: bytes, limit: int) -> bytes:
    """The original pure-Python walk, kept here as the thing to agree with."""
    ring = bytearray(cb.RING)
    r = cb.RING - cb.MAX_MATCH
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
            r = (r + 1) % cb.RING
        else:
            if i + 2 > n:
                break
            lo, hi = data[i], data[i + 1]
            i += 2
            pos = lo | ((hi & 0xF0) << 4)
            for k in range((hi & 0x0F) + cb.THRESHOLD + 1):
                c = ring[(pos + k) % cb.RING]
                out.append(c)
                ring[r] = c
                r = (r + 1) % cb.RING
    return bytes(out)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_compiled_output_is_byte_identical_to_the_reference(seed):
    """Random bytes exercise both opcode paths and every ring wrap."""
    data = bytes(np.random.default_rng(seed).integers(0, 256, 1 << 17, dtype=np.uint8))
    limit = cb.output_limit(len(data))
    assert cb.decompress(data, limit) == _reference(data, limit)


def test_small_inputs_take_the_python_path_and_still_agree():
    """Below _JIT_MIN the call overhead outweighs the win, so the reference runs - and the two
    must not disagree at the boundary either."""
    data = bytes(np.random.default_rng(9).integers(0, 256, 4096, dtype=np.uint8))
    limit = cb.output_limit(len(data))
    assert len(data) < cb._JIT_MIN
    assert cb.decompress(data, limit) == _reference(data, limit)


def test_the_limit_is_still_honoured_by_the_compiled_path():
    data = bytes(np.random.default_rng(11).integers(0, 256, 1 << 17, dtype=np.uint8))
    out = cb.decompress(data, 1000)
    assert len(out) >= 1000, "the loop tests the limit before emitting, so it may overshoot once"
    assert len(out) <= 1000 + cb.MAX_MATCH
    assert cb.hit_limit(out, len(data), 1000)


def test_reference_path_survives_numba_being_absent(monkeypatch):
    """numba is optional; the pure-Python walk stays the reference implementation."""
    data = bytes(np.random.default_rng(13).integers(0, 256, 1 << 17, dtype=np.uint8))
    limit = cb.output_limit(len(data))
    fast = cb.decompress(data, limit)
    monkeypatch.setattr(cb, "_decompress_fast", None)
    assert cb.decompress(data, limit) == fast
