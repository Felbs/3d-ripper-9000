"""Konami ``KCEO ARCDT`` archives (gcrip.formats.kceo_arc) as a container - Evolution
Snowboarding.  Members are named ``.BPX`` files; handing them to the pipeline lets every other
plugin and the structure scanner see them.  ``detect``/``extract`` decline because
``container_plugins()`` will not register a module without them."""

from __future__ import annotations

from gcrip.formats import kceo_arc
from ripcore.scene import Scene

NAME = "kceo_arc"
SUFFIX = ".arc"


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    return []


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(SUFFIX) and kceo_arc.is_kceo_arc(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    seen: dict[str, int] = {}
    for m in kceo_arc.members(data):
        n = seen.get(m.name, 0)
        seen[m.name] = n + 1
        label = m.name if n == 0 else f"{n}_{m.name}"
        out.append((label, data[m.offset : m.offset + m.size]))
    return out
