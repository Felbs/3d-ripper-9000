"""Blitz Games ``.gcp`` packs (Pac-Man World 3, Bratz, Bad Boys, Cubix, Fairly OddParents,
Frogger Ancient Shadow, Chicken Little, ...) as containers: ``AllPaks.gcp`` is an archive of
named per-level packs (gcrip.formats.blitz_gcp), and each pack splits further into Blitz's
stamped packages.  The object stream itself is not decoded yet; the split gives the structure
scanner small, named blobs to pull display lists out of."""

from __future__ import annotations

from gcrip.formats import blitz_gcp

NAME = "blitz"


def is_container(name: str, head: bytes) -> bool:
    return blitz_gcp.is_pack(name, head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    seen: dict[str, int] = {}
    for m in blitz_gcp.members(data):
        name = m.name
        if name in seen:
            seen[name] += 1
            stem, _, ext = name.rpartition(".")
            name = f"{stem}_{seen[name]}.{ext}"
        else:
            seen[name] = 0
        out.append((name, data[m.offset : m.offset + m.size]))
    if out:
        return out
    for i, (start, end, who) in enumerate(blitz_gcp.packages(data)):
        out.append((f"pkg{i:03d}_{who}.pkg", data[start:end]))
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
