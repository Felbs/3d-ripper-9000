"""``FSYS`` archives (gcrip.formats.fsys) - Pokemon Colosseum and Pokemon XD.  A container
only: members come out under the names the game gives them and go to whichever plugin claims
them."""

from __future__ import annotations

from gcrip.formats import fsys

NAME = "fsys"


def detect(path: str, head: bytes, size: int) -> bool:
    """A container only; both of these exist so the plugin is registered at all."""
    return False


def extract(data: bytes, path: str, src):
    return []


def is_container(name: str, head: bytes) -> bool:
    return fsys.is_fsys(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """Only the uncompressed members are handed over.

    Nearly everything on these discs is `LZSS`, and that codec is not solved - see the format
    note.  Emitting the compressed blobs would put thousands of undecodable members into every
    manifest for nothing, so they are skipped until the codec falls, at which point this is the
    only place that has to change.
    """
    out = []
    seen: dict[str, int] = {}
    for m in fsys.members(data):
        if m.compressed:
            continue
        stem = m.name
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        if n:
            stem = f"{stem}_{n}"
        # an uncompressed member repeats its own length first; hand over what follows
        out.append((f"{stem}.bin", data[m.offset + 4 : m.offset + m.size]))
    return out
