"""Crystal Dynamics ``bigfile.dat`` as a container (gcrip.formats.cd_bigfile): Tomb Raider:
Legend keeps the whole game in one."""

from __future__ import annotations

from gcrip.formats import cd_bigfile

NAME = "cd_bigfile"


def is_container(name: str, head: bytes) -> bool:
    return cd_bigfile.is_bigfile(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for m in cd_bigfile.members(data):
        blob = cd_bigfile.read(data, m)
        if blob:
            out.append((m.name, blob))
    return out


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
