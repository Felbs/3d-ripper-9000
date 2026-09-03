"""Yuke's ``.pac`` / ``.tex`` packs (WWE Day of Reckoning, WrestleMania XIX) as containers:
the ``tpl`` entries of a ``.tex`` reach the TPL plugin, the ``ymg`` models wait for a
``YOBJ`` reader (gcrip.formats.yukes_pac)."""

from __future__ import annotations

from gcrip.formats import yukes_pac
from ripcore.scene import Scene

NAME = "yukes_pac"


def detect(path: str, head: bytes, size: int) -> bool:
    """A container only; both of these exist so the plugin is registered at all."""
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    return []


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith((".pac", ".tex")) and yukes_pac.is_pac(head, 1 << 31)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return yukes_pac.expand(data)
