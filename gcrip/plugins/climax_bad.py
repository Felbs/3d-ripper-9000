"""Climax ``.bad`` archives as a container (gcrip.formats.climax_bad): ATV: Quad Power
Racing 2, Hot Wheels World Race and The Italian Job each keep the whole game in one.  The
sibling ``.bah`` names every member; each member is its own LZSS block (or a raw one)."""

from __future__ import annotations

from gcrip.formats import climax_bad

NAME = "climax_bad"
NEEDS_SIBLING = True


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".bad") and climax_bad.looks_like(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return climax_bad.members(data, None)


def expand_with(data: bytes, name: str, sibling) -> list[tuple[str, bytes]]:
    bah = None
    stem = name.rsplit(".", 1)[0]
    for candidate in (f"{stem}.bah", f"{stem}.BAH", "harchive.bah", "Archive.bah", "ATV.bah"):
        try:
            bah = sibling(candidate)
        except Exception:  # noqa: BLE001 - try the next name
            bah = None
        if bah and climax_bad.is_bah(bah[:16]):
            break
        bah = None
    return climax_bad.members(data, bah)


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
