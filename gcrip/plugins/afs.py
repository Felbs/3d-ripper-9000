"""Sega / CRI ``AFS`` archives as a named container (Konami's TMNT 1-3 ``.DAT`` data files and
``.afs`` sound banks, Sonic Team discs): ``"AFS\\0" | u32 count | count x (u32 offset, u32
size) | u32 name-table offset, u32 size``; the name table holds 48-byte records ``char
name[32] | u16 year, month, day, hour, minute, second | u32 size``."""

from __future__ import annotations

import struct

NAME = "afs"
MAGIC = b"AFS\0"


def is_container(name: str, head: bytes) -> bool:
    if head[:4] != MAGIC or len(head) < 16:
        return False
    count = struct.unpack_from("<I", head, 4)[0]
    return 0 < count < 65536


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if data[:4] != MAGIC:
        return []
    count = struct.unpack_from("<I", data, 4)[0]
    if count <= 0 or 8 + count * 8 + 8 > len(data):
        return []
    entries = [struct.unpack_from("<2I", data, 8 + i * 8) for i in range(count)]
    nt_off, nt_size = struct.unpack_from("<2I", data, 8 + count * 8)
    names: list[str] = []
    if nt_off and nt_off + nt_size <= len(data) and nt_size >= count * 48:
        for i in range(count):
            raw = data[nt_off + i * 48 : nt_off + i * 48 + 32].split(b"\0")[0]
            names.append(raw.decode("latin-1", "replace").replace("\\", "/").rsplit("/", 1)[-1])
    out = []
    seen: dict[str, int] = {}
    for i, (off, size) in enumerate(entries):
        if size == 0 or off + size > len(data):
            continue
        name = names[i] if i < len(names) and names[i] else f"member{i:04d}.bin"
        if name in seen:
            seen[name] += 1
            stem, dot, ext = name.rpartition(".")
            name = f"{stem}_{seen[name]}.{ext}" if dot else f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append((name, data[off : off + size]))
    return out


# gcrip.plugins.all_plugins() only registers a module that has BOTH detect and extract, so a
# container needs this pair even though it produces no Scenes of its own.  Without it the
# plugin is skipped silently and the archive is never expanded.
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
