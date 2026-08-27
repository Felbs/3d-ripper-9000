"""AFS - CRI's flat archive (Dreamcast/PS2, everywhere on Sega discs).

    u32 "AFS\\0", u32 count, then count x (u32 offset, u32 size); a name table
    (32-byte names + timestamps, u32 size) may sit at the end, its location given by a final
    (offset, size) pair right after the entry table (or at 0x7FFF8 in some files).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"AFS\x00"


@dataclass
class AfsEntry:
    index: int
    offset: int
    size: int
    name: str = ""


def is_afs(data: bytes) -> bool:
    return data[:4] == MAGIC


def parse(data: bytes) -> list[AfsEntry]:
    if not is_afs(data) or len(data) < 8:
        raise ValueError("not an AFS")
    count = struct.unpack_from("<I", data, 4)[0]
    if count > 1 << 20 or 8 + count * 8 > len(data):
        raise ValueError("AFS: implausible entry count")
    entries = []
    for i in range(count):
        off, size = struct.unpack_from("<II", data, 8 + i * 8)
        entries.append(AfsEntry(i, off, size))
    # optional name table
    for probe in (8 + count * 8, 0x7FFF8):
        if probe + 8 <= len(data):
            noff, nsize = struct.unpack_from("<II", data, probe)
            if noff and nsize >= count * 48 and noff + nsize <= len(data):
                for i in range(count):
                    raw = data[noff + i * 48 : noff + i * 48 + 32]
                    entries[i].name = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
                break
    return entries
