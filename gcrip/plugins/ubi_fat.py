"""Ubisoft ``.fat`` + ``.000`` (gcrip.formats.ubi_fat): Batman: Vengeance, Batman: Rise of
Sin Tzu.  The ``.fat`` is the container; its members come out of the sibling ``.000``
unpacked, named by their ``/gamedata/...`` path with the leading directories dropped."""

from __future__ import annotations

import posixpath

from gcrip.formats import ubi_fat

NAME = "ubi_fat"
NEEDS_SIBLING = True
MAX_MEMBER = 64 << 20


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".fat") and ubi_fat.is_fat(head)


def expand_with(data: bytes, name: str, sibling) -> list[tuple[str, bytes]]:
    stem = posixpath.basename(name).rsplit(".", 1)[0]
    store = sibling(f"{stem}.000")
    if not store:
        return []
    out = []
    seen: set[str] = set()
    for e in ubi_fat.entries(data):
        if not (0 < e.unpacked <= MAX_MEMBER):
            continue
        blob = ubi_fat.unpack(store, e)
        if not blob:
            continue
        member = e.name.lstrip("/")
        if member.lower().startswith("gamedata/"):
            member = member[len("gamedata/") :]
        base = member
        k = 1
        while member in seen:
            k += 1
            member = f"{base}.{k}"
        seen.add(member)
        out.append((member, blob))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return []


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
