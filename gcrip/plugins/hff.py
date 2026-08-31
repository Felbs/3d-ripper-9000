"""``HFF`` data files as a container (gcrip.formats.hff): Aquaman: Battle for Atlantis, Casper
and TONKA Rescue Patrol.  There is no directory, so the `PNG` members are carved on their
signature and their `IEND` terminator."""

from __future__ import annotations

from gcrip.formats import hff

NAME = "hff"


def is_container(name: str, head: bytes) -> bool:
    return hff.is_hff(name, head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return hff.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
