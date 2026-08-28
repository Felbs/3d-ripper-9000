"""Fallback model plugin: geometry found by structure (gcrip.gxscan) in files no format
plugin claims.  Raw meshes only - the point is coverage: every disc yields what it can,
and the report shows where the models live for a real plugin to follow up."""

from __future__ import annotations

import os
import time

from gcrip import gxscan
from gcrip.formats import generic

NAME = "gx"
FALLBACK = True

MIN_SIZE = 4 << 10
MAX_SIZE = 32 << 20
BUDGET = float(os.environ.get("GCRIP_GX_BUDGET", "45"))  # seconds per file
DISC_BUDGET = float(os.environ.get("GCRIP_GX_DISC_BUDGET", "900"))  # seconds per disc

_disc_deadline: float | None = None


def begin_disc() -> None:
    """Called by the rip before its plugin pass: the scanner gets DISC_BUDGET seconds per
    disc in total, spent on the biggest candidates first (see rip._run_plugins)."""
    global _disc_deadline
    _disc_deadline = time.monotonic() + DISC_BUDGET if DISC_BUDGET > 0 else None


def detect(path: str, head: bytes, size: int) -> bool:
    return MIN_SIZE <= size <= MAX_SIZE and generic.worth_trying(head)


def extract(data: bytes, path: str, src):
    if _disc_deadline is not None and time.monotonic() > _disc_deadline:
        return []  # disc budget spent: silently pass (no row, no error)
    if generic._entropy(data[: 1 << 16]) > 7.5:  # compressed / audio / video
        return []
    budget = BUDGET
    if _disc_deadline is not None:
        budget = max(1.0, min(BUDGET, _disc_deadline - time.monotonic()))
    meshes = gxscan.scan_blob(data, budget=budget)
    if not meshes:
        return []
    return [gxscan.to_scene(os.path.basename(path), meshes)]
