"""Krome RKV archives (Ty the Tasmanian Tiger and other Merkury-engine discs) as a
container: the v1 directory sits at the END of the file, so the archive is recognised by
its ``.rkv`` name and validated when expanded (gcrip.formats.rkv)."""

from __future__ import annotations

from gcrip.formats import rkv

NAME = "rkv"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".rkv")


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return [(m.name, data[m.offset : m.offset + m.size]) for m in rkv.members(data)]


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
