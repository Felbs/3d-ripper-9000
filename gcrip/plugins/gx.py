"""Fallback model plugin: geometry found by structure (gcrip.gxscan) in files no format
plugin claims.  Raw meshes only - the point is coverage: every disc yields what it can,
and the report shows where the models live for a real plugin to follow up."""

from __future__ import annotations

import os

from gcrip import gxscan
from gcrip.formats import generic

NAME = "gx"
FALLBACK = True

MIN_SIZE = 4 << 10
MAX_SIZE = 32 << 20
BUDGET = float(os.environ.get("GCRIP_GX_BUDGET", "45"))  # seconds per file


def detect(path: str, head: bytes, size: int) -> bool:
    return MIN_SIZE <= size <= MAX_SIZE and generic.worth_trying(head)


def extract(data: bytes, path: str, src):
    if generic._entropy(data[: 1 << 16]) > 7.5:  # compressed / audio / video
        return []
    meshes = gxscan.scan_blob(data, budget=BUDGET)
    if not meshes:
        return []
    return [gxscan.to_scene(os.path.basename(path), meshes)]
