"""A reader must be a pure function of its bytes.

`generic.find_toc` used to stop on a 0.15-**second** deadline and return the best table found so
far.  That made `generic.expand` non-deterministic: the manifest walk named a container's
members, a later fetch under different load produced a different set, and the model died on a
bare KeyError on its own path - 36 recorded examples across 8 discs.

The rule that follows is not "never look at the clock".  It is that anything deciding **what a
file contains** must not, because two runs have to agree.  A declared resource budget on a
speculative scan is a different thing, and is allowed by name.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

#: Plugins permitted to consult the clock, with the reason.  Adding one is a deliberate act.
#:
#: `gx` is the fallback display-list scanner and its budget is a genuine time limit on an
#: expensive search - GCRIP_GX_DISC_BUDGET, seconds per disc.  The consequence is real and worth
#: naming: gx can find different meshes on different runs.  That is tolerable because it names
#: nothing the manifest depends on; `find_toc` was not, because it did.
CLOCK_ALLOWED = {"gx.py"}

CLOCK_CALLS = {"monotonic", "time", "perf_counter", "process_time"}


def _clock_uses(path: pathlib.Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "time"
        and node.attr in CLOCK_CALLS
    ]


@pytest.mark.parametrize(
    "path", sorted(pathlib.Path("gcrip/formats").glob("*.py")), ids=lambda p: p.name
)
def test_readers_do_not_consult_the_clock(path):
    """A format reader decides what a file contains.  Two runs must agree."""
    lines = _clock_uses(path)
    assert not lines, (
        f"{path.name} reads the clock at line(s) {lines}; a reader must be a pure function of "
        "its bytes - see gcrip/formats/generic.py TOC_MAX_WORK for the work-cap pattern"
    )


@pytest.mark.parametrize(
    "path", sorted(pathlib.Path("gcrip/plugins").glob("*.py")), ids=lambda p: p.name
)
def test_only_allowlisted_plugins_consult_the_clock(path):
    lines = _clock_uses(path)
    if path.name in CLOCK_ALLOWED:
        return
    assert not lines, (
        f"{path.name} reads the clock at line(s) {lines}.  If that is a declared resource "
        f"budget rather than a decision about content, add it to CLOCK_ALLOWED with the reason"
    )


def test_the_allowlist_is_still_accurate():
    """An allowlist nobody prunes becomes a blanket exemption."""
    for name in CLOCK_ALLOWED:
        path = pathlib.Path("gcrip/plugins") / name
        assert path.exists(), f"{name} is allowlisted but no longer exists"
        assert _clock_uses(path), f"{name} no longer uses the clock - drop it from CLOCK_ALLOWED"
