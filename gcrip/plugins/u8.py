"""Nintendo U8 archives (gcrip.formats.u8) as a container: the plain ``.arc`` directory
format used beside RARC on GameCube discs (Harvest Moon: A Wonderful Life / Another Wonderful
Life, F-Zero GX's ``vehicle_parts/parts_all.arc``, Swingerz Golf, Ultimate Muscle, One Piece:
Treasure Battle).  Members keep their in-archive paths so the format plugins and the sibling
lookups (textures beside models) see the archive's own directory layout."""

from __future__ import annotations

from gcrip.formats import u8

NAME = "u8"


def is_container(name: str, head: bytes) -> bool:
    return u8.is_u8(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return u8.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
