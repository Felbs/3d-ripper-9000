"""``TOC`` ``.wad`` archives as a container (gcrip.formats.toc_wad): Spawn: Armageddon keeps
its whole game in 201 of them.  Members come out as `NAME.TYPE`."""

from __future__ import annotations

from gcrip.formats import toc_wad

NAME = "toc_wad"


def is_container(name: str, head: bytes) -> bool:
    # both variants: Spawn's TOC magic, and The Scorpion King's magic-less inline records
    return toc_wad.is_toc_wad(head) or toc_wad.looks_inline(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return toc_wad.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
