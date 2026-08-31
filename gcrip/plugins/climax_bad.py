"""Climax ``.bad`` archives as a container (gcrip.formats.climax_bad): ATV: Quad Power
Racing 2, Hot Wheels World Race and The Italian Job each keep the whole game in one, and the
payload is ring-buffer LZSS."""

from __future__ import annotations

from gcrip.formats import climax_bad

NAME = "climax_bad"
MIN_OUTPUT = 1 << 16


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".bad") and climax_bad.looks_like(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    at = climax_bad.stream_start(data)
    if at is None:
        return []
    out = climax_bad.decompress(data[at:])
    return [("payload", out)] if len(out) >= MIN_OUTPUT else []


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
