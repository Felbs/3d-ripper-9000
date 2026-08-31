"""Visual Concepts ``DAT`` archives as a container (gcrip.formats.vc_dat): NBA 2K2/2K3,
NFL 2K3 and the two NCAA 2K3 discs each keep the whole game in one 0.8-1.3 GB `game.dat`."""

from __future__ import annotations

from gcrip.formats import vc_dat

NAME = "vc_dat"


def is_container(name: str, head: bytes) -> bool:
    return vc_dat.is_dat(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return vc_dat.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
