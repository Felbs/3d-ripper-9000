"""THQ ``pack`` archives (gcrip.formats.thq_pack) as a container: ``.PAK`` files whose members
are named ``.rad`` objects or further packs (Avatar: The Last Airbender, Jimmy Neutron, Alien
Hominid, Darkened Skye, Future Tactics).  The ``.rad`` object format itself is not decoded
yet, so this only gives the structure scanner named, per-level blobs to work on."""

from __future__ import annotations

from gcrip.formats import thq_pack

NAME = "thq_pack"


def is_container(name: str, head: bytes) -> bool:
    return thq_pack.is_pack(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return thq_pack.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
