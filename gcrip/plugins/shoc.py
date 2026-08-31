"""EA ``SHOC`` chunk archives as a container (gcrip.formats.shoc): the ``.hog`` on the four
Tiger Woods PGA Tour discs, which share an extension with Warthog's archives and nothing
else."""

from __future__ import annotations

from gcrip.formats import shoc

NAME = "shoc"


def is_container(name: str, head: bytes) -> bool:
    return shoc.is_shoc(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    seen: dict[str, int] = {}
    for m in shoc.members(data):
        stem = f"{m.kind}_{m.index}"
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        out.append((stem if not n else f"{stem}.{n}", m.data))
    return out


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
