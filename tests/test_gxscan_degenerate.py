"""The fallback scanner refuses finds that are not geometry: a mesh whose vertices lie on
a line (Freestyle Street Soccer's `.fab` keyframe columns read as `[0.12, y, 0.12]`) or
whose triangle edges are mostly zero-length (Mat Hoffman `.gcg` and Treyarch stash tables
read through the wrong index stream: 39-100% zero edges).  Before this gate those exports
scored garbage in the quality audit while looking like models in the library.
"""

import numpy as np

from gcrip import gxscan
from tests.test_gxscan import build_blob


def _mesh(pos, tri):
    dl = gxscan.DisplayList(0, 0, 4, [(0x90, len(tri), 0)])
    return gxscan.Mesh(
        dl, 0, 2, 0, "f32", pos.astype(np.float32), np.asarray(tri, np.uint32).reshape(-1), 0.5
    )


def test_a_line_is_not_a_mesh():
    pos = np.stack([np.full(60, 0.12), np.linspace(0, 300, 60), np.full(60, 0.12)], 1)
    tri = np.arange(60).reshape(-1, 3)
    assert gxscan._degenerate(pos, tri)
    assert not gxscan._accept(_mesh(pos, tri))


def test_mostly_zero_length_edges_are_refused():
    rng = np.random.default_rng(1)
    pos = rng.random((40, 3)).astype(np.float32)
    good = rng.integers(0, 40, (30, 3))
    good = good[
        (good[:, 0] != good[:, 1]) & (good[:, 1] != good[:, 2]) & (good[:, 0] != good[:, 2])
    ]
    dup = np.repeat(good[:, :1], 3, 1)  # every corner the same position: all edges zero
    dup[:, 2] = (dup[:, 2] + 1) % 40
    pos[(dup[:, 2])] = pos[dup[:, 0]]  # ... and that corner's position equals the others'
    tri = np.concatenate([good, dup, dup, dup])
    assert gxscan._degenerate(pos, tri)
    assert not gxscan._degenerate(pos, good)


def test_the_synthetic_grid_still_scans():
    data, expected = build_blob()
    (m,) = gxscan.scan_blob(data)
    assert m.triangles == expected
    assert not gxscan._degenerate(m.positions, m.indices)
