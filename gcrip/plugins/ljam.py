"""``LJAM`` archives as a container (gcrip.formats.ljam): Hunter: The Reckoning ships its
whole game in 35 of them.  Members come out under their tree path, so the `TPL` textures and
`TGA` images inside are claimed by the plugins that already read those."""

from __future__ import annotations

from gcrip.formats import ljam

NAME = "ljam"


def is_container(name: str, head: bytes) -> bool:
    return ljam.is_ljam(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return ljam.expand(data)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
