"""HSD trees must not cost stack frames.

`hsd: RecursionError: maximum recursion depth exceeded` was 30 recorded failures across 8 discs
(bobobo-bo bo-bobo among them).  The parser already guarded cycles - a JOBJ pointing back at
itself - but not depth, and a `child` chain read out of arbitrary bytes can be arbitrarily long.
One bad branch killed the whole file.
"""

from __future__ import annotations

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
