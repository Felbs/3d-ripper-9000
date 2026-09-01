"""Yuke's ``.tex`` texture directories (gcrip.formats.yukes_tex) - WWE Day of Reckoning 1
and 2, WrestleMania XIX.  A container only: the members are ordinary Nintendo TPLs, so
``gcrip/plugins/tpl.py`` decodes them once they are handed over.
"""

from __future__ import annotations

from gcrip.formats import yukes_tex

NAME = "yukes_tex"


SUFFIXES = (".tex", ".pac")


def is_container(name: str, head: bytes) -> bool:
    """``rip.py`` passes the member's basename, never a path.  ``.pac`` is the same directory
    with different member types - mostly ``tpl`` there too."""
    return name.lower().endswith(SUFFIXES) and yukes_tex.is_tex(head)


def detect(path: str, head: bytes, size: int) -> bool:
    """A container only - the TPL plugin handles what comes out.  Both of these exist so the
    plugin is registered at all: `container_plugins()` only lists modules that are plugins in
    the full sense, so a container without them is silently never consulted."""
    return False


def extract(data: bytes, path: str, src):
    return []


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    seen: dict[str, int] = {}
    for m in yukes_tex.members(data):
        stem = f"{m.name}.{m.kind}"
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        if n:
            stem = f"{m.name}_{n}.{m.kind}"
        out.append((stem, data[m.offset : m.offset + m.size]))
    return out
