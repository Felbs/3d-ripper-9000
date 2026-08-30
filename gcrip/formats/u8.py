"""Nintendo U8 archives (``.arc``): the plain directory format that sits beside RARC on
GameCube and Wii discs (F-Zero GX wraps one in ``vehicle_parts/parts_all.arc.lz``).

Header: ``u32 magic 0x55AA382D | u32 root node offset (usually 0x20) | u32 header size |
u32 data offset | 16 zero bytes``.  Nodes are 12 bytes each, starting at the root node
offset: ``u8 type (0 file, 1 directory) | u24 name offset | u32 data offset (file) or parent
index (directory) | u32 size (file) or index one past the directory's last child``.  The
root node's size is the node count; the string table follows the nodes and holds
NUL-terminated names.  All fields are big-endian.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"U\xaa8-"
NODE = 12


@dataclass
class Entry:
    path: str
    offset: int
    size: int


def is_u8(head: bytes) -> bool:
    if len(head) < 0x20 or head[:4] != MAGIC:
        return False
    root, header_size, data_off = struct.unpack_from(">3I", head, 4)
    return root >= 0x20 and 0 < header_size < 0x8000000 and data_off >= root


def entries(data: bytes) -> list[Entry]:
    """Files of the archive with their full paths (directories only shape the paths)."""
    if not is_u8(data[:0x20]):
        return []
    root = struct.unpack_from(">I", data, 4)[0]
    if root + NODE > len(data):
        return []
    count = struct.unpack_from(">I", data, root + 8)[0]
    if not 0 < count < 500000 or root + count * NODE > len(data):
        return []
    strings = root + count * NODE
    nodes = []
    for i in range(count):
        o = root + i * NODE
        kind = data[o]
        name_off = int.from_bytes(data[o + 1 : o + 4], "big")
        a, b = struct.unpack_from(">2I", data, o + 4)
        nodes.append((kind, name_off, a, b))

    def name(off: int) -> str:
        p = strings + off
        if p >= len(data):
            return ""
        end = data.find(b"\0", p)
        return data[p : end if end >= 0 else len(data)].decode("latin-1", "replace")

    out: list[Entry] = []
    stack: list[tuple[int, str]] = [(count, "")]  # (index one past the directory, prefix)
    for i in range(1, count):
        while stack and i >= stack[-1][0]:
            stack.pop()
        prefix = stack[-1][1] if stack else ""
        kind, name_off, a, b = nodes[i]
        label = name(name_off)
        if kind == 1:
            stack.append((b, f"{prefix}{label}/" if label else prefix))
            continue
        if a + b > len(data) or b == 0:
            continue
        out.append(Entry(f"{prefix}{label}" if label else f"file{i:04d}", a, b))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return [(e.path, data[e.offset : e.offset + e.size]) for e in entries(data)]
