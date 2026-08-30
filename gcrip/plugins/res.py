"""``res\\n`` resource files as a container (gcrip.formats.res): Digimon Rumble Arena 2,
Lemony Snicket's A Series of Unfortunate Events and Samurai Jack: The Shadow of Aku all ship
their levels, menus and audio in this middleware format.  Splitting a file into its tagged
sections gives the structure scanner small, labelled blobs (``surf``, ``node``, ``sdta`` hold
the geometry; ``wave`` / ``musc`` are audio)."""

from __future__ import annotations

from gcrip.formats import res

NAME = "res"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".res") and res.is_res(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return res.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
