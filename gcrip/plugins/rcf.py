"""Radical RCF archives (``RADCORE`` / ``ATG CORE CEMENT LIBRARY``) as a container: members
are walked like any archive, so the Pure3D plugin sees the ``.p3d`` files inside."""

from __future__ import annotations

from gcrip.formats import rcf

NAME = "rcf"


def is_container(name: str, head: bytes) -> bool:
    return rcf.is_rcf(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for m in rcf.members(data):
        try:
            out.append((m.name, rcf.read(data, m)))
        except Exception:  # noqa: BLE001
            continue
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
