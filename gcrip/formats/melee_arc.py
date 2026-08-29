"""TMNT: Mutant Melee (Konami) ``archive.arc`` directory + ``archive.dat`` blob.

``archive.arc``: ``char magic[8] "archive" | 0x5c filler (0xcd) | u32 size | u32 folder count |
u32 file count | u32 x | u32 name-table offset | u32 file-record offset``, then ``folder count``
20-byte folder records ``u32 name offset | i32 parent (-1 = root group) | u32 | u32 index |
u32 hash``, the name table (C strings) and ``file count`` 20-byte file records ``u32 name
offset | u32 folder | u32 data offset | u32 size | u16 resource type | u16 group``.

The data offsets and sizes address ``archive.dat`` directly: most members are little-endian
RenderWare 3.x streams (clump 0x10, texture dictionary 0x16, animation 0x1b, world 0x0b),
the rest DDS textures, ``ktf`` images, scripts and UTF-16 text.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"archive\0"
HEADER = 0x64
RECORD = 20

_RW_EXT = {0x10: "dff", 0x16: "txd", 0x1B: "anm", 0x0B: "pac", 0x1A: "rw3", 0x14: "rw3"}


@dataclass
class Entry:
    name: str
    folder: str
    offset: int
    size: int
    rtype: int
    group: int

    @property
    def path(self) -> str:
        return f"{self.folder}/{self.name}" if self.folder else self.name


def is_arc(name: str, head: bytes) -> bool:
    return name.lower().endswith(".arc") and head[:8] == MAGIC


def _cstr(buf: bytes, off: int) -> str:
    if not 0 <= off < len(buf):
        return ""
    end = buf.find(b"\0", off)
    return buf[off : end if end >= 0 else len(buf)].decode("latin-1", "replace")


def entries(arc: bytes) -> list[Entry]:
    if len(arc) < HEADER + 20 or arc[:8] != MAGIC:
        return []
    _size, nfold, nfile, _x, names_off, files_off = struct.unpack_from("<6I", arc, HEADER)
    if not (0 < nfile < 1_000_000 and names_off < files_off <= len(arc)):
        return []
    if files_off + nfile * RECORD > len(arc):
        return []
    names = arc[names_off:files_off]
    folders = []
    for k in range(min(nfold, (names_off - HEADER - 24) // RECORD)):
        off = struct.unpack_from("<I", arc, HEADER + 24 + k * RECORD)[0]
        folders.append(_cstr(names, off))
    out = []
    for k in range(nfile):
        name_off, folder, off, size, kind = struct.unpack_from("<5I", arc, files_off + k * RECORD)
        name = _cstr(names, name_off)
        if not name or size == 0:
            continue
        out.append(
            Entry(
                name,
                folders[folder] if folder < len(folders) else "",
                off,
                size,
                kind & 0xFFFF,
                kind >> 16,
            )
        )
    return out


def member_name(e: Entry, blob: bytes) -> str:
    """Path with an extension chosen from the member's own magic."""
    head = blob[:12]
    ext = "bin"
    if head[:4] == b"DDS ":
        ext = "dds"
    elif head[:4] == b"ktf\0":
        ext = "ktf"
    elif head[:2] == b"\xff\xfe":
        ext = "txt"
    elif len(head) >= 12:
        t, size, lib = struct.unpack("<3I", head)
        if 0 < t < 0x100 and (lib & 0xFFFF) == 0xFFFF and size <= len(blob):
            ext = _RW_EXT.get(t, "rw3")
    return f"{e.path}.{ext}" if e.path else f"{e.name}.{ext}"


def members(arc: bytes, dat: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for e in entries(arc):
        if e.offset + e.size > len(dat):
            continue
        blob = dat[e.offset : e.offset + e.size]
        name = member_name(e, blob)
        if name in seen:
            seen[name] += 1
            stem, _, ext = name.rpartition(".")
            name = f"{stem}_{seen[name]}.{ext}"
        else:
            seen[name] = 0
        out.append((name, blob))
    return out
