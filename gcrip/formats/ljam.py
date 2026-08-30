"""``LJAM`` archives - Hunter: The Reckoning keeps its whole game in 35 of them, 304 MB.

Little-endian, and the whole file is a directory tree written depth-first::

    +0   char magic[4]  "LJAM"
    +4   the root node

    node:
        u32 file count
        file count times:  char name[12], u32 offset, u32 size
        u32 directory count
        directory count times:  char name[12], u32 node offset

So a node is **its files and then its subdirectories** - two counted tables back to back, not
one - and that is the only thing that has to be got right.  Reading a node as a single table
parses the first branch and then stops, which is what a first pass did: it found the one
script at the root of ``INTROUI.JAM`` and none of the 383 KB behind it.

The tree names everything, including the textures the rest of the pipeline can already read::

    /UI/DATASETS/INTROUI/GRAPHICS/LOGOS.TPL
    /UI/DATASETS/INTROUI/GRAPHICS/LEGALBK.TPL
    /UI/DATASETS/INTROUI/GRAPHICS/T_HNT14.TGA

A name fills the 12 bytes with no terminator when it is exactly 12 characters long, so a check
that insists on a NUL drops those entries - and dropping one entry in a node's table is enough
to lose the whole subtree under it.  That cost ``GRAPHICS`` its `TPL` textures on the first
attempt, because the two entries either side of them are 12 characters.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"LJAM"
ROOT = 4
NAME = 12
FILE_ENTRY = 20
DIR_ENTRY = 16
MAX_ENTRIES = 8192
MAX_DEPTH = 24


@dataclass
class Member:
    path: str
    offset: int
    size: int


def is_ljam(head: bytes) -> bool:
    return len(head) >= 8 and head[:4] == MAGIC


def _name(data: bytes, at: int) -> str | None:
    raw = data[at : at + NAME]
    if len(raw) < NAME:
        return None
    text = raw.split(b"\0")[0]  # a 12-character name fills the field with no terminator
    if not text or not all(32 <= c < 127 for c in text) or set(raw[len(text) :]) - {0}:
        return None
    return text.decode("latin-1")


def _node(data: bytes, at: int, path: str, out: list[Member], seen: set[int], depth: int) -> None:
    if at in seen or at + 4 > len(data) or depth > MAX_DEPTH:
        return
    seen.add(at)
    files = struct.unpack_from("<I", data, at)[0]
    if files > MAX_ENTRIES or at + 4 + files * FILE_ENTRY > len(data):
        return
    p = at + 4
    for _ in range(files):
        name = _name(data, p)
        offset, size = struct.unpack_from("<2I", data, p + NAME)
        if name is not None and size and offset >= ROOT and offset + size <= len(data):
            out.append(Member(f"{path}/{name}", offset, size))
        p += FILE_ENTRY
    if p + 4 > len(data):
        return
    dirs = struct.unpack_from("<I", data, p)[0]
    if dirs > MAX_ENTRIES or p + 4 + dirs * DIR_ENTRY > len(data):
        return
    q = p + 4
    for _ in range(dirs):
        name = _name(data, q)
        child = struct.unpack_from("<I", data, q + NAME)[0]
        if name is not None and ROOT < child < len(data):
            _node(data, child, f"{path}/{name}", out, seen, depth + 1)
        q += DIR_ENTRY


def members(data: bytes) -> list[Member]:
    if not is_ljam(data[:8]):
        return []
    out: list[Member] = []
    _node(data, ROOT, "", out, set(), 0)
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for m in members(data):
        name = m.path.lstrip("/").replace("/", "__")
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:
            stem, _dot, ext = name.rpartition(".")
            name = f"{stem}_{n:03d}.{ext}" if stem else f"{name}_{n:03d}"
        out.append((name, data[m.offset : m.offset + m.size]))
    return out
