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
    """Members come out decompressed.  Nearly everything on these discs is `LZSS`."""
    out = []
    seen: dict[str, int] = {}
    for m in fsys.members(data):
        blob = data[m.offset : m.offset + m.size]
        if m.compressed:
            payload = fsys.decompress(blob[fsys.LZSS_HEADER :], m.unpacked)
            if payload is None:
                continue
        else:
            # an uncompressed member repeats its own length first
            payload = blob[4:]
        stem = m.name
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        if n:
            stem = f"{stem}_{n}"
        out.append((f"{stem}.bin", payload))
    return out
