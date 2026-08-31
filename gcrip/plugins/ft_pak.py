"""FutureTactics: The Uprising's ``files.pak`` as a container (gcrip.formats.ft_pak): the
whole game in one 143 MB archive with no magic, recognised by its table arithmetic."""

from __future__ import annotations

from gcrip.formats import ft_pak

NAME = "ft_pak"


def is_container(name: str, head: bytes) -> bool:
    return ft_pak.is_ft_pak(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return ft_pak.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
