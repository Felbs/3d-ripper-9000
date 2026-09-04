"""Acclaim ``supertree0.tre`` (gcrip.formats.acclaim_tre): Vexx and Turok: Evolution.  A
container of the table's members - textures named ``tex_<key>.atx`` and decoded here, the
rest by their key - keeping the ``SWAP`` animation packs and anything over 4 MB out of the
member list (the file is the whole disc; nothing in those reads yet)."""

from __future__ import annotations

import posixpath

from gcrip.formats import acclaim_tre
from ripcore.scene import Scene

NAME = "acclaim_tre"
MAX_MEMBER = 4 << 20
SKIP_MAGIC = (b"SWAP",)


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".tre") and len(head) >= 64 and acclaim_tre.is_tre(head, 1 << 31)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for e in acclaim_tre.table(data[: acclaim_tre.RECORD * acclaim_tre.MAX_RECORDS], len(data)):
        if e.size <= 0 or e.size > MAX_MEMBER:
            continue
        head = data[e.offset : e.offset + 32]
        if head[:4] in SKIP_MAGIC:
            continue
        blob = data[e.offset : e.offset + e.size]
        if acclaim_tre.is_texture(head, e.size):
            out.append((f"tex_{e.key:08x}.atx", blob))
        else:
            out.append((f"{e.key:08x}.bin", blob))
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".atx") and acclaim_tre.is_texture(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = acclaim_tre.texture(data)
    if rgba is None:
        return []
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=name)
    scene.textures[name] = rgba
    scene.extras = {"textures_only": True, "format": "acclaim_tre"}
    return [scene]
