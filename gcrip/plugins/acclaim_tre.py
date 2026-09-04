"""Acclaim ``supertree0.tre`` (gcrip.formats.acclaim_tre): Vexx and Turok: Evolution.  A
container of the table's members - textures named ``tex_<key>.atx`` and decoded here, the
rest by their key - keeping the ``SWAP`` animation packs and anything over 4 MB out of the
member list (the file is the whole disc; nothing in those reads yet)."""

from __future__ import annotations

import posixpath
import struct

from gcrip.formats import acclaim_tre
from ripcore.scene import Scene

NAME = "acclaim_tre"
MAX_MEMBER = 20 << 20
SKIP_MAGIC = (b"SWAP",)


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".tre") and len(head) >= 64 and acclaim_tre.is_tre(head, 1 << 31)


MAX_DEPTH = 3
MAX_TABLE = 64 << 20


def _is_subtree(head: bytes, size: int) -> bool:
    """A member that is itself a table: its first row's offset + size fit inside it."""
    if len(head) < 16 or head[:4].isalnum() or head[:10] == bytes(10):
        return False
    _ident, offset, length, _key = struct.unpack_from(">4I", head, 0)
    return length > 0 and offset + length <= size and size >= 64


def _walk(data: bytes, out: list, prefix: str, depth: int) -> None:
    for e in acclaim_tre.table(data[: acclaim_tre.RECORD * acclaim_tre.MAX_RECORDS], len(data)):
        if e.size <= 0:
            continue
        head = data[e.offset : e.offset + 32]
        if head[:4] in SKIP_MAGIC:
            continue
        if depth < MAX_DEPTH and e.size <= MAX_TABLE and _is_subtree(head, e.size):
            sub = data[e.offset : e.offset + e.size]
            if len(acclaim_tre.table(sub[: acclaim_tre.RECORD * 4096], e.size)) >= 4:
                _walk(sub, out, f"{prefix}{e.key:08x}/", depth + 1)
                continue
        if e.size > MAX_MEMBER:
            continue
        blob = data[e.offset : e.offset + e.size]
        if acclaim_tre.is_texture(head, e.size):
            out.append((f"{prefix}tex_{e.key:08x}.atx", blob))
        else:
            out.append((f"{prefix}{e.key:08x}.bin", blob))


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """Every leaf of the tree - members that are tables themselves (105 on Vexx, holding
    7,706 more textures and the ``AAAp`` geometry) are walked, not handed out."""
    out: list[tuple[str, bytes]] = []
    _walk(data, out, "", 0)
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
