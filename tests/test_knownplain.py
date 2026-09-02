"""Known-plaintext search: the technique that broke the Tiger Woods codec.

The tests pin the property the whole method rests on - a shared run of at least
``window + stride - 1`` bytes is *certain* to be found - and the thing that makes it useful on
real data, which is that literal runs inside a compressed stream are recovered even though
everything around them is unrecognisable.
"""

from __future__ import annotations

import numpy as np

from gcrip import knownplain


def _noise(n: int, seed: int) -> bytes:
    return bytes(np.random.default_rng(seed).integers(0, 256, n, dtype=np.uint8))


def test_a_verbatim_run_is_found_and_grown_to_its_full_length():
    raw = _noise(4096, 1)
    packed = _noise(500, 2) + raw[1000:1400] + _noise(500, 3)
    idx = knownplain.Index()
    idx.add("ter", raw)
    got = idx.search(packed)
    assert got, "a 400-byte verbatim run was missed"
    best = got[0]
    assert best.length == 400, f"run grown to {best.length}, expected the full 400"
    assert best.target_offset == 500
    assert best.source_offset == 1000


def test_the_guarantee_holds_at_the_stated_minimum():
    """Any shared run of window + stride - 1 must be found, whatever its alignment."""
    idx = knownplain.Index(window=16, stride=16)
    raw = _noise(8192, 4)
    idx.add("src", raw)
    need = idx.window + idx.stride - 1
    for shift in range(idx.stride):
        packed = _noise(64 + shift, 5) + raw[2048 : 2048 + need] + _noise(64, 6)
        assert idx.search(packed, min_run=need), f"missed a {need}-byte run at shift {shift}"


def test_unrelated_data_produces_nothing():
    """Sixteen-byte coincidences do not happen - that is why the window is 16."""
    idx = knownplain.Index()
    idx.add("src", _noise(1 << 16, 7))
    assert idx.search(_noise(1 << 16, 8)) == []


def test_literal_runs_survive_inside_a_compressed_stream():
    """The real shape of the problem: an LZ stream is control bytes and back-references with
    literal runs between, and only the literals are recoverable.  That is exactly what the
    Tiger Woods measurement saw - 435 windows of 2,080, not all of them."""
    rng = np.random.default_rng(9)
    raw = _noise(8192, 10)
    packed = bytearray()
    at = 0
    while at < len(raw) - 64:
        packed += bytes(rng.integers(0, 256, 2, dtype=np.uint8))  # a control pair
        run = int(rng.integers(24, 64))
        packed += raw[at : at + run]  # a literal run
        at += run + int(rng.integers(16, 48))  # ... and a back-reference we cannot see
    idx = knownplain.Index()
    idx.add("raw", raw)
    got = idx.search(bytes(packed))
    assert got, "no literal runs recovered"
    cov = knownplain.coverage(got, len(packed))
    assert 0.2 < cov < 1.0, f"coverage {cov:.2f} - expected partial recovery, not all or nothing"


def test_coverage_counts_each_byte_once():
    raw = _noise(2048, 11)
    packed = raw[:512] + raw[:512]  # the same run twice
    idx = knownplain.Index()
    idx.add("raw", raw)
    got = idx.search(packed)
    assert knownplain.coverage(got, len(packed)) > 0.9


def test_index_reports_its_size():
    idx = knownplain.Index(window=16, stride=16)
    added = idx.add("a", _noise(1600, 12))
    assert added == len(idx) == 100  # 1600 / 16
