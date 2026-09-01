"""Madagascar ``.gcn`` resource archives (gcrip.formats.tfb_gcn) as a container.

The payloads are ordinary RenderWare - ``rwID_CLUMP``, ``rwID_WORLD``, ``rwID_TEXDICTIONARY``,
``rwID_HANIMANIMATION`` - so this only has to hand them out under their own names and
``plugins/renderware.py`` reads them.  ``detect``/``extract`` decline because
``container_plugins()`` will not register a module without them.
"""

from __future__ import annotations

from gcrip.formats import tfb_gcn
from ripcore.scene import Scene

NAME = "tfb_gcn"
SUFFIX = ".gcn"


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    return []


def is_container(name: str, head: bytes) -> bool:
    """``rip`` passes a basename, and ``head`` is only the 64 bytes ``classify`` sniffs - too
    few to walk the chain, so this screens on the extension and the census chunk, and
    ``expand`` does the real check."""
    if not name.lower().endswith(SUFFIX) or len(head) < tfb_gcn.HEADER:
        return False
    import struct

    kind, size, _lib = struct.unpack_from("<3I", head, 0)
    return kind == tfb_gcn.CENSUS and size > 0


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if not tfb_gcn.is_gcn(data):
        return []
    out = []
    seen: dict[str, int] = {}
    for res in tfb_gcn.resources(data):
        # names repeat across languages, and a resource may share a name with another tag
        stem = res.name.rsplit(".", 1)[0] or res.tag
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        label = stem if n == 0 else f"{stem}_{n}"
        out.append((f"{label}.dff", data[res.offset : res.offset + res.size]))
    return out
