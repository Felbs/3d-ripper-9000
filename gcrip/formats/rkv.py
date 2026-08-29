"""Krome Studios RKV archives (Merkury engine v1: Ty the Tasmanian Tiger; v2 archives of
Ty 2 / Ty 3 / Spyro A New Beginning / King Arthur / Jimmy Neutron are detected but only
v1 is opened so far).

RKV v1: the file is member data followed by the directory: ``nfiles`` 64-byte entries
(``char name[32], u32 dir index, u32 size, u32 0, u32 offset, u32 crc, u32 time, u32, u32``),
``ndirs`` 256-byte directory names, then the footer ``u32 LE nfiles, u32 LE ndirs``.
Offset 0xffffffff marks source files that were not shipped.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC_V2 = b"RKV2"


@dataclass
class Member:
    name: str
    offset: int
    size: int


def is_rkv(head: bytes, tail: bytes | None = None) -> bool:
    return head[:4] == MAGIC_V2 or (tail is not None and _footer_ok(tail))


def _footer_ok(tail: bytes) -> bool:
    if len(tail) < 8:
        return False
    nfiles, ndirs = struct.unpack_from("<II", tail, len(tail) - 8)
    return 0 < nfiles < 1_000_000 and 0 < ndirs < 100_000


def _members_v2(data: bytes) -> list[Member]:
    """RKV2: ``"RKV2" | u32 nfiles | u32 names size | u32 nsources | u32 source names size
    | u32 directory offset | u32 directory size`` (all LE); the directory holds 20-byte
    entries ``u32 name offset, u32 flags, u32 size, u32 offset, u32 crc`` then the name
    table (then per-file build source paths + mtimes, ignored).  Data archives keep the
    directory at 0x80, media archives at the end."""
    n = len(data)
    if n < 0x40:
        return []
    nfiles, names_size, _nsrc, _ssz, dir_off, dir_size = struct.unpack_from("<6I", data, 4)
    if not (0 < nfiles < 1_000_000) or dir_off + dir_size > n:
        return []
    if nfiles * 20 + names_size > dir_size:
        return []
    names_off = dir_off + nfiles * 20
    names = data[names_off : names_off + names_size]
    out = []
    for i in range(nfiles):
        name_off, _flags, size, off, _crc = struct.unpack_from("<5I", data, dir_off + i * 20)
        end = names.find(b"\0", name_off)
        name = names[name_off : end if end >= 0 else names_size].decode("latin-1", "replace")
        if not name or off + size > n or size == 0:
            continue
        out.append(Member(name.replace("\\", "/").lstrip("./"), off, size))
    return out


def members(data: bytes) -> list[Member]:
    n = len(data)
    if data[:4] == MAGIC_V2:
        return _members_v2(data)
    if n < 8 or not _footer_ok(data[-8:]):
        return []
    nfiles, ndirs = struct.unpack_from("<II", data, n - 8)
    dirs_off = n - 8 - ndirs * 256
    ents_off = dirs_off - nfiles * 64
    if ents_off < 0:
        return []
    dirs = [
        data[dirs_off + i * 256 : dirs_off + (i + 1) * 256].split(b"\0")[0].decode("latin-1")
        for i in range(ndirs)
    ]
    out = []
    for i in range(nfiles):
        e = data[ents_off + i * 64 : ents_off + (i + 1) * 64]
        name = e[:32].split(b"\0")[0].decode("latin-1", "replace")
        didx, size, _z, off = struct.unpack_from("<4I", e, 32)
        if off == 0xFFFFFFFF or off + size > ents_off or not name:
            continue
        folder = dirs[didx] if didx < len(dirs) else ""
        path = (folder + name).replace("\\", "/").lstrip("./")
        out.append(Member(path, off, size))
    return out
