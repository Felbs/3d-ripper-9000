"""Midway ``SEC`` archives (``.ssf``, gcrip.formats.mk_ssf) as a container: clumps go on as
``<name>.mkdff`` and textures as ``<name>.mktex`` for the RenderWare plugin."""

from __future__ import annotations

from gcrip.formats import mk_ssf

NAME = "mk_ssf"


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".ssf") and mk_ssf.is_ssf(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    seen: dict[str, int] = {}
    for m in mk_ssf.members(data):
        if m.kind == mk_ssf.CLUMP:
            blob = m.data[mk_ssf.CLUMP_PREFIX :]
            ext = "mkdff"
        elif m.kind == mk_ssf.TEXTURE:
            blob = m.data
            ext = "mktex"
        else:
            blob = m.data
            ext = "bin"
        stem = m.name or "member"
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        out.append((f"{stem}{'' if n == 0 else f'_{n}'}.{ext}", blob))
    return out
