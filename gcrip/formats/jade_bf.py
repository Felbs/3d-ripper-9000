"""Ubisoft Jade engine "BIG" files (.bf): sally.bf (Beyond Good & Evil),
prince.bf (Prince of Persia: The Sands of Time), also King Kong / Rayman Raving
Rabbids on later consoles.

Everything in the table is little-endian, on GameCube too.

Header (44 bytes):
  0x00 'BIG\\0'   0x04 version (34 = BG&E, 37 = PoP SoT)   0x08 max files
  0x0C max dirs  0x10 max keys  0x14 root  0x18 first free file  0x1C first free dir
  0x20 size of fat (entries per fat)  0x24 number of fats  0x28 universe key
Fat header (0x18) follows the header: files, dirs, pos_fat, next_pos_fat,
  first index, last index.
At pos_fat: file references (u32 data offset, u32 key) x files;
  at pos_fat + size_of_fat*8: file infos (u32 length, i32 prev, i32 next,
  i32 parent dir, u32 mtime, char[64] name [+ u32 p4 revision except v34/37/38]);
  then directory infos (i32 first file, i32 first subdir, i32 prev, i32 next,
  i32 parent, char[64] name).
At each data offset: u32 size (bit 31 = "branch", unused here), then the bytes.

Keys: the top byte says what a file is.  0xFF0xxxxx = a level's binarized map
pack, 0xFF4 = its sounds, 0xFF8 = its textures (BG&E only), 0xFD/0xFE = texts.
Those packs are LZO block streams (see jade_lzo); everything else is stored raw.

Layout documented by the Ray1Map project (BinarySerializer/Ray1Map,
Assets/Scripts/Games/Jade/Serializable/BIG/BigFile/*.cs).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"BIG\0"
HEADER_SIZE = 44
FAT_HEADER_SIZE = 0x18
DIR_INFO_SIZE = 0x54
NAME_SIZE = 0x40


class BfError(ValueError):
    pass


@dataclass
class BfEntry:
    path: str  # "ROOT/Bin/ff007685.bin" - directory chain + file name
    key: int
    offset: int  # absolute offset of the payload (past the u32 size)
    size: int


def is_bf(data: bytes) -> bool:
    return data[:4] == MAGIC


def _file_info_size(version: int) -> int:
    if version in (34, 37, 38):
        return 0x54
    if version >= 42:
        return 0x3C + NAME_SIZE
    return 0x58


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin-1")


def _dir_path(dirs: list[tuple[int, str]], i: int, cache: dict[int, str]) -> str:
    if i in cache:
        return cache[i]
    parts = []
    seen = set()
    j = i
    while 0 <= j < len(dirs) and j not in seen:
        seen.add(j)
        parts.append(dirs[j][1])
        j = dirs[j][0]
    cache[i] = "/".join(reversed(parts))
    return cache[i]


def parse(data: bytes) -> list[BfEntry]:
    if not is_bf(data):
        raise BfError("not a Jade BIG file")
    if len(data) < HEADER_SIZE + FAT_HEADER_SIZE:
        raise BfError("truncated BIG header")
    version, max_file, max_dir, _max_key, _root, _fff, _ffd, size_of_fat, num_fat = (
        struct.unpack_from("<9I", data, 4)
    )
    if size_of_fat == 0 or num_fat == 0:
        return []
    fi_size = _file_info_size(version)
    entries: list[BfEntry] = []
    fat_pos = HEADER_SIZE
    for _ in range(num_fat):
        if fat_pos + FAT_HEADER_SIZE > len(data):
            break
        n_files, n_dirs, pos_fat, next_pos = struct.unpack_from("<IIIi", data, fat_pos)
        refs_off = pos_fat
        infos_off = pos_fat + size_of_fat * 8
        dirs_off = infos_off + size_of_fat * fi_size
        if dirs_off + n_dirs * DIR_INFO_SIZE > len(data):
            raise BfError("fat table runs past the end of the file")
        dirs = []
        for i in range(n_dirs):
            o = dirs_off + i * DIR_INFO_SIZE
            parent = struct.unpack_from("<i", data, o + 16)[0]
            dirs.append((parent, _cstr(data[o + 20 : o + 20 + NAME_SIZE])))
        paths: dict[int, str] = {}
        for i in range(n_files):
            off, key = struct.unpack_from("<II", data, refs_off + i * 8)
            o = infos_off + i * fi_size
            length, _prev, _next, parent = struct.unpack_from("<Iiii", data, o)
            name = _cstr(data[o + 20 : o + 20 + NAME_SIZE])
            if off + 4 > len(data):
                continue
            size = struct.unpack_from("<I", data, off)[0] & 0x7FFFFFFF
            if length and length != size:
                size = min(size, length)
            if off + 4 + size > len(data):
                size = max(0, len(data) - off - 4)
            d = _dir_path(dirs, parent, paths) if parent >= 0 else ""
            entries.append(BfEntry(f"{d}/{name}" if d else name, key, off + 4, size))
        if next_pos == -1 or next_pos <= 0:
            break
        fat_pos = next_pos
    return entries


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return [(e.path, data[e.offset : e.offset + e.size]) for e in parse(data)]


KEY_MAP = 0xFF0
KEY_SOUNDS = 0xFF4
KEY_TEXTURES = 0xFF8


def key_type(key: int) -> str | None:
    top = key >> 20
    if top == KEY_MAP:
        return "map"
    if top == KEY_SOUNDS:
        return "sounds"
    if top == KEY_TEXTURES:
        return "textures"
    if (key >> 24) in (0xFD, 0xFE):
        return "text"
    return None
