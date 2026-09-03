"""The gxscan salvage pass: re-walking the span a rejected chain claimed.

The walk in `candidate_lists` is greedy - an accepted chain claims the bytes it covers - and
one accidental chain can bury every real list behind it.  On TimeSplitters 2's
`ob__chrs__chr128.gcr` a spurious 1,397-vertex chain at offset 254 covers 35 KB and hides 562
genuine strips; the file scanned to 36 triangles.  The salvage pass re-walks such spans with the
skip off, ranks the chains by how much they look like real lists, and scores only the best few.

Benchmarked over 22 files from zero-model discs: 5,738 triangles became 23,412, with
TimeSplitters at 16,897 and Conflict: Desert Storm 93 -> 877.  Gated on the first pass having
found at least one mesh, because the sixteen files that produced none gained nothing and paid
50-100% more time without the gate.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip import gxscan


def strip(indices, stride=2):
    out = bytearray([0x98]) + struct.pack(">H", len(indices))
    for i in indices:
        out += struct.pack(">H", i)[-stride:] if stride <= 2 else struct.pack(">H", i) + bytes(stride - 2)
    return bytes(out)


def make_real_lists(n_verts: int = 64, n_strips: int = 12) -> bytes:
    """A run of strips over one small index array, stride 2, zero-padded between."""
    body = bytearray()
    for s in range(n_strips):
        base = (s * 5) % (n_verts - 8)
        body += strip([base + k for k in range(8)]) + bytes(3)
    return bytes(body)


def make_positions(n_verts: int = 64) -> bytes:
    rng = np.random.default_rng(5)
    return rng.uniform(-3, 3, (n_verts, 3)).astype(">f4").tobytes()


def test_within_walks_every_start_in_the_span_with_the_skip_off():
    lists = make_real_lists()
    blob = gxscan._Blob(lists)
    greedy = gxscan.candidate_lists(lists, blob=blob)
    confined = gxscan.candidate_lists(lists, blob=blob, within=[(0, len(lists))])
    assert len(confined) >= len(greedy)


def test_salvage_rank_prefers_many_primitives_with_small_indices():
    lists = make_real_lists()
    blob = gxscan._Blob(lists)
    groups = gxscan.candidate_lists(lists, blob=blob, within=[(0, len(lists))])
    ranked = sorted(groups, key=lambda g: -gxscan._salvage_rank(blob, g[0]))
    best = ranked[0][0]
    assert len(best.prims) >= 2
    assert gxscan._salvage_rank(blob, best) >= gxscan._salvage_rank(blob, ranked[-1][0])


def test_the_pass_only_runs_when_the_first_pass_found_something():
    """A blob of noise must not pay for a salvage pass.  Random bytes hold accidental chains
    that get rejected; with nothing accepted, `wasted` is ignored."""
    rng = np.random.default_rng(9)
    noise = bytes(rng.integers(0, 256, 1 << 16, dtype=np.uint8))
    assert gxscan.scan_blob(noise, budget=20.0) == []
