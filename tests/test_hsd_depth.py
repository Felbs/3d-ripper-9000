"""HSD trees must not cost stack frames.

`hsd: RecursionError: maximum recursion depth exceeded` was 30 recorded failures across 8 discs
(bobobo-bo bo-bobo among them).  The parser already guarded cycles - a JOBJ pointing back at
itself - but not depth, and a `child` chain read out of arbitrary bytes can be arbitrarily long.
One bad branch killed the whole file.
"""

from __future__ import annotations

import struct
import sys

import numpy as np

from gcrip.formats import hsd
from gcrip.formats.hsd import Jobj


def _chain(n: int) -> Jobj:
    """A JOBJ chain `n` deep, each joint the single child of the one above."""
    leaf = Jobj(0, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [])
    top = leaf
    for i in range(1, n):
        top = Jobj(i, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [top])
    return top


def test_walk_survives_a_tree_deeper_than_the_recursion_limit():
    depth = sys.getrecursionlimit() * 3
    root = _chain(depth)
    assert sum(1 for _ in root.walk()) == depth


def test_walk_is_depth_first_children_before_siblings():
    a = Jobj(1, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [])
    b = Jobj(2, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [])
    child = Jobj(3, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [])
    a.children.append(child)
    root = Jobj(0, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [a, b])
    assert [j.offset for j in root.walk()] == [0, 1, 3, 2]


def test_the_parse_depth_is_bounded():
    """A real skeleton is tens of joints deep - the cap exists so damaged data truncates one
    branch instead of raising and losing the file."""
    assert hsd.MAX_JOBJ_DEPTH >= 64
    assert hsd.MAX_JOBJ_DEPTH < sys.getrecursionlimit()


# -- and they must not cost gigabytes either -------------------------------------------------


def test_a_vertex_array_is_bounded_by_the_file():
    """`hsd: MemoryError` on Dragon Drive's `sd12_000.dat` stalled a whole shard of the library
    pass for twenty minutes.  The array is padded to one past the largest index a display list
    used, and a mis-read display list makes that number arbitrary - so it has to be bounded by
    what the file could possibly hold, and say so rather than dying in the allocator."""
    import pytest

    size = 0x40
    block = size - hsd.HEADER - 8  # leave room for one root entry
    raw = struct.pack(">5I", size, block, 0, 1, 0) + bytes(size - 20)
    dat = hsd.DatFile(raw)
    reader = hsd.AttrReader(dat)
    attr = hsd.VtxAttr(
        attr=hsd.VA_POS, attr_type=1, comp_cnt=1, comp_type=4, frac=0, stride=12, data=0
    )
    with pytest.raises(hsd.HsdError, match="indexes"):
        reader.array(attr, 1 << 28)
    # a request the file could actually satisfy still works
    assert reader.array(attr, 4).shape == (4, 3)


# -- and a shared subtree must not be walked once per path -----------------------------------


def _diamond(levels: int) -> Jobj:
    """A DAG: at every level both children point at the same subtree.

    The parser rejects a joint that is its own ancestor, so this is not a cycle - and nothing
    stops a file doing it.  Walking paths rather than nodes here is 2**levels.
    """
    node = Jobj(levels, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [])
    for i in range(levels - 1, -1, -1):
        node = Jobj(i, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [node, node])
    return node


def test_a_shared_subtree_is_walked_once_not_once_per_path():
    """One Piece's `l_result_back.dat` hung a library shard here - no error, no output, for
    as long as it was left running."""
    root = _diamond(40)  # 2**40 paths, 41 joints
    seen = [j.offset for j in root.walk()]
    assert len(seen) == 41
    assert len(set(seen)) == 41


def test_world_matrices_terminates_on_a_shared_subtree():
    """Fixing only the walk moved the freeze into world_matrices and turned it into an
    IndexError, because a joint visited twice had its index reassigned underneath a child
    that had already recorded it."""
    root = _diamond(40)
    order, world = hsd.world_matrices([root])
    assert len(order) == len(world) == 41
    assert [j.index for j in order] == list(range(41))
    assert order[0].parent is None
    assert all(j.parent == i - 1 for i, j in enumerate(order) if i)


def test_world_matrices_keeps_depth_first_order_on_an_ordinary_tree():
    a = Jobj(1, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [])
    b = Jobj(2, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [])
    child = Jobj(3, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [])
    a.children.append(child)
    root = Jobj(0, 0, (0, 0, 0), (1, 1, 1), (0, 0, 0), None, [], [a, b])
    order, _ = hsd.world_matrices([root])
    assert [j.offset for j in order] == [0, 1, 3, 2]
