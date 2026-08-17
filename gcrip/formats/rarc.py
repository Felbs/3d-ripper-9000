"""RARC archive parsing (Nintendo's JKernel archive; .arc/.rarc, and the payload
of .szs (Yaz0) / .szp (Yay0) files in J3D-era games).

All big-endian.

Header (0x20):
  0x00 'RARC'      0x04 file size        0x08 header size (0x20)
  0x0C data offset (relative to end of header, i.e. absolute = 0x20 + value)
  0x10 data length 0x14 MRAM size        0x18 ARAM size   0x1C pad
Info block (at 0x20, offsets below relative to 0x20):
  0x00 node count      0x04 node table offset
  0x08 file entry count 0x0C file entry table offset
  0x10 string table size 0x14 string table offset
  0x18 next free file id (u16), 0x1A sync-ids flag (u8)
Node (0x10): u32 type tag ('ROOT' or 4 chars of name), u32 name offset,
  u16 name hash, u16 file count, u32 first file entry index
File entry (0x14): u16 id (0xFFFF for dirs), u16 name hash,
  u32 flags<<24 | name offset, u32 data offset (dirs: node index), u32 size, u32 pad
Flags: 0x01 file, 0x02 dir, 0x04 compressed, 0x10 in MRAM, 0x20 in ARAM,
  0x40 load from DVD, 0x80 Yaz0 (else Yay0 when compressed)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"RARC"

FLAG_FILE = 0x01
FLAG_DIR = 0x02
FLAG_COMPRESSED = 0x04
FLAG_MRAM = 0x10
FLAG_ARAM = 0x20
FLAG_DVD = 0x40
FLAG_YAZ0 = 0x80


def is_rarc(data: bytes) -> bool:
    return data[:4] == MAGIC


@dataclass
class RarcFile:
    path: str  # relative to archive root, includes the root node's name as first component
    name: str
    offset: int  # absolute offset of the data within the (decompressed) archive
    size: int
    flags: int
    file_id: int
    node_index: int

    @property
    def compressed(self) -> bool:
        return bool(self.flags & FLAG_COMPRESSED)

    @property
    def yaz0(self) -> bool:
        return bool(self.flags & FLAG_YAZ0)


@dataclass
class RarcDir:
    path: str
    name: str
    node_type: str
    node_index: int


@dataclass
class Rarc:
    root_name: str
    files: list[RarcFile] = field(default_factory=list)
    dirs: list[RarcDir] = field(default_factory=list)

    def read(self, data: bytes, f: RarcFile) -> bytes:
        return data[f.offset : f.offset + f.size]


def _cstr(b: bytes, off: int) -> str:
    end = b.find(b"\x00", off)
    raw = b[off : end if end >= 0 else len(b)]
    for enc in ("shift_jis", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def parse(data: bytes) -> Rarc:
    """Parse a decompressed RARC archive. Returns file entries with absolute
    offsets into `data`; nothing is copied."""
    if data[:4] != MAGIC:
        raise ValueError("not a RARC archive")
    header_size, data_offset = struct.unpack_from(">II", data, 0x08)
    data_base = header_size + data_offset
    info = header_size
    (
        node_count,
        node_off,
        file_count,
        file_off,
        _string_size,
        string_off,
    ) = struct.unpack_from(">6I", data, info)
    node_off += info
    file_off += info
    string_off += info

    if node_count == 0:
        raise ValueError("RARC has no nodes")

    nodes = []
    for i in range(node_count):
        base = node_off + i * 0x10
        tag = data[base : base + 4].decode("ascii", "replace")
        name_offset, _hash, nfiles, first = struct.unpack_from(">IHHI", data, base + 4)
        nodes.append((tag, _cstr(data, string_off + name_offset), nfiles, first))

    arc = Rarc(root_name=nodes[0][1])
    node_paths: dict[int, str] = {0: nodes[0][1]}
    arc.dirs.append(
        RarcDir(path=nodes[0][1], name=nodes[0][1], node_type=nodes[0][0], node_index=0)
    )

    # Walk nodes in order; a directory node's path is known once its parent
    # (which always precedes it) has been walked and its dir entry seen.
    for ni, (tag, nname, nfiles, first) in enumerate(nodes):
        parent_path = node_paths.get(ni)
        if parent_path is None:
            # Orphan node (shouldn't happen in valid archives) - place at root.
            parent_path = f"{arc.root_name}/{nname}"
            node_paths[ni] = parent_path
            arc.dirs.append(RarcDir(path=parent_path, name=nname, node_type=tag, node_index=ni))
        for fi in range(first, first + nfiles):
            base = file_off + fi * 0x14
            file_id, _hash, w, off_or_node, size = struct.unpack_from(">HHIII", data, base)
            flags = w >> 24
            name = _cstr(data, string_off + (w & 0xFFFFFF))
            if flags & FLAG_DIR:
                if name in (".", ".."):
                    continue
                child = off_or_node
                if child < node_count and child not in node_paths:
                    child_path = f"{parent_path}/{name}"
                    node_paths[child] = child_path
                    arc.dirs.append(
                        RarcDir(
                            path=child_path, name=name, node_type=nodes[child][0], node_index=child
                        )
                    )
            else:
                arc.files.append(
                    RarcFile(
                        path=f"{parent_path}/{name}",
                        name=name,
                        offset=data_base + off_or_node,
                        size=size,
                        flags=flags,
                        file_id=file_id,
                        node_index=ni,
                    )
                )
    return arc
