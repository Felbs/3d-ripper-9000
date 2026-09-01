"""Edge of Reality ``.arc`` archives (gcrip.formats.edge_ind) - The Sims, Shark Tale, Over the
Hedge.  A container only: the directory lives in the sibling ``index.ind``, and the members go
to whichever plugin claims them.

Audio and video categories are skipped rather than carried - ``Movies`` alone is 574 MB on Over
the Hedge, and none of it is geometry.
"""

from __future__ import annotations

from gcrip.formats import edge_ind

NAME = "edge_arc"
NEEDS_SIBLING = True

INDEX = "index.ind"
# the archives these discs actually ship, so an unrelated .arc is never claimed
STEMS = frozenset(
    {"models", "levels", "samples", "movies", "audiostr", "datasets", "quickdat", "rletextu"}
)
SKIP = frozenset({"movies", "audiostr", "samples"})


def detect(path: str, head: bytes, size: int) -> bool:
    """A container only; both of these exist so the plugin is registered at all."""
    return False


def extract(data: bytes, path: str, src):
    return []


def is_container(name: str, head: bytes) -> bool:
    """These archives open with zeros, so there is nothing to sniff - the name is all there
    is, and `expand_with` refuses anything whose index does not account for it exactly."""
    lower = name.lower()
    if not lower.endswith(".arc"):
        return False
    stem = lower[:-4]
    return stem in STEMS and stem not in SKIP


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return []


def expand_with(data: bytes, name: str, sibling) -> list[tuple[str, bytes]]:
    stem = name.lower()[:-4]
    try:
        index = sibling(INDEX)
    except Exception:  # noqa: BLE001
        return []
    if not index:
        return []
    for category, entries in edge_ind.categories(index).items():
        if edge_ind.stem_of(category) != stem:
            continue
        if not edge_ind.fits(entries, len(data)):
            return []  # the wrong archive for this category, so decline rather than guess
        out = []
        for e in entries:
            if e.size == 0 or e.offset + e.size > len(data):
                continue
            out.append((f"{category}/{e.hash:08x}.bin", data[e.offset : e.offset + e.size]))
        return out
    return []
