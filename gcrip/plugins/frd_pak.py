"""Free Radical ``P4CK`` / ``P5CK`` / ``P8CK`` archives as a container (gcrip.formats.frd_pak):
TimeSplitters 2, TimeSplitters: Future Perfect and Second Sight ship everything in them."""

from __future__ import annotations

from gcrip.formats import frd_pak

NAME = "frd_pak"


def is_container(name: str, head: bytes) -> bool:
    return frd_pak.is_pck(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return frd_pak.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
