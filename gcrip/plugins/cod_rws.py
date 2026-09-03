"""Call of Duty: Finest Hour's ``.rws`` (gcrip.formats.cod_rws) as a container: each section
is an ordinary RenderWare chunk behind an 8-byte header, so hand them out and
``plugins/renderware.py`` reads them."""

from __future__ import annotations

from gcrip.formats import cod_rws
from ripcore.scene import Scene

NAME = "cod_rws"


def detect(path: str, head: bytes, size: int) -> bool:
    """A container only; both of these exist so the plugin is registered at all."""
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    return []


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".rws") and cod_rws.is_cod_rws(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for i, s in enumerate(cod_rws.sections(data)):
        ext = cod_rws.EXT.get(s.ident, "bin")
        out.append((f"{i:03d}_{s.kind}.{ext}", data[s.offset : s.end]))
    return out
