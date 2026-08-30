"""Konami ``KCEO ARCDT`` archives as a container (gcrip.formats.kceo): Evolution Snowboarding's
``.arc``.  Members come out under their real names (``FL_STG21_00.BPX``)."""

from __future__ import annotations

from gcrip.formats import kceo

NAME = "kceo"


def is_container(name: str, head: bytes) -> bool:
    return kceo.is_kceo(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return kceo.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
