"""High Voltage Software ``FSTA`` archives as a container (gcrip.formats.fsta): the ``.jam``
files of The Grim Adventures of Billy & Mandy and Codename: Kids Next Door.  Members come out
as ``<name>.<ext>``, so the ``TPL`` ones land on gcrip's Nintendo texture reader."""

from __future__ import annotations

from gcrip.formats import fsta

NAME = "fsta"


def is_container(name: str, head: bytes) -> bool:
    return fsta.is_fsta(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return fsta.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
