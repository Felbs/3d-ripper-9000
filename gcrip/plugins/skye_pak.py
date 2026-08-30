"""Darkened Skye ``PAK`` archives as a container (gcrip.formats.skye_pak): 16 archives holding
255 ``.SKX`` models, emitted under their real names."""

from __future__ import annotations

from gcrip.formats import skye_pak

NAME = "skye_pak"


def is_container(name: str, head: bytes) -> bool:
    return skye_pak.is_pak(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return skye_pak.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
