"""EA BIG / VIV archives (BIGF, BIG4 and the older C0FB index).

BIGF/BIG4: magic, u32 LE archive size, u32 BE file count, u32 BE index size, then per file
u32 BE offset, u32 BE size, NUL-terminated path (backslash separated). C0FB: u16 BE 0xC0FB,
u16 BE index size, u16 BE count, then u24 BE offset, u24 BE size, NUL-terminated path.
Members are frequently RefPack-compressed; `expand` decompresses them.
"""

from __future__ import annotations

import contextlib
import struct
from dataclasses import dataclass

from gcrip.formats import refpack


@dataclass
class BigEntry:
    name: str
    offset: int
    size: int


def is_big(data: bytes) -> bool:
    if len(data) < 16:
        return False
    if data[:4] in (b"BIGF", b"BIG4"):
        return True
    return data[:2] == b"\xc0\xfb"


def parse(data: bytes) -> list[BigEntry]:
    if data[:2] == b"\xc0\xfb":
        _index_size, count = struct.unpack_from(">HH", data, 2)
        pos = 6
        out = []
        for _ in range(count):
            off = int.from_bytes(data[pos : pos + 3], "big")
            size = int.from_bytes(data[pos + 3 : pos + 6], "big")
            end = data.index(b"\0", pos + 6)
            out.append(BigEntry(data[pos + 6 : end].decode("latin-1"), off, size))
            pos = end + 1
        return out
    if data[:4] not in (b"BIGF", b"BIG4"):
        raise ValueError("not a BIG archive")
    count, _index_size = struct.unpack_from(">II", data, 8)
    if count > 0x100000:
        raise ValueError("implausible BIG file count")
    pos = 16
    out = []
    for _ in range(count):
        off, size = struct.unpack_from(">II", data, pos)
        end = data.index(b"\0", pos + 8)
        out.append(BigEntry(data[pos + 8 : end].decode("latin-1"), off, size))
        pos = end + 1
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """(inner path, bytes) for every member, RefPack members decompressed."""
    out = []
    for e in parse(data):
        blob = data[e.offset : e.offset + e.size]
        if refpack.is_refpack(blob):
            with contextlib.suppress(ValueError):
                blob = refpack.decompress(blob)
        name = e.name.replace("\\", "/").lstrip("/")
        out.append((name, blob))
    return out
