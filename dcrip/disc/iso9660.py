"""ISO 9660 directory walk over a GdImage (absolute LBAs, PVD at first data track + 16).

Directory record (ECMA-119 9.1): u8 length, u8 ext attr length, u32 LE/BE extent LBA,
u32 LE/BE size, 7-byte date, u8 flags (bit 1 = directory), u8 unit size, u8 gap,
u16 LE/BE volume sequence number, u8 name length, name (";1" version suffix on files).
Records never cross a sector boundary: a zero length byte means "skip to the next sector".
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from dcrip.disc.gdi import GdImage

PVD_OFFSET = 16
MAX_DEPTH = 16


@dataclass
class Entry:
    path: str
    name: str
    lba: int
    size: int
    is_dir: bool


@dataclass
class Volume:
    label: str
    root_lba: int
    root_size: int
    entries: list[Entry]

    @property
    def files(self) -> list[Entry]:
        return [e for e in self.entries if not e.is_dir]


def _records(data: bytes):
    i = 0
    n = len(data)
    while i < n:
        length = data[i]
        if length == 0:
            i = (i // 2048 + 1) * 2048
            continue
        if i + length > n:
            break
        rec = data[i : i + length]
        i += length
        name_len = rec[32]
        name = rec[33 : 33 + name_len]
        if name in (b"\x00", b"\x01"):
            continue
        lba = struct.unpack_from("<I", rec, 2)[0]
        size = struct.unpack_from("<I", rec, 10)[0]
        flags = rec[25]
        text = name.decode("ascii", "replace")
        if ";" in text:
            text = text.split(";", 1)[0]
        yield text, lba, size, bool(flags & 0x02)


def walk(img: GdImage) -> Volume:
    pvd_lba = img.first_data.lba + PVD_OFFSET
    pvd = img.read_sector(pvd_lba)
    if pvd[1:6] != b"CD001":
        raise ValueError(f"no ISO 9660 primary volume descriptor at LBA {pvd_lba}")
    label = pvd[40:72].decode("ascii", "replace").strip()
    root = pvd[156:190]
    root_lba = struct.unpack_from("<I", root, 2)[0]
    root_size = struct.unpack_from("<I", root, 10)[0]
    entries: list[Entry] = []
    seen: set[int] = set()

    def rec(dir_lba: int, dir_size: int, prefix: str, depth: int) -> None:
        if dir_lba in seen or depth > MAX_DEPTH:
            return
        seen.add(dir_lba)
        try:
            data = img.read(dir_lba, dir_size)
        except ValueError:
            return
        for name, lba, size, is_dir in _records(data):
            path = f"{prefix}{name}"
            entries.append(Entry(path=path, name=name, lba=lba, size=size, is_dir=is_dir))
            if is_dir:
                rec(lba, size, path + "/", depth + 1)

    rec(root_lba, root_size, "", 0)
    return Volume(label=label, root_lba=root_lba, root_size=root_size, entries=entries)
