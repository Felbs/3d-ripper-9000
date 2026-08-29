"""TMNT: Mutant Melee: ``archive.dat`` is one 220 MB blob whose directory is the sibling
``archive.arc`` (gcrip.formats.melee_arc); the members are little-endian RenderWare streams
(clumps, texture dictionaries, animations) plus DDS / ktf images, so the renderware plugin
takes them from here."""

from __future__ import annotations

import re

from gcrip.formats import melee_arc

NAME = "melee"
NEEDS_SIBLING = True

_CONTAINER = re.compile(r"archive\.dat$", re.I)


def is_container(name: str, head: bytes) -> bool:
    return bool(_CONTAINER.search(name))


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return []


def expand_with(data: bytes, name: str, sibling) -> list[tuple[str, bytes]]:
    try:
        arc = sibling("archive.arc")
    except Exception:  # noqa: BLE001
        return []
    if not arc or arc[:8] != melee_arc.MAGIC:
        return []
    return melee_arc.members(arc, data)


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
