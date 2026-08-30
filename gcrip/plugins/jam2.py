"""``JAM2`` archives as a container (gcrip.formats.jam2): Charlie and the Chocolate Factory
keeps 244 MB in 38 of them.  Members come out under `NAME.EXT`, so the `TPL` textures inside
are claimed by the plugin that already reads those."""

from __future__ import annotations

from gcrip.formats import jam2

NAME = "jam2"


def is_container(name: str, head: bytes) -> bool:
    return jam2.is_jam2(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return jam2.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
