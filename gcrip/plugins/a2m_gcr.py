"""Artificial Mind & Movement's ``.gcr`` level archives (Scooby-Doo! Mystery Mayhem) as a
container: the RenderWare world and clump records come out as ``.bsp`` / ``.dff`` members for
``plugins/renderware.py``, which finds the level's ``TEXDIC_*.txd`` beside the archive
(gcrip.formats.a2m_gcr)."""

from __future__ import annotations

from gcrip.formats import a2m_gcr
from ripcore.scene import Scene

NAME = "a2m_gcr"


def detect(path: str, head: bytes, size: int) -> bool:
    """A container only; both of these exist so the plugin is registered at all."""
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    return []


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".gcr") and a2m_gcr.is_gcr(head, 1 << 31)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return a2m_gcr.expand(data)
